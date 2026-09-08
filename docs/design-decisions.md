# Design Decisions — airwire

> **Status:** living document, started 2026-07-28.
> **Scope:** the [airwire](../README.md) product track only, same boundary as
> [roadmap.md](./roadmap.md) — nothing about airwave's audio/channel work belongs here.
> **Format:** each entry is a point-in-time record of a real trade-off made in the
> [`core/`](../core/) implementation — the problem, what was tried, what it costs, and what's
> still open. Entries are numbered and never renumbered or rewritten in place; a decision that
> gets superseded gets a *new* entry that links back to the old one.

## 1. Minimizing cryptography overhead

**Status:** implemented — [`core/sources/chunking.py`](../core/sources/chunking.py),
[`core/sources/crypto.py`](../core/sources/crypto.py).

### The problem

SMS gives 160 ASCII characters per message — 120 raw bytes once base64-decoded. Any per-message
crypto overhead (a nonce, an authentication tag, routing metadata) is a fixed tax on that tiny,
fixed budget — the smaller the message, the larger the tax as a fraction of what actually gets
through.

### Iteration 1 — per-chunk AEAD (superseded)

The first working version encrypted every ~83-byte wire chunk independently: a 4-byte message ID,
16-byte receiver ID, and 16-byte tag as a cleartext header, keyed to a symmetric X25519-derived
key. Building it against the README's exact numbers immediately surfaced two real gaps:

- The README's overhead table never budgeted XChaCha20's 24-byte nonce at all. Fixed by deriving
  the nonce deterministically from `(message_id, chunk_index)` instead of transmitting it — AEAD
  needs nonce *uniqueness*, not randomness, and those two values are already unique per chunk by
  construction.
- The table also didn't reserve space for the chunk index the README's prose mentions. Fixed by
  adding one byte (7-bit index + "is last" flag).

Net result: **83 of 120 raw bytes usable per chunk (69%)**, paid on *every single chunk*
regardless of message length — a 1024-byte message needed 13 chunks and 1505 raw bytes,
**68.0% efficiency**, with no delivery confirmation of any kind.

### Iteration 2 — hyperslice/hyperchunk model

The real fix wasn't a smaller header, it was paying the header cost less often. A message is now
cut into large **hyperslices** (configurable, 1KB by default) and each hyperslice is encrypted as
a *single* AEAD operation — one nonce, one tag, covering the whole 1KB, not each individual
outgoing message. The resulting ciphertext is then split into wire-sized **chunks** that carry
almost no overhead of their own: just a plain sequence number, 1 to 8 bytes wide depending on how
many chunks are actually needed, with no per-chunk crypto at all. One small header message
(`HyperchunkHeader`) precedes the chunk sequence, carrying the nonce/tag/chunk-count/chunk-ID-width
needed to reassemble and verify them. The receiver acknowledges the whole hyperslice at once;
on any failure — missing chunk, bad tag, timeout — the *entire* hyperchunk is retried, up to a
configured limit.

Measured against the shipped defaults (1KB hyperslice, 120-byte chunks):

| | Iteration 1 (per-chunk) | Iteration 2 (hyperslice) |
|---|---|---|
| Messages for 1024 bytes of data | 13 | 10 (+ 1 tiny ack) |
| Total raw bytes on the wire | 1505 | 1126 |
| Raw-byte efficiency | 68.0% | **90.9%** |
| Delivery confirmation | none | yes (ack + retry) |

Fewer outbound messages *and* a working retry protocol the old design never had — because the
crypto tax that used to repeat every ~83 bytes now repeats every ~1024.

### Iteration 3 — encrypting the header and ack

The header and the one-byte success/failure ack were still sent in the clear. Both are now
`HyperchunkHeader`/`HyperchunkAck` Protobuf messages ([`hyperchunk.proto`](../core/sources/proto/hyperchunk.proto)),
serialized and then encrypted as a whole (fresh random nonce, same session key) before going on
the wire, and each hyperchunk now carries a session-scoped `hyperchunk_id` so an ack can be tied
back to the transfer it belongs to.

This is a deliberate case of **spending a little overhead to buy security properties**, not
minimizing overhead for its own sake: the header grew from a 49-byte cleartext struct to a
93-byte encrypted blob (still just once per 1024-byte hyperslice, so the efficiency figure above
barely moves). In exchange:

- **Metadata confidentiality.** Previously, anyone observing the wire — without the key — could
  read a hyperslice's exact size and chunk count directly off the cleartext header. They can't
  now.
- **Uniform tamper handling.** Before, a corrupted header field surfaced through indirect
  effects (a reassembly-length mismatch, a downstream tag failure on the data) rather than a
  direct check on the header itself. Now the whole header is under one MAC: any tampering is a
  clean decrypt failure, the same failure mode as everything else in this module.
- **Ack correlation**, which also happens to close two gaps flagged when the hyperslice model was
  first built: the sender can now tell an ack for the *current* hyperchunk apart from a stale or
  cross-session one, and the header's content is no longer visible to a passive observer at all.

### Accepted trade-off, carried forward

Header, ack, and data all currently share one symmetric key, distinguished only by using a fresh
nonce each time. That's standard practice, but it is a simplification — a domain-separated key
per message class would be more conservative, at the cost of session-setup machinery that doesn't
exist yet. Not revisited here; flagged for whenever session setup gets designed.

### TODO: further overhead reduction (not yet implemented)

Roughly in order of expected payoff for the effort. Each of these is a candidate change to
[`core/sources/chunking.py`](../core/sources/chunking.py).

- [ ] **Derive the header/ack nonce instead of transmitting it** — tried for the ack, measured a
      real win, and then deliberately reverted; still not done for the header, which is impossible
      as originally described. Recorded in full because the dead ends here are informative, not
      just the outcome:
      - **The header's nonce can't be derived from `hyperchunk_id`, full stop.** `hyperchunk_id` is
        a *field inside* the header — the receiver only learns it by decrypting the header, so
        deriving the header's own decryption nonce from it is circular (you'd need the nonce to
        learn the value you need to compute the nonce). No way around this without either
        transmitting something else in the clear (defeats the metadata-confidentiality point of
        encrypting the header at all -- decision #1, iteration 3) or making the header
        re-transmitted-per-retry instead of cached-and-resent (see the retry-counter dead end
        below for why that's a bigger change than it looks). The header's nonce stays fresh and
        random, embedded as before.
      - **The ack's nonce *can* be derived from `hyperchunk_id`** — the side decoding an ack
        already knows which hyperchunk it's waiting for, no circularity — but naively deriving
        from `hyperchunk_id` alone is a real bug, not a theoretical one: the same hyperchunk ID
        legitimately gets acked more than once with *different* outcomes across ordinary retries
        (a lossy attempt failing, a later one succeeding — exactly what
        `test_send_and_receive_hyperchunk_over_a_lossy_channel` exercises), which would reuse a
        nonce across two different plaintexts under the same key — the one thing AEAD nonces must
        never do, and a serious break for a Poly1305-based AEAD specifically (nonce reuse there can
        leak the authenticator key, enabling forgery, not just a confidentiality dent). *Not* a
        false alarm from over-caution, either: a repeated failure ack for the same ID (channel
        stays bad, never succeeds) reuses the derived nonce too, but with the *same* plaintext each
        time, which is the one case AEAD's rule doesn't forbid (repeating an identical
        `(nonce, plaintext)` pair just reproduces the same ciphertext — no keystream reuse against
        different content, so no break) — worth spelling out since it's easy to conflate "nonce
        reused" with "nonce reused unsafely" and they're not the same thing.
      - Fixed the failure/success case by folding `success` into the derivation too
        (`sources/chunking.py`'s `_ack_nonce`, since removed — see below), so every distinct ack
        plaintext got its own nonce; decoding recovered `success` by trying both of its two
        possible derivations and taking whichever one authenticated. Measured: ack size dropped
        from 44 to 20 bytes (**54.5%**, better than the ~26% estimated for the header, which wasn't
        attempted — smaller messages benefit proportionally more from dropping a fixed 24-byte
        cost).
      - **Two alternatives to the "try both" trial-decryption step were explored and rejected:**
        - *A short random salt, transmitted alongside the ack, folded into the derivation instead
          of `success`.* Any nonzero salt size is strictly more bytes than the zero transmitted by
          the derived-from-`success` version, so it can only ever be a worse deal on the metric
          this whole decision is about — and it reintroduces a genuine, calculable collision risk
          the derived version doesn't have at all (a 2-byte salt reaches ~1% collision risk after
          just 36 acks under one key, by the birthday bound; a 2-byte salt was the size actually
          proposed). Even a large-enough salt to make that risk negligible (~8 bytes, ~2⁻³²-ish
          over billions of messages) still costs more bytes than deriving from `success` costs
          zero.
        - *A retry-attempt counter, `(hyperchunk_id, attempt_number)`, never transmitted, both
          sides "just know" which attempt this is.* Looked promising by analogy to the original
          per-chunk design's `(message_id, chunk_index)` derivation, but the analogy doesn't
          actually hold: a chunk index is agreed by construction (both sides derive it from the
          data's own structure), while an attempt number is only agreed if both sides track
          *identical send/receive history* — and `send_hyperchunk` resends byte-identical cached
          messages per retry with no attempt number anywhere in them, so the receiver has no signal
          to read one off of, and can't reliably reconstruct the sender's local counter on a channel
          lossy enough to need retries in the first place (duplication or loss between them can
          desync the two counts silently). Making this real would mean the sender re-serializing
          and re-encrypting the header fresh on every retry with an explicit attempt field, instead
          of resending cached bytes — a real architecture change, to remove a trial-decryption step
          that was already free.
      - **Why reverted despite working:** the "derive from content, try all candidates on decode"
        trick fundamentally requires the ack's content to be small and enumerable — fine for
        today's boolean `success`, but it cannot survive
        [selective retransmission](#todo-further-overhead-reduction-not-yet-implemented) (the next
        item on this list), which wants the failure ack to carry *which chunk indices are missing*
        — an open-ended list, not a 2-way choice, and not practically enumerable to trial-decrypt
        against. Rather than ship something known to need ripping out for a change already on this
        same list, the ack reverted to a plain random embedded nonce (44 bytes, unchanged from
        before this was ever tried).
      - `sources/crypto.py`'s `derive_nonce` helper (BLAKE2b-based, built for this) stayed in the
        codebase despite its one caller being reverted — it's a generically useful primitive, and
        the natural next place for it is the *data* nonce: `HyperchunkHeader.nonce` is currently a
        random value transmitted as an explicit header field, but by the time it's needed (data
        decryption happens strictly after the header is already decrypted, per `_reassemble`) the
        decoder already knows `hyperchunk_id` — no circularity, unlike the header's own encryption
        nonce. Not attempted yet; flagged here rather than acted on immediately since it deserves
        its own look at whether "same hyperchunk_id, different hyperslice content" can ever
        legitimately happen (it shouldn't, by the same uniqueness invariant the hyperchunk ID
        already relies on elsewhere, but that deserves checking on its own merits rather than
        assumed by analogy to the ack case, which is exactly the kind of assumption that turned out
        wrong twice above).
- [ ] **Inline small hyperslices.** Right now every hyperslice costs at least 2 messages (header +
      1 chunk), even when the whole ciphertext would fit alongside the header fields in one
      message. Most real chat messages are short enough that this matters — collapsing
      header+single-chunk into one message when it fits would cut the message-count floor in half
      for the common case.
- [ ] **Selective retransmission.** A failure ack currently triggers resending the *entire*
      hyperchunk. If the failure ack instead named which chunk indices were actually missing, the
      sender could resend only those — a bigger win on lossy links in practice than in the
      steady-state numbers above, since it's about wasted retries rather than per-byte overhead.
- [ ] **Adaptive hyperslice size.** Bigger hyperslices amortize the header cost further but make a
      single lost chunk more expensive to retry (the whole hyperslice resends). A link that's
      dropping chunks could shrink its hyperslice size; a clean link could grow it. Speculative,
      more complex, lower priority than the above.

## 2. Pluggable wire encodings for hyperchunk payloads

**Status:** implemented (raw bytes, base64) —
[`core/sources/encodings.py`](../core/sources/encodings.py),
[`core/sources/chunking.py`](../core/sources/chunking.py). Disguised-text encoding not
implemented yet.

### The gap: chunk payloads were always raw ciphertext

Decision #1 fixed how much crypto overhead a hyperchunk pays. It says nothing about what the
*chunk payload bytes themselves* look like on the wire — until now, `pack_hyperchunk` always
emitted the raw ciphertext unmodified, split at fixed byte boundaries. The
[product README](../README.md#mms-support-premium) commits to disguise strategies beyond that
(Markov-chain text, image steganography); building the first one meant deciding how it plugs into
the existing chunk-ID/header/ack/retry machinery, rather than becoming a second, parallel chunking
implementation.

### The complication: predictable vs. unpredictable expansion

The original packer sliced ciphertext into fixed `usable_per_chunk`-byte pieces because the
transform was the identity — 1 input byte always became exactly 1 output byte, so
`chunk_count = ceil(len(ciphertext) / usable_per_chunk)` could be computed directly. That
arithmetic breaks for any other encoding: base64 has a fixed but non-1:1 ratio (3 input bytes → 4
output bytes), and a Markov-chain encoding's ratio isn't fixed at all — how many ciphertext bits a
given generated word represents depends on how many candidate continuations the chain has at that
point in the walk, which varies word to word.

### The fix: greedy atom-based packing, chosen encoding recorded in the header

`ChunkEncoding` (`sources/encodings.py`) exposes one method, `encode_atoms(data) -> Iterator[bytes]`,
yielding indivisible output units — one raw byte for `PlainEncoding`, one base64-encoded 3-byte
group for `Base64Encoding`. `chunking._greedy_pack` walks that iterator and fills each chunk with
as many whole atoms as fit under the chunk's byte budget, starting a new chunk the moment the next
atom would overflow it. This works identically regardless of whether the encoding's expansion
ratio is fixed, and needs no upfront prediction of `chunk_count` — `pack_hyperchunk`'s existing
fixed-point loop (grow `chunk_id_size` until it's wide enough for the actual chunk count) just
re-runs the greedy pack at each candidate width instead of a ceiling-division formula, which
continues to converge for the same reason it always did.

Which encoding was used is now a field on `HyperchunkHeader` (`ChunkEncoding encoding = 7`), so
`unpack_hyperchunk`/`receive_hyperchunk` can invert it without the caller needing to configure it
out of band — the same reasoning as `chunk_id_size` living in the header rather than being
guessed. Since the header is already encrypted end to end (decision #1, iteration 3), recording
this costs nothing in metadata confidentiality.

### Base64 as a deliberate middle tier

Alongside raw bytes and (eventually) fully disguised text, `Base64Encoding` was added as a third,
simple option: visible ASCII, but not plausible as an innocuous message on its own — a middle
ground between "obviously opaque binary" and "meant to pass as an ordinary message." Its atoms are
always exactly 4 bytes (base64 pads only the final partial group of the whole message, never an
intermediate one), so it also doubles as a second, simpler exercise of the same greedy-packing
machinery before the harder Markov-chain encoding gets built on top of it.

### Follow-up

`ChunkEncoding.MARKOV` was reserved in the wire format here but not implemented yet at the time
this entry was written — see [decision #3](#3-the-markov-chain-text-disguise-encoding) for how it
was actually built, and the determinism constraint (no floating point, no ML inference, anywhere
in the encode/decode-critical path) that shaped it.

## 3. The Markov-chain text disguise encoding

**Status:** implemented — [`core/sources/markov.py`](../core/sources/markov.py). English
(`MARKOV_ENG`) and Russian (`MARKOV_RUS`) both work and are both wired into `unpack_hyperchunk`'s
auto-detection (see "Known limitation, since resolved" below).

### Why not just use an existing entropy-coding library

The obvious-looking plan was [`constriction`](https://pypi.org/project/constriction/): MIT/Apache/
BSL-1.0 licensed, prebuilt wheels, and documentation that explicitly promises "exactly invertible
fixed-point arithmetic" — precisely the determinism this needs. It was tried first, hands-on,
before writing any project code against it.

It didn't work out, for a structural reason rather than a bug: `constriction`'s public API is
shaped for compressing/decompressing an *already-known* number of symbols (`decoder.decode(model,
9)` — you tell it how many). This module's actual question is the reverse: *how many words does it
take to represent this many bytes* — the symbol count is exactly what's unknown going in. Every
way of coercing `constriction` into answering that (padding the input and hoping the decoder
tolerates reading past the real data, tracking `RangeEncoder.get_compressed()`'s growth to guess
when "enough" had been decoded) failed empirically: its `RangeDecoder` doesn't error on the first
out-of-bounds read, but decoding enough further symbols eventually corrupts its internal state and
raises an unrecoverable assertion — confirmed directly, not inferred from docs, with padding sizes
from a few hundred bytes up to many kilobytes, zero-filled and randomly-filled alike. Its own
`maybe_exhausted()` docs hint at exactly this: "cannot detect end-of-stream in all cases... append
an end-of-stream sentinel symbol." That sentinel-based idiom fits compressing a message whose
*symbol* content is already fully known upfront; it doesn't fit this module's shape, where the
symbols (words) are themselves the output being discovered step by step.

### What was built instead

A small binary arithmetic coder, written from scratch directly against the frozen model's integer
counts, adapted from the structure of Hernan Moraldo's reference implementation
([github.com/hmoraldo/markovTextStego](https://github.com/hmoraldo/markovTextStego), previously
identified as prior art for this feature) — a proven design (its own bundled self-tests pass) that
already solves the exact-termination problem this needs, by tracking "how many source bits remain"
as an explicit value it owns, rather than asking an external library to report it:

- A binary interval `[low, high]` (arbitrary-precision Python integers) narrows every time a word
  is chosen, proportional to that word's share of its Markov state's total corpus-frequency count.
- The interval widens (gains binary digits) only when the current width can't distinguish all of a
  state's candidates, and *only ever up to how many real source bits are actually left* — this cap
  is what makes the walk exactly self-terminating. It never asks for more precision than there is
  real data to supply it, so it always stops after consuming exactly the right number of bits, with
  no length prefix or sentinel needed on the wire — `HyperchunkHeader.hyperchunk_length` already
  carries the target byte count, reused rather than duplicated (see decision #1's whole theme).
- Whenever `low` and `high` agree on their leading bits, those bits are locked in regardless of
  what's chosen from here on, and get popped off both the interval and the source-bit cursor —
  ordinary arithmetic-coding renormalization.
- Decoding replays the identical walk *forwards* from the same begin state, using each observed
  word to look up the sub-interval it must have occupied when chosen, and accumulates the same
  locked-in bits into the output instead of reading them from a cursor.

One deliberate departure from Moraldo's own arithmetic: his version splits each state's range
proportionally using **floating-point** division (`step = range_size * 1.0 / denominator`). Scalar
IEEE-754 double arithmetic is actually platform-portable for this — the non-determinism risk
flagged in decision #1's TODOs is specifically about parallel/vectorized reduction order (GPU
kernels, SIMD-batched BLAS), which doesn't apply to a single sequential Python float op — but since
an equally simple **exact-integer** alternative was available (cumulative count scaled by the
range size, floor-divided: `(cumulative * range_size) // denominator`), that was used instead.
Zero floating point anywhere in the encode/decode-critical path, not just an argument for why the
floating point that's there is safe.

Hands-on validation (not just unit tests against the shipped frozen models) covered: round trips
across byte lengths from 0 to several KB against both a synthetic low-branching-factor model and
the real per-language frozen chains; determinism (identical input always produces an identical word
sequence); and that tampering a chosen word either fails closed with a clear error (the word isn't
a valid continuation at that point in the walk) or silently changes the recovered bytes, which is
fine — the outer AEAD tag (decision #1) is what actually has to catch tampering, the same
fail-closed contract every other encoding already relies on.

### Known limitation, since resolved: no per-hyperchunk language selection

`HyperchunkHeader.encoding` used to be a single `MARKOV` value shared by every language's model —
it didn't say *which* frozen chain was used, only that some Markov-disguised text was. Both
`MARKOV_ENG` and `MARKOV_RUS` encoded and decoded correctly on their own, but
`sources.encodings._ENCODINGS` (what `unpack_hyperchunk` consults for header-driven
auto-detection) could only map that one identifier to one instance — `MARKOV_ENG`. Packing with
`MARKOV_RUS` and then unpacking through the normal `pack_hyperchunk`/`unpack_hyperchunk` path
reliably failed, because the receiver ended up walking the English chain against Russian text.
This was caught by hand-testing the demo script's `--mode` end to end (not by the unit tests,
which exercise `MarkovEncoding.decode` directly against a matching instance and so never touched
the registry) — a reminder that a "does the interface round-trip" test and a "does the
*wired-together system* round-trip" test can pass and fail independently of each other.

Resolved as a side effect of wiring up image steganography (decision #4) and the handshake
(decision #5): every disguise variant, Markov language or texture flavor alike, now gets its own
`ChunkEncoding` identifier (`MARKOV_ENG = 2`, `MARKOV_RUS = 3`, the `SYNTHESIS_*` values), so
auto-detection picks the right one directly from the header, same as any other encoding choice.
This wasn't optional scope creep — `sources/handshake.py`'s obfuscation-mode derivation needs to
select a *specific* language or flavor deterministically, which a shared identifier can't express.

## 4. Image steganography: patch-based texture synthesis (prototype)

**Status:** prototype — [`core/sources/synthesis.py`](../core/sources/synthesis.py),
[`core/sources/textures.py`](../core/sources/textures.py). Round-trips correctly for all four
texture flavors; visual quality is still a work in progress for two of them.

### Starting point: Wu & Wang, adapted rather than ported

[Wu & Wang's "Steganography Using Reversible Texture Synthesis"](https://ieeexplore.ieee.org/document/6957552/)
(IEEE TIP, 2015) was identified earlier as the closest prior art: non-neural, and — unlike most
image steganography — designed from the ground up to be exactly reversible rather than merely
low-distortion. Its mechanism: divide a small source texture into a library of patches, synthesize
a larger canvas by repeatedly ranking library patches by how well they'd blend with whatever's
already been placed next to them, and use secret bits to choose *which rank* to place rather than
always the best match — recoverable because the receiver can re-derive the same ranking and read
off which one was actually used.

Two deliberate departures from the paper, once the actual mechanism was pinned down (fetched and
read directly, not worked from search-result summaries, after an earlier attempt to describe it
from indirect sources turned out too vague to build against):

- **Regular seed/gap rows instead of an irregular scatter-then-fill-gaps layout.** Wu & Wang
  scatter whole patches at arbitrary positions and fill irregularly-shaped gaps between them. This
  implementation alternates whole, untouched **seed rows** (placed by a fixed, position-only rule,
  carrying no secret data) with synthesized **gap rows** (one patch at a time, secret-bit-driven).
  Much simpler to implement and reason about, at a real cost: less space-efficient than an optimal
  irregular packing, and the regularity is itself a visible tell once you know to look for it.
- **No source-texture recovery.** Wu & Wang also recover the exact original source texture from
  the stego image, because in their setting the texture itself is secret content, which needs an
  index-table bookkeeping layer of its own. Here the source texture is a public, regenerable
  codebook (`sources/textures.py`, seeded procedurally rather than downloaded) that both ends
  already have independently, so that whole mechanism is simply not needed and isn't built.

The result reuses `sources/arithmetic.py` (factored out of `sources/markov.py` for exactly this
reuse) essentially unchanged: "candidates weighted by corpus frequency" becomes "candidates
weighted by inverse boundary-match cost," and the coder doesn't know or care about the difference.

### What actually limits visual quality right now

An earlier, simpler version (every canvas position synthesized in raster order, no seed rows at
all) was tested first and visibly failed on textures with large-scale structure: a Voronoi
diagram's flat cells shattered into small incoherent fragments, and a reaction-diffusion pattern's
continuous tubes degraded into disconnected speckle noise. Root cause: the blend-cost function
only ever compares a single pixel-wide edge between immediate neighbors, which has no way to keep
a feature that spans many patches coherent.

Introducing seed rows (this decision) measurably improved both cases — reaction-diffusion in
particular went from unrecognizable noise to a distinct, if blockier and more angular than the
source, connected pattern — because most of a gap row's neighbors are now genuine untouched
texture rather than other synthesized guesses. It did not fully fix either one: Voronoi's cells
are still visibly more fragmented than the source, because a gap row is only one patch tall and a
real cell can easily be several patches wide. Locally-stationary textures (`value_noise`) were
fine even before this change and remain fine now.

### Widening the blend-cost overlap window — tried, measured, reverted

The natural next fix looked like comparing more than the single touching row of pixels at each
boundary — the same reasoning behind Efros & Freeman's overlap-region cost in image quilting, one
of the two non-neural prior-art techniques this module started from. Implemented as an `OVERLAP`
parameter (comparing the first/last `OVERLAP` rows or columns of a candidate against the matching
region of its already-placed neighbor, instead of just row/column 0), and measured against a
deliberately independent metric — not the cost function's own output, but the actual mean squared
color difference at the *visible* seam between horizontally-adjacent gap-row patches in the
rendered canvas, for a fixed (non-random, for a fair comparison across settings) input payload:

| `OVERLAP` | Voronoi seam MSE | Reaction-diffusion seam MSE |
|---|---|---|
| 1 (baseline) | 4721.9 | 8032.3 |
| 2 | 4630.1 | 8386.6 |
| 3 | 4767.9 | 8670.8 |
| 4 | 4640.5 | 8722.8 |
| 5 | 4627.2 | 9069.6 |
| 6 | 4704.2 | 9095.3 |

Not an improvement — reaction-diffusion gets monotonically *worse* as the window widens, and
Voronoi shows no clear trend at all (noise-level fluctuation around the baseline). Reverted;
`_candidate_weights` is back to the original single-row comparison.

**Why this is believed to have failed**, worth recording so the same idea isn't re-tried the same
way: Efros & Freeman's overlap-region cost works because their algorithm is a hard minimizer — it
always places the single best-matching patch (then cuts a minimum-error seam through the overlap).
This module's coder is fundamentally not that: candidate costs become arithmetic-coder *weights*,
and which candidate actually gets placed is driven by the ciphertext bits being carried, weighted
toward cheap options but by no means restricted to the cheapest one — if it only ever picked the
best match, the walk would carry zero bits of information, which defeats the entire point. A wider
overlap changes the absolute and relative scale of every candidate's cost, but nothing here
establishes that this reshapes the resulting weight distribution in the direction that helps
picking a *randomly-selected-but-weighted* candidate look right, the way it reliably helps a
strict minimizer. Confirming that mechanism precisely (e.g. measuring whether the weight
distribution actually gets flatter, not sharper, as the window widens) wasn't done — this is a
reasoned hypothesis for *why* the measurement came out this way, not a proven root cause.

### Not yet decided

- Widening the blend-cost comparison was tried and measurably didn't help (see above). Still open:
  shrinking gap rows relative to seed rows, or trying Wu & Wang's own irregular scatter after all,
  to close the remaining gap on large-structure textures.

### Wire integration: one image *is* a `ChunkEncoding` atom

Resolved the two open questions above (where this plugs in, SVG vs. a real wire format) together,
since the answer to one shaped the other:

- **Each texture flavor is its own `ChunkEncoding`** (`ImageEncoding` in `sources/synthesis.py`,
  four registered identifiers — `SYNTHESIS_VALUE_NOISE`/`VORONOI`/`REACTION_DIFFUSION`/`ATTRACTOR`
  — one per flavor, in `hyperchunk.proto`), and `encode_atoms` yields exactly **one atom: the whole
  synthesized image**, rather than many small pieces. That one atom fills exactly one wire chunk,
  so `pack_hyperchunk` produces `[header, one big chunk]` for an image hyperslice — precisely the
  "one hyperslice → one image" MMS-attachment shape the product README already described, achieved
  by reusing every bit of `chunking.py`'s existing header/ack/retry machinery unchanged, just with
  a `chunk_size` set to an MMS-scale budget instead of an SMS one, rather than inventing a second
  delivery path. Picking the flavor via the encoding identifier (rather than a session-negotiated
  convention) also means it costs nothing extra on the wire — the `encoding` field already exists
  in the header regardless of which `ChunkEncoding` is chosen.
- **PNG, not SVG, is the wire format.** The demo's SVG output (tile `<defs>`/`<use>`) was
  convenient for eyeballing prototype output but was never a realistic wire format: most carriers
  don't accept SVG as an MMS attachment at all, and it's the largest of the realistic options
  (base64-encoded tile data URIs plus XML markup). PNG is lossless (verified: Pillow round-trips
  this module's `uint8` canvas arrays bit-exact), a real, directly-attachable, viewable image file,
  and smaller than the SVG encoding. `to_svg`/`save_svg` stay in `sources/synthesis.py` as a
  debugging/inspection tool, just no longer in the default wire path.
- **The payload image's source-texture seed is derived from the hyperslice's own AEAD nonce**
  (`HyperchunkHeader.nonce`, already random and unique per hyperchunk, already transmitted) rather
  than given a new field or a fixed value — real per-message texture variety at zero extra wire
  cost. This is safe specifically because texture choice was already established above to need no
  confidentiality: reusing the nonce for a second, unrelated, non-secret purpose alongside its AEAD
  role doesn't create a nonce-reuse problem, since nothing about AEAD security depends on the nonce
  *also* being unpredictable or single-purpose. This needed `ChunkEncoding.encode_atoms`/`decode`
  to gain a `nonce: bytes` parameter (mirrors how `length` already works on `decode` — most
  encodings ignore it, the one that needs it uses it).
- Real MMS carrier transcoding/recompression (which could silently destroy the bit-exactness this
  scheme depends on) is explicitly out of scope for Phase 0 — this is a platform/mobile-phase
  concern once real carriers are involved, not something a Python proof of concept can validate.

## 5. Session handshake

**Status:** designed, implementation in progress — see [`docs/handshake.md`](./handshake.md) for
the full design (this gets its own document rather than an entry here, since it's one coherent
protocol rather than a single trade-off).

Establishes the session key `chunking.py` has always assumed already exists, and — the harder
problem — makes sure the disguise chosen for a sender's messages never visibly changes between the
first handshake message and the last data acknowledgement, even though the encryption key
underneath does. Both the disguise choice and the handshake's own bootstrap key are derived
directly from each sender's public, transport-visible identifier, needing no prior exchange at
all; deliberately plain TOFU (no persistent signing identity), with the resulting first-contact
MITM exposure recorded as an accepted, revisitable trade-off rather than an oversight. Also
records the reasoning for an eventual post-quantum hybrid key exchange, not implemented now.
