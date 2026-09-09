# Messaging Protocol — Design Spec (draft, in progress)

> **Status:** DRAFT — all sections written and self-reviewed, pending user review before proceeding
> to an implementation plan.
> **Relationship to `core/`:** the Python code in [`core/`](../../../core/) (crypto primitives,
> chunking, disguise encoders, the earlier handshake design) is a proof-of-concept and testing
> ground — useful prior art and a source of validated sub-mechanisms (the arithmetic-coder-based
> disguise trick, the TOFU handshake shape), but it is **not** this protocol and will not
> necessarily match it field-for-field once this spec is done. This document is the actual
> deliverable.
> **Relationship to the existing product docs:** [`README.md`](../../../README.md),
> [`memory/wire-protocol.md`](../../../memory/wire-protocol.md), and
> [`memory/handshake.md`](../../../memory/handshake.md)
> describe an earlier, narrower design (SMS/MMS specifically, a relay server, ack/retry over an
> assumed-lossy medium). This spec supersedes that shape with a **serverless, medium-agnostic**
> protocol. Reconciling/updating those documents is a follow-up, not part of this spec.

## 1. Purpose and scope

A **messaging protocol** — not a transport protocol — for long-lived 1:1 text chats between users
identified only by a medium-supplied ID, with no server and no shared user database anywhere.
"Medium" is deliberately abstract: SMS, a voice channel, a standalone messenger app, or another
messenger's API are all valid mediums: this spec only needs whatever a medium adapter provides (see
§2).
The transport-specific mechanics of any *particular* medium (SMS character budgets, MMS,
carrier behavior) are out of scope here — this spec defines the layer that sits on top of any
medium meeting the contract in §2.

## 2. Critical assumptions and constraints

These are starting facts about the environment, not design choices — everything else in this
document is derived from them:

1. **Serverless.** No server stores messages, ever.
All state is local to each device.
If local
   storage is cleared, everything about a chat — keys, history, the fact it ever existed — is gone
   permanently.
There is no unified user database anywhere.
2. **Medium-agnostic.** The medium's only two jobs are user identification and message delivery.
   Everything else (framing, compaction, obfuscation, encryption, handshake) is this protocol's
   job, independent of which medium is underneath.
3. **Identity is medium-supplied, public, and not secure.** Every user has a unique ID defined by
   the medium (a phone number, a platform user ID, etc.).
Anyone who knows a peer's ID can address
   them.
An ID is not private and carries no cryptographic guarantee — it can be used as
   *input* to encryption/obfuscation bootstrapping (see §4), but never as a source of actual
   secrecy.
A real, cryptographically-secure handshake is required at the start of every chat (and
   periodically thereafter) to establish anything trustworthy.
4. **The medium is reliable, but constrained.** Medium messages can be small, and can be costly to
   send (SMS is the motivating example) — so payloads must be compacted, not sent raw.
Medium
   messages may also take a long time to arrive.
In exchange, the medium is trusted for: lossless
   delivery, in-order delivery (per sender/recipient pair), and no silent corruption.
This protocol
   is built *on top of* that guarantee, not defensively around its absence — there is deliberately
   no application-level ack/retry/timeout machinery here, because the medium already solved that
   problem.
(This assumption covers accidental loss/corruption from normal medium operation, not an
   active on-path adversary who deliberately rewrites bytes — see the security-properties section,
   §8, for where that distinction actually matters.)
5. **No arbitrary message-size ceiling.** A logical protocol message is however long it needs to be.
   It is not assumed to fit in one medium message — fragmentation across many medium messages is
   the normal path, not an edge case (see §5).
6. **Content is text only, at the protocol level.** Images exist solely as an optional disguise
   *carrier* for text ciphertext (one of several `ChunkEncoding`-style options), never as a distinct
   content type an application sends directly.
7. **One full-duplex channel per medium.** A sender cannot have two outbound messages in flight to
   the *same* recipient simultaneously (sends to that peer are serialized), but sending and
   receiving happen concurrently, and sends to *different* peers are independent of each other.
8. **Chats are strictly 1:1.** Any user can start a chat with any other user, given their ID.
There
   is no group/multi-party membership model.
"A user joins/leaves" describes a peer's reachability
   on the medium being unreliable or permanent — a peer can silently vanish (the medium may still
   claim they exist, but they never answer again) — not a membership operation on a shared chat.

## 3. Layering and the medium contract

Two layers: the **medium** (external, out of scope — SMS, a voice channel, a messenger API) and the
**messaging protocol** (this spec, medium-agnostic).
A medium adapter must provide:

- `my_id` — this device's own address on that medium (opaque bytes).
- `send(peer_id, bytes)` — hand one opaque message to a peer.
- `receive() -> (peer_id, bytes)` — incoming messages, delivered lossless, uncorrupted, and in order
  **per peer** (no ordering guarantee assumed *across* different peers' streams).
- `max_message_size` — a size budget; may vary by medium/deployment (SMS's ~140 usable bytes vs. a
  messenger API's much larger limit).

Concurrency the medium provides, per constraint 7 above: sending to *different* peers concurrently
is fine; sending and receiving concurrently is fine; only one outstanding send to the *same* peer at
a time — the protocol queues anything else addressed to that peer until the in-flight send
completes.

**Chat** = the persistent local state between `my_id` and one specific `peer_id` (exactly one chat
per peer_id).
"Restart" = that local state is discarded (cache clear, explicit reset, or the peer
going silent forever, per constraint 8) — the next message either side sends triggers a fresh TOFU
handshake, indistinguishable from true first contact.

## 4. Message envelope and compaction

A logical message (arbitrary length, text only) is encrypted once as a whole, then split into as
many medium-messages ("fragments") as its size and the medium's `max_message_size` require.
No
fragment count is predicted or reserved for in advance beyond what's described below — the design
supports arbitrarily many fragments.

**Layering, outermost to innermost, each doing exactly one job:**

1. **Disguise** (`ChunkEncoding`-style: Markov-chain text, image steganography, base64, or plain) —
   wraps whatever opaque bytes are given to it.
Cosmetic only, carries no confidentiality guarantee
   of its own.
Which encoding was used is never transmitted as a field — the receiver discovers it
   by trial-decode against the small registry of known encodings, same mechanism already proven in
   `core/sources/markov.py`'s auto-detection.
2. **Header encryption** (new in this design) — confidentiality only, no authentication tag, for
   the header fields specifically (see below for why no tag is needed for most fields, and the one
   exception).
3. **Data AEAD** (XChaCha20-Poly1305, unchanged primitive from `core/sources/crypto.py`) —
   confidentiality *and* integrity for the actual message content.

**Wire shape:**

- **First fragment** = `header_ciphertext || (as much data ciphertext as fits)`.
  - `header_ciphertext` is fixed-length: `data_tag` (16B) + `data_length` (4B, the
    plaintext/ciphertext byte length — XChaCha20-Poly1305 doesn't expand, so these are the same
    number; needed because `N` alone tells the receiver how many *fragments* to expect, not how many
    *bytes* the disguise-decoded data represents, and non-self-delimiting encodings like Markov text
    need an exact target length to replay the same arithmetic walk the sender used — see
    "Header vs. data disguise" below) + `N` (2B, count of *additional* fragments to expect) + `n_tag`
    (4B, see below) + rotation material (variable, present only on the fragment where a scheduled key
    rotation lands — see §6). `data_nonce` is *not* a field here — see below, it's derived the same
    way `header_nonce` is, not transmitted.
  - Encrypted with a plain XChaCha20 keystream (no Poly1305 step) under the sender's current
    directional key for this peer (§6), nonced from `derive_key(directional_key, "header-nonce",
    message_counter)` — `message_counter` is a persisted, monotonically-increasing count of
    messages sent/received on this specific directional key (both sides maintain their own,
    incrementing in lockstep, since delivery is reliable and in-order per constraint 4 — no
    transmission or synchronization mechanism needed beyond that).
This was originally specified as
    reusing the leading bytes of the data ciphertext instead, to avoid needing any counter at all —
    but that doesn't actually work for the receiver: recovering those bytes requires disguise-
    decoding the data portion first, which (for a non-self-delimiting encoding like Markov) needs
    the target byte length, which lives *inside* the header this nonce is meant to unlock — a real
    circularity, not just an inconvenience.
The counter avoids it entirely, costs nothing on the
    wire, and doubles as the natural input §6's rotation trigger already needs to track anyway.
  - **`data_nonce` is derived the same way, not transmitted**: `derive_key(directional_key,
    "data-nonce", message_counter)` — the identical `(key, counter)` pair `header_nonce` uses, with a
    different domain-separation label, which is what keeps the two values independent despite
    sharing an input (the standard technique for deriving several independent values from one shared
    secret, e.g. TLS 1.3's key schedule).
Safe for the same reason `header_nonce` is: the counter
    never repeats within a key's lifetime, so neither derived nonce does either.
This is genuinely
    load-bearing on the two labels staying distinct — conflating them would make `header_nonce` and
    `data_nonce` the same value, which is a real, serious problem (the two ciphers would then share a
    nonce under the same key), not just a style slip.
- **Fragments 2..N** (if any) = pure data ciphertext, zero framing bytes.
The receiver already knows
  exactly how many to expect from `N`, so no per-fragment marker is needed at all.
- A message that fits in one fragment just has `N = 0` — this is the common case, not a special
  case: short messages need exactly one medium-message, with no separate header message ever
  required (unlike the earlier `core/` design's mandatory header + ≥1 chunk floor).

**Header vs. data disguise — two independent, chained disguise operations, not one shared stream.**
The header must be fully recoverable from fragment 1 alone (that's how the receiver learns `N` in
the first place), but a variable-expansion disguise encoding (Markov text; image steganography is
single-atom and doesn't apply here) doesn't have a predictable output length for a given input length
— so header and data are disguised as **two separate `encode_atoms` calls**, each starting fresh from
that encoding's own initial state, physically concatenated within fragment 1's raw bytes with no
delimiter between them (none is needed — see below).
Decoding mirrors this: `ChunkEncoding.decode`
takes a target byte length and the *front* of an already-disguise-encoded byte stream, and returns
both the decoded plaintext and how many wire bytes it actually consumed to get there — for
Plain/Base64 this is a direct, predictable formula (no walking needed, since their expansion ratios
are fixed); for Markov, it's however many words the arithmetic walk actually needed to reach the
requested byte length, discovered by running the same self-terminating walk `encode_atoms` used.
The
header is decoded first, against `header_ciphertext`'s fixed target length; whatever wire bytes it
didn't consume are handed to a second decode call (fresh walk state, target length `data_length`) for
the data portion, continuing across any further fragments as needed.
Plain/Base64 headers need no
special handling here since their consumed-byte count is just a formula; Markov headers work through
exactly the same mechanism as Markov data, just as an independent, shorter walk.

**Minimum fragment budget for header disguise.** Because the header must fit inside one fragment,
whatever encoding disguises it needs its worst-case expansion for `header_ciphertext`'s fixed length
to fit under `max_message_size` — unlike data, which can always spill into another fragment if an
atom doesn't fit.
Each `ChunkEncoding` exposes `minimum_budget_for_header(header_ciphertext_size)`:
`header_ciphertext_size` itself for Plain (1:1), the exact base64 formula for Base64
(`ceil(size/3)*4`), and a deliberately conservative fixed multiplier of `header_ciphertext_size` for
Markov (an exact worst-case bound isn't practically computable — a corpus-driven chain could in
principle force many low-information word choices in a row — so this is a reasoned safety margin, not
a proven bound; revisit empirically against the real frozen models if it ever needs tightening).
Packing rejects up front, before doing any work, if `max_message_size` is smaller than the chosen
header encoding's minimum for the header size actually in play (base size, or base+rotation-material
size on a rotation-carrying message) — on a medium too constrained for that, Markov (or any other
variable-expansion encoding) simply isn't offered as a header-disguise choice; Plain/Base64 always
qualify.

**Compaction — how much ciphertext actually fits per fragment:** unchanged from the current `core/`
design's atom-based greedy packing (`ChunkEncoding.encode_atoms` yielding indivisible output
units — one raw byte for plain, one base64 group, one word for Markov text, one whole image for
image steganography), filled into each fragment up to its byte budget.
This already handles
disguise encodings whose expansion ratio isn't fixed 1:1, and needs no change here — just reused
per-fragment instead of per-chunk-within-a-hyperslice.

**Why the header has no full tag, and the two fields that get one anyway:** per constraint 4, the
medium already rules out accidental corruption, so most header fields don't need integrity
protection beyond what the downstream data AEAD already gives them for free — if `data_tag` is
tampered with by an active adversary, the final data-AEAD check fails closed on *that one message*,
the same failure shape as everything else in this design, and nothing about future messages is
affected (`data_nonce` isn't a field an attacker could tamper in the first place — it's derived
independently by both sides, not transmitted, above).
Two fields don't have that property, because
they feed key/framing state that outlives the current message:

- `N`: since continuation fragments carry no marker of their own, a tampered `N` that reads *too
  high* would cause the receiver to consume a peer's next, legitimate fragments as if they were
  continuation ciphertext of the current message.
- **Rotation material** (§6, present only when a rotation is due): tampering it makes the receiver
  derive the *wrong* next directional key.
Worse than `N`'s failure mode — the sender continues
  using the real (untampered) derived key for every subsequent message in that direction, so the
  receiver can never decrypt anything else on that direction again.
It isn't contained to one
  message, and unlike the §5 recovery path (which only triggers when a peer record is *missing*),
  nothing here notices or self-heals it, since the peer record still exists — it's just permanently
  wrong.

Both get covered by one short MAC rather than a full second AEAD tag:
`n_tag = truncated_BLAKE2b(subkey, data_nonce || N || rotation_material)[:4]` (rotation_material
being empty bytes on a fragment that doesn't carry any), where `subkey` is domain-separated from the
sender's current directional key via `crypto.py`'s existing `derive_key` helper.
Binding to
`data_nonce` (unique per message, already required for AEAD safety) stops replaying an old,
validly-tagged value onto a different message.
The receiver verifies `n_tag` immediately after
decrypting the header, *before* acting on either field — so tampering either one fails the current
message closed, with zero risk of misreading subsequent fragments or permanently desyncing the key
chain.

**Reassembly (receiver side):** reverse the disguise on the first fragment → derive `header_nonce`
from the current directional key and message counter, decrypt the header → verify `n_tag` → derive
`data_nonce` the same way → read exactly `N` more (disguise-reversed) fragments → concatenate with
the data ciphertext already in the first fragment → verify the real data AEAD tag over the whole
thing → done.

## 5. Identity, peer state, and handshake

### Peer record

Local storage, keyed by `peer_id`: the two current directional keys `key_min2max`/`key_max2min`
(§6), the long-lived per-chat `root_key` they're both rotated from, and each direction's own message
counter since its last rotation.
This record *is* the chat — its presence or absence is the only signal of whether a chat exists at all.
There is no
separate "chat" object with its own lifecycle; the handshake that creates this record and the act
of starting a chat are the same event.

### Key selection on receive

No explicit "message type" field is ever transmitted.
Which key successfully authenticates a
message *is* the type signal:

- **No peer record for this `peer_id`** → the only key that could apply is
  `bootstrap_key(peer_id, my_id) = derive_key(peer_id, my_id, "airwire-handshake-bootstrap", 32)` —
  a pure function of *both* the sender's and recipient's public IDs, computable unilaterally by
  anyone who knows both (which, per constraint 3, is everyone: addressing requires knowing a
  recipient's ID too).
Pair-specific rather than sender-only (a departure from the original
  `handshake.md` design, which kept it sender-only) — this is what makes the certificate's own
  transmitted nonce (below) safe in practice rather than just cosmetic: two different peers of the
  same sender no longer share a key at all, narrowing any nonce-adjacent concern to a single
  specific pair rather than a sender's entire contact list. Anything that authenticates under it is
  a certificate; success creates the peer record.
- **Peer record exists** → the current directional key for that sender (see §6 — each direction has
  its own key) is tried first. No grace window for a just-superseded key is needed: delivery is
  strictly ordered and lossless per peer (§2), so a stale-keyed message can never arrive after a
  rotation boundary.
If the current key doesn't authenticate, fall back to
  `bootstrap_key(peer_id, my_id)` too, rather than discarding the message — see "Recovery from
  one-sided session loss" below for why this fallback matters.

### Certificate exchange

Mechanics carried over from the current `docs/handshake.md`, riding the §4 envelope instead of a
bespoke message shape: each side generates a fresh, conversation-scoped ephemeral X25519 keypair and
sends `Certificate = {ephemeral_public_key, rotation_interval}` — encrypted and header-encrypted
under `bootstrap_key(own_id, recipient_id)`, disguised same as anything else. `sender_id` is
deliberately not a field: the receiver already has to know it before attempting decryption at all
(it's an input to `bootstrap_key` itself), and a successful AEAD tag already proves it was correct —
a redundant copy inside the plaintext would add no assurance.
Fixed 34-byte plaintext, no
length-prefix framing needed.
Unsigned (plain
TOFU, deliberately — see "Security properties" for what this does and doesn't provide).
Order-independent: both sides can send their own certificate without waiting for the other's, even
crossing in flight. `rotation_interval` (2 bytes) announces the message count *this sender's own*
outgoing directional key will rotate at (see §6) — implementation-configurable, default 256;
protected by the certificate's own full data-AEAD tag, so tampering it fails closed the same as
tampering anything else in the certificate.

**Certificate header nonce — necessarily different from data messages' counter-based one.** Even
with `bootstrap_key` made pair-specific (above), a persistent counter still can't safely drive its
header nonce: the one scenario where the *same* pair ever exchanges a second certificate is
recovery after a local-storage wipe, and a counter safe enough to never repeat there would have to
survive exactly the event it exists to recover *from* — a contradiction, not a hard-to-hit edge
case.
(The residual risk of *not* solving this — reusing a stream-cipher nonce only in that narrow,
same-pair-after-wipe case — was assessed and judged small in practice: `data_nonce` itself is now
derived from `header_nonce` (below), so it adds no independent entropy either way, and the remaining
fields — `data_length` and `N`, both effectively constant for a certificate — carry little
information regardless; the only field that would actually differ between two reused-nonce
certificates is `data_tag`, and an XOR of two AEAD tags doesn't yield anything practically
exploitable.
But "small, not proven zero" was judged not worth accepting for zero cost, so this
stays as designed below rather than switching to a counter.
) Certificates therefore use a **fresh
random 24-byte nonce, transmitted** — disguised and
prepended as its own chained unit ahead of the header, using the same consumed-bytes mechanism §4
already has for chaining header→data (here: nonce→header→data, one more link in the same chain).
`data_nonce` for a certificate then derives from that same transmitted nonce —
`derive_key(bootstrap_key, "data-nonce", header_nonce)` — rather than needing its own separate 24
random bytes: the receiver already has `header_nonce` in hand (it's the very first thing decoded)
before it ever needs `data_nonce`, so there's no circularity, and this saves the certificate another
24 bytes on top of dropping `sender_id`.
Being public once disguise is reversed (disguise was never secret), this transmitted nonce can't be
put to any *second* use that needs a secret ingredient — considered and rejected: replay-detection
(rejecting a repeated nonce) doesn't add real protection here, since an adversary capable of forging
a malicious certificate can just generate a fresh keypair and a fresh nonce rather than replaying an
old one, and `bootstrap_key` being derivable by anyone (this section) means nothing stops that
regardless.
This only applies to certificates; ordinary data messages keep the counter-based
derivation (§4), since they're part of an ongoing, continuously-tracked relationship where a
reliable counter genuinely exists.

From the shared ECDH secret, both sides derive: `root_key` (long-lived, never itself rotated) and
the two directional keys, labeled canonically by sorted ephemeral-pubkey order rather than "self"
vs. "peer" (so both sides agree on which is which regardless of who computed first) —
`key_min2max = derive_key(shared_secret, min(pubkeys), max(pubkeys), "min2max")` and
`key_max2min` symmetrically.
Each side only ever *writes* with its own outgoing key and *reads* with
the other's.
Sending data to a peer requires having already received *their* certificate (to have
derived any of this key material at all); sending your own certificate requires nothing from them.

### Disguise mode selection

Unchanged from the earlier decision: an application-policy concern, not a protocol one, including
for the certificate itself — the receiver's trial-decode already tries every registered encoding
regardless of what the sender's local policy picked, so certificates need no special-casing here.

### Recovery from one-sided session loss

Because storage is local-only and either side's state can vanish independently (cache clear,
reinstall, uninstall) with no way for the other side to find out, the `bootstrap_key` fallback above
doubles as an **automatic recovery path**.
If peer B still holds a record for A but A has genuinely
lost its own, A's next message to B is necessarily a fresh certificate (A has no directional key left
to encrypt anything else with) — it authenticates under `bootstrap_key(A, B)` once B's directional-key
attempts fail, and B completes a normal handshake in response: new ephemeral keypair, new ECDH, a
wholly new `root_key` and pair of directional keys replacing the old ones.
There is nothing to actually recover
from A's forgotten state — this establishes a new session automatically, without either user
manually re-adding the contact.

Two consequences accepted deliberately, not overlooked:

- **Directional gap.** This only self-heals once the forgetful side speaks first. If B (still
  remembering) sends an ordinary message before hearing anything from A, that one message fails to
  authenticate on A's end and is silently dropped — a bounded, self-healing loss (resolved the
  moment either side sends its next message), not a permanent break.
Fixing it would mean
  reintroducing per-message acknowledgement, which §2 already deliberately dropped in favor of
  trusting the medium's delivery guarantee.
- **Continuous MITM window.** `bootstrap_key(sender, recipient)` is derivable by anyone who knows
  both public IDs — still everyone, since addressing a message requires knowing the recipient's ID
  too, so pair-specific derivation narrows *nonce* concerns without adding authentication; this
  gap is already an accepted, first-contact-only weakness in the original design (no persistent identity
  exists yet to pin against).
Making it a standing fallback for every established chat, not just new
  ones, means an active adversary can forge a "peer has reset" certificate at *any point* during an
  ongoing chat and trick the other side into re-keying with the attacker instead.
Not a new class of
  weakness, but a wider window for the same one — accepted here for the same reason the original gap
  was: the real fix is a persistent signing identity, already flagged in `handshake.md` as a
  deliberately deferred future upgrade.
This finding just raises that upgrade's priority.

## 6. Key rotation

**Two independent directional keys instead of one shared session key** — `key_min2max` /
`key_max2min` (§5), both derived once from the handshake's ECDH secret via domain separation.
This
was chosen specifically to avoid a coordination race: if both sides independently rotated a single
shared key based on their own message counts, two thresholds crossed around the same time would
derive two different "next" keys from the same starting point and desync the chat.
Directional keys
sidestep this entirely — each side unilaterally owns rotation of the one key it alone writes with,
no coordination needed, no race possible.

- **`root_key`** — derived once from the ECDH secret alongside the directional keys, long-lived for
  the chat's whole life, never itself rotated or used for AEAD directly; only ever a KDF ingredient
  for deriving the next directional key in each chain.
- **Trigger** — `rotation_interval`, announced per-direction in the `Certificate` (§5), not a
  spec-wide constant.
Each side counts its own outgoing logical messages on its own directional key
  since that key's last rotation, via `message_counter` — the same counter §4's header nonce
  derivation (`derive_key(directional_key, "header-nonce", message_counter)`) already needs, not a
  second, separate one: it starts at 0 when the key is established (initial handshake or the most
  recent rotation), increments by 1 after every message sent on that key, and is what both
  mechanisms read.
Resetting it to 0 exactly when the key itself changes is what keeps the header
  nonce safe across rotations too — nonce uniqueness only ever needs to hold *within* one key's
  lifetime, and a fresh key starting its own count back at 0 doesn't collide with the previous key's
  history.
- **Mechanics, on the message where `message_counter + 1` reaches `rotation_interval`:** the sender
  generates 32 fresh cryptographically-secure random bytes (`material` — forward secrecy depends on
  this being real entropy, not just any 32 bytes) and derives
  `new_key = derive_key(root_key, current_key, material)`. **Only the data portion of this message
  switches to `new_key`** — the header (and its `n_tag`) still encrypts under the *current*
  (about-to-be-superseded) key and `message_counter` value, same as every other message on this
  key.
This isn't a stylistic choice: `material` itself travels inside the header, so the header
  cannot be the thing `new_key` is needed to read — that would be circular.
Concretely: header nonce
  and `n_tag` subkey both derive from `current_key`. `data_nonce` itself also derives from
  `current_key` and `message_counter`, exactly as on any other message — only the key the resulting
  `data_nonce` gets used *with*, for the actual AEAD operation, switches to `new_key` (no collision
  risk: `new_key`'s first-ever use pairs it with a `data_nonce` derived from a different key, and
  future messages on `new_key` derive their own `data_nonce` from `new_key` itself starting at
  counter 0 — BLAKE2b's collision resistance makes these two derivation paths landing on the same
  value negligible).
The
  receiver, tracking its own incoming-message count from that peer/direction, already knows — pure
  computation, no signal transmitted — that this incoming header will be 32 bytes longer than the
  base length; decrypts it with `current_key` exactly as usual, recovers `material` from the now-
  decrypted header, derives the identical `new_key`, uses *that* for the data portion, and only
  then resets its own `message_counter` for that direction to 0 alongside switching to `new_key` for
  all following messages.
- **Forward secrecy depends on erasure, not just derivation.** `key_i` must be actively deleted once
  `key_i+1` is derived — a hash-chain that keeps every past key around provides no forward secrecy
  at all, since anyone who later learns `root_key` (or breaks the original X25519 ECDH, see §9) could
  otherwise walk the whole chain forward from the first key.
This is an implementation requirement,
  not an implementation detail, and worth stating as such rather than leaving implicit.

## 7. Concurrency

- **Sending:** at most one logical message's fragments in flight to a given peer at a time (matches
  the medium's own one-outstanding-send-per-peer constraint, §3) — outgoing messages to the same
  peer queue FIFO.
Sends to *different* peers are fully independent, no shared queue between them.
- **Receiving:** each peer's reassembly state (its in-progress header/fragment buffer, if any) is
  independent of every other peer's — no cross-peer interference, consistent with §4's "no
  interleaving to worry about" already relying on this.
- **Send/receive concurrency:** unrestricted in both directions per §3.

## 8. Security properties summary

| Property | Provided? | Notes |
| --- | --- | --- |
| Data confidentiality | Yes | Directional keys (§6), XChaCha20-Poly1305 AEAD. |
| Data tamper-evidence | Yes | Full AEAD tag per logical message; corruption/tampering fails closed. |
| Header metadata confidentiality | Yes (new vs. the earlier `core/` design) | Header fields hidden by the §4 stream-cipher layer, not just disguised. |
| Header tamper-evidence | Partial, by design | `N` and rotation material are explicitly MAC'd together (§4) — the two fields whose tampering could otherwise outlive one message. `data_tag` fails closed indirectly, via the downstream data-AEAD check, rather than directly, but that's sufficient since its tampering is contained to one message (`data_nonce` isn't transmitted at all — derived independently by both sides, nothing for an attacker to tamper). |
| Disguise consistency | Yes | Cosmetic only; per-message choice is an app-policy concern, never reveals protocol state. |
| First-contact authentication | No | Plain TOFU, unsigned certificates — same accepted gap as the original `handshake.md`. |
| Post-loss recovery authentication | No | The §5 recovery path extends the same TOFU gap to be exploitable for a chat's entire life, not just its start — explicitly accepted in §5. |
| Forward secrecy | Yes, conditional | Depends on old directional keys being erased after each rotation (§6) — an implementation obligation, not automatic. |

## 9. Future direction: post-quantum migration (not implemented — reasoning only)

Carried forward from `docs/handshake.md`, re-examined under this design's key rotation.
X25519 is
the only asymmetric primitive anywhere in this protocol (the ECDH handshake, §5) — classical
elliptic-curve Diffie-Hellman, broken outright by a sufficiently large quantum computer running
Shor's algorithm.
XChaCha20-Poly1305 (§4, §6) is not considered quantum-vulnerable the same way —
Grover's algorithm only halves effective symmetric key strength, and a 256-bit key keeps a
comfortable ~128-bit margin against it.

**"Harvest now, decrypt later" is a present-tense threat, not a someday-concern:** an adversary who
records today's handshake and resulting ciphertext can, once a sufficiently powerful quantum
computer exists, retroactively break the recorded ECDH and decrypt everything derived from it.

**Important connection to §6, worth stating plainly:** key rotation does *not* protect against this.
Every directional key in both chains traces back to `root_key`, itself derived from the one X25519
ECDH secret established at handshake time.
An adversary who breaks that original ECDH recovers
`root_key` and, from it, every key in both chains — past and future — no matter how many rotations
have happened since.
Rotation's forward secrecy (§6) only protects against a *live* key or
`root_key` leaking through some other channel (e.g. device compromise); it provides no protection at
all against the original ECDH itself being broken.
Rotation is not a bigger security win against this
specific threat than it actually is.

**Standard mitigation, when this becomes a priority:** a hybrid key exchange — run a post-quantum
KEM (ML-KEM/Kyber, NIST-standardized) alongside X25519, deriving `root_key` from both secrets
combined, so breaking either primitive alone isn't enough.
Not pursued now: no PQ KEM primitive
exists in any codebase here yet, and this spec's job is proving the protocol's shape, not
selecting/vetting a specific PQ library.

## 10. Open questions and non-goals

- **`peer_id` spoofing** (e.g. SMS sender-number spoofing) is inherited entirely from the medium;
  nothing at this layer can address it, since the whole scheme is keyed on trusting `peer_id` at
  face value — same open item `handshake.md` already carried.
- **Reassembly-state crash recovery is unresolved.** If an app is killed mid-reassembly of a
  multi-fragment message, the medium has already delivered every fragment it received before the
  crash (per §2's reliability guarantee) — but the *application's* in-memory reassembly buffer is
  gone.
With no ack/retry layer (deliberately, §2), the sender has no way to know this happened, and
  the medium won't redeliver something it already handed off.
Whether/how to persist in-progress
  reassembly state is left to the implementation; this spec doesn't mandate a strategy.
- **Multi-device use is a non-goal here.** A user with the same `peer_id` reachable from two devices
  (e.g. a linked SMS inbox) isn't addressed — each device would independently run its own handshake
  and hold its own, unsynchronized peer records.
Out of scope for this spec; flagged so it isn't
  mistaken for an oversight.
- **Group/multi-party chats are explicitly out of scope** (constraint 8, §2) — this spec is 1:1 only,
  by deliberate design choice, not an unaddressed gap.
- **`rotation_interval` is a self-contained trust boundary.** Each side only ever controls the
  cadence of its own outgoing key (§6); an implementation choosing a very large or very small value
  affects only its own side's forward-secrecy granularity, never the other party's security.
- **Carrier-side history retention exposes disguise persistence, not confidentiality.** Some mediums
  (SMS is the motivating example) unreliably retain past messages outside any app's control.
This
  doesn't threaten confidentiality — forward secrecy (§6) already requires old directional keys to be
  erased once superseded, so retained raw ciphertext stays permanently undecryptable regardless of
  how long it persists — and unrelated plaintext mixed into the same history is already harmless,
  since the receiver's trial-decrypt (§5) simply fails closed on anything that isn't actually a
  protocol message.
What *is* exposed: the disguise (§4) was only ever designed to make one message
  look plausible in isolation, with no visibility into whatever else a medium stores for that thread
  — if a carrier's retained history sits a disguised message next to genuinely human-written text,
  the contrast could be noticeable to anyone reviewing that raw history, without breaking any crypto
  at all.
This is an inherent limitation of text/image steganography in general, not something
  introduced by or closeable within this protocol.
Recommended, though not mandatory (medium-
  dependent, and never a complete fix — carrier-network-level logs and backups stay outside any app's
  control regardless): where a medium exposes a way to delete a message after it's been processed,
  implementations **should** delete their own sent/received messages from the medium's own store to
  shrink this exposure window.
