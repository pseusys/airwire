# Wire protocol — how a message actually gets encrypted, split, disguised, and sent

*keywords:* hyperslice, hyperchunk, chunking, arithmetic coding, ChunkEncoding, disguise, source of truth, pack_hyperchunk

`AGENTS.md` says what the project does in five lines; this says how, in enough depth to predict the
system's behavior in a situation the code alone does not cover.
For the steganography mechanism specifically (how bits become plausible text or a plausible image),
see [`../core/README.md#how-the-steganography-works`](../core/README.md#how-the-steganography-works)
— that document already covers it in depth and is not duplicated here.
For the session handshake and the crypto scheme (including where the currently-implemented crypto
diverges from the target spec), see [`handshake.md`](handshake.md).

## The core idea

A message never goes on the wire looking like ciphertext.
It is cut into pieces, each piece is encrypted as one AEAD operation, and the resulting ciphertext
bytes are re-rendered — via a shared arithmetic-coding trick — as either plausible natural-language
sentences or a plausible generated image, so a passive observer sees something ordinary instead of
opaque binary.
The same arithmetic coder (`core/sources/arithmetic.py`) drives both disguises: for text, candidates
are Markov-chain next-words weighted by corpus frequency; for images, candidates are texture patches
weighted by inverse blend-cost.
The coder itself doesn't know or care which.

## Lifecycle

One hyperslice's round trip, in order:

1. **Slice.** `slice_hyperslices` cuts the plaintext into `hyperslice_size`-byte pieces (1KB by
   default, last one may be shorter).
2. **Encrypt.** `pack_hyperchunk` AEAD-encrypts one hyperslice as a single operation (one nonce, one
   tag, covers the whole slice) — `core/sources/crypto.py`'s `Symmetric.encrypt`.
3. **Encode.** The ciphertext is handed to a `ChunkEncoding` (`core/sources/encodings.py`):
   `encode_atoms(data, nonce)` yields indivisible output units (raw bytes, base64 groups, Markov
   words, or — for images — exactly one atom, the whole synthesized PNG).
4. **Pack.** `_greedy_pack` fills each wire chunk with as many whole atoms as fit under the chunk's
   byte budget, starting a new chunk the moment the next atom would overflow it.
This is why one
   encoding's output-length-per-input-byte doesn't need to be predictable in advance.
5. **Header.** One `HyperchunkHeader` message (nonce, ciphertext length, chunk count, tag, chunk-ID
   width, chosen encoding) precedes the chunk sequence — itself serialized and AEAD-encrypted (and,
   optionally, disguised the same way payload atoms are) before transmission.
6. **Send + retry.** `send_hyperchunk` sends `[header, chunk_0, chunk_1, ...]`, then waits for an
   ack naming this exact `hyperchunk_id` with `success=True`.
Anything else — wrong ID, malformed
   ack, timeout — retries the *whole* hyperchunk (header included), up to `DEFAULT_MAX_RETRIES`.
7. **Receive + reassemble.** `receive_hyperchunk` decrypts the header, gathers every named chunk
   index, reassembles and decodes the ciphertext, decrypts it, and sends back one ack.
   If the header itself fails to decrypt, nothing is sent back at all (the sender is expected to
   time out and retry) — there is no `hyperchunk_id` to acknowledge yet.

The common path is a clean single round trip (send once, get a matching success ack) — retries exist
for a lossy channel, not as the expected case.

## Data flow

Producer → transport → consumer, for one hyperslice: application plaintext → `pack_hyperchunk`
(in-process function call, not a queue) → a list of wire messages → whatever transport the caller
supplies (`send: Callable[[bytes], None]`, medium-agnostic) → the peer's `receive_hyperchunk` → the
original plaintext, plus one ack sent back over the same transport.
Nothing here owns a queue, a socket, or a background task — `chunking.py` is pure transformation
logic; `send`/`receive_ack` are injected by whatever actually moves bytes (a `Medium` implementation,
see [`medium.md`](medium.md), or the demo scripts).

## Termination and exit order

A hyperchunk transfer ends one of three ways, and only one of these three wins for a given attempt:

1. **Success** — an ack for this exact `hyperchunk_id` with `success=True` arrives. `send_hyperchunk`
   returns normally.
2. **Retries exhausted** — `max_retries` attempts all failed to produce a matching success ack.
   `HyperchunkDeliveryError` is raised; nothing is retried further automatically.
3. **Undecryptable header on receive** — `receive_hyperchunk` returns `(None, None)`; the sender's
   own retry loop (case 2, eventually) is what ends this, not anything on the receive side.

## Source of truth

**`core/sources/crypto.py`, `chunking.py`, and `handshake.py` are what the protocol actually does
right now**: one symmetric key per session (`Symmetric`, XChaCha20-Poly1305), a fresh random nonce
per hyperslice embedded in the AEAD-encrypted header, no key rotation, no per-direction keys, no
message counter.

`docs/superpowers/specs/2026-08-27-messaging-protocol-design.md` and the crypto scheme it summarizes
in [`handshake.md`](handshake.md) (directional keys, key rotation via `material`, derived
per-message nonces) describe a **different, not-yet-implemented target design** for the same
protocol — the spec itself says `core/` "is not this protocol and will not necessarily match it
field-for-field once this spec is done."
Reading `crypto-summary.md`'s scheme as describing what `core/` does today produces confidently
wrong analysis; see `handshake.md` for both, clearly separated.

`docs/design-decisions.md` no longer exists as a live document — its still-current reasoning was
folded into this file and `handshake.md`; its settled rejections are in
[`rejected-ideas.md`](rejected-ideas.md); its full history is in [`../CHANGELOG.md`](../CHANGELOG.md).

## Components

- **`core/sources/chunking.py`** — the lifecycle above: `pack_hyperchunk`/`unpack_hyperchunk`,
  `send_hyperchunk`/`receive_hyperchunk`, `_greedy_pack`.
Owns no transport and no session state.
- **`core/sources/crypto.py`** — `Symmetric` (XChaCha20-Poly1305 AEAD), `Asymmetric` (X25519 with a
  keyed-XOR public-key-hiding trick), `derive_key`/`derive_nonce` (BLAKE2b, public/non-secret-safe
  derivation — safe as long as the derivation inputs never repeat for two different plaintexts under
  the same key).
- **`core/sources/encodings.py`** — the `ChunkEncoding` interface (`encode_atoms`/`decode`, both take
  a `nonce: bytes` — most encodings ignore it, the ones that need it use it) plus `PlainEncoding` and
  `Base64Encoding`.
- **`core/sources/arithmetic.py`** — the shared binary arithmetic coder (`BitCursor`, `BitAccumulator`,
  `candidate_ranges`, exact integer arithmetic, no floating point anywhere in the encode/decode path).
  Factored out of `markov.py` once `synthesis.py` needed the identical mechanism.
- **`core/sources/markov.py`** — the text disguise.
Frozen per-language Markov chains
  (`sources/data/markov_*.json`, trained by `scripts/model.py` from `sources/corpus.py`'s Tatoeba
  corpus).
Every visited state's candidate order is shuffled by a nonce-derived permutation before
  `candidate_ranges` assigns bit ranges, so the nonce gates the whole walk, not just the cosmetic
  filler tail that completes an otherwise-truncated final sentence.
- **`core/sources/synthesis.py` + `textures.py`** — the image disguise.
Patch-based reversible
  texture synthesis (adapted from Wu & Wang 2015), four texture flavors, each its own
  `ChunkEncoding` yielding exactly one atom (the whole PNG).
The source texture's seed is derived
  from the hyperslice's own nonce — real per-message variety at zero extra wire cost, safe because
  texture choice needs no confidentiality of its own.
Every canvas position maps onto a real position in the source
  texture (`_guide_patch`), which requires the texture to be exactly `canvas_width` patches wide
  (`DEFAULT_TEXTURE_SIZE = DEFAULT_CANVAS_WIDTH * DEFAULT_PATCH_SIZE`) and, for canvases taller
  than one texture, requires the texture to tile seamlessly — true by construction for
  `reaction_diffusion` (its Laplacian is already toroidal), added deliberately for `value_noise`
  and `voronoi` (periodic grid/distance wrapping).
Two layout mechanisms exist, chosen per flavor
  via `position_guided` on `ImageEncoding`: a **scattered anchor layout**
  (`value_noise`/`voronoi`/`reaction_diffusion`) where a deterministic, seed-derived 2-D anchor
  mask (`_anchor_mask`, Poisson-disk-style dart-throwing) decides which canvas positions render
  real texture content versus synthesized content, walked in a plain row-major raster scan with
  gap cells scored against the texture's true content at that position plus already-resolved
  above/left neighbors; and the original **row-alternating layout** (`attractor` only, no
  exploitable 2-D positional structure — a sparse chaotic-orbit density histogram, not a spatially
  periodic field), scored only against local edge agreement.
`PatchLibrary` also supports
  overlapping, pixel-shifted candidates (`stride` parameter) — measured and not adopted as the
  default, see `memory/rejected-ideas.md`.
See the two 2026-09-09 entries in
  [`../CHANGELOG.md`](../CHANGELOG.md) for the before/after measurements of both changes.
- **`core/sources/handshake.py`** — see [`handshake.md`](handshake.md).

## Tunables

| Tunable | Value | Read in | What it does |
| --- | --- | --- | --- |
| `DEFAULT_HYPERSLICE_SIZE` | 1024 | `chunking.py` | Bytes of plaintext encrypted as one AEAD operation. |
| `DEFAULT_CHUNK_SIZE` | 120 | `chunking.py` | Wire chunk payload budget; matches a 160-char base64-encoded SMS's raw-byte budget. |
| `DEFAULT_MMS_CHUNK_SIZE` | 300 000 | `chunking.py` | Wire chunk budget when sending one hyperslice as an MMS attachment (one image = one chunk). |
| `MIN_CHUNK_ID_SIZE` / `MAX_CHUNK_ID_SIZE` | 1 / 8 | `chunking.py` | Byte-width range for the per-hyperchunk chunk sequence number; grows only as far as the actual chunk count needs. |
| `DEFAULT_MAX_RETRIES` | 3 | `chunking.py` | Whole-hyperchunk resend attempts before `HyperchunkDeliveryError`. |
| `HEADER_PLAINTEXT_SIZE` | 96 | `chunking.py` | Fixed padded size a serialized header is grown to before an optional header disguise, so disguised length never needs to be self-describing. |
| `DEFAULT_TEXTURE_SIZE` | 128 | `synthesis.py` | Source texture's edge length in pixels; must equal `DEFAULT_CANVAS_WIDTH * DEFAULT_PATCH_SIZE`. |
| `DEFAULT_PATCH_SIZE` | 8 | `synthesis.py` | Edge length, in pixels, of one texture patch. |
| `DEFAULT_CANVAS_WIDTH` | 16 | `synthesis.py` | Synthesized canvas width, in patches. |
| `MIN_ANCHOR_DISTANCE` | 1.1 | `synthesis.py` | Minimum toroidal grid distance between scattered anchors; excludes only orthogonally-adjacent cells, the natural maximal blue-noise packing density (~36-39%). |
| `DEFAULT_CANDIDATE_STRIDE` | `DEFAULT_PATCH_SIZE` (8) | `synthesis.py` | `PatchLibrary` candidate spacing; non-overlapping by default — see `memory/rejected-ideas.md` for why a smaller stride wasn't adopted. |
| `_FILLER_SEED_SIZE` | 4 | `markov.py` | Byte size of every derived Markov filler/permutation seed. |
