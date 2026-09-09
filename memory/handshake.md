# Handshake and session crypto — current implementation vs. target spec

*keywords:* handshake, TOFU, X25519, obf_mode, bootstrap_key, session key, rotation, directional key, MITM

**This file documents two different things side by side, and does not let them blur together:**
what `core/sources/handshake.py` and `crypto.py` actually implement today, and what
`docs/superpowers/specs/2026-08-27-messaging-protocol-design.md` specifies as the target design for
the eventual real protocol.
The spec explicitly says `core/` "is not this protocol and will not necessarily match it
field-for-field" — treat the "Currently implemented" section as reality and the "Target spec"
section as *not yet built*, no matter how precisely either one is written up.

## Why a handshake exists at all

`core/sources/chunking.py` assumes a session symmetric key already exists — nothing before the
handshake addresses how the two ends of a conversation get that key, or each other's identity, in
the first place.
The harder problem it also solves: the *disguise* a sender's messages are wrapped in (Markov
language / texture flavor) must never visibly change across a session, even though the encryption
key underneath legitimately does.

## Currently implemented (`core/sources/handshake.py`, `crypto.py`)

**Starting assumptions:** plain TOFU (Trust On First Use) — no pre-shared key, no persistent signing
identity, whatever's presented at first contact is accepted, the same baseline SSH and Signal both
start from. Each side already knows the other's transport-visible identifier (`sender_id`) —
inherent to routing a message at all, not a design choice.

**Phase 0 — per-sender constants, no messages sent yet.** Both are pure functions of `sender_id`
alone, computable unilaterally by anyone who knows who's sending:

```text
obf_mode(sender_id)      = disguise_pool[ int(BLAKE2b(sender_id, "airwire-obfuscation-mode")) % len(disguise_pool) ]
bootstrap_key(sender_id) = Symmetric(BLAKE2b(sender_id, "airwire-handshake-bootstrap"))
```

`disguise_pool` is a fixed, ordered list of the real disguise encodings (the two Markov languages,
the four texture flavors — not `PLAIN`/`BASE64`). The order is part of the wire-compatible protocol:
new entries append, never insert or reorder, or every existing sender's derived choice silently
changes. `obf_mode` is picked per sender (not per conversation), so it never changes mid-session by
construction — it's a pure function of an identity that doesn't change during a session. A manual
override lets a deployment pre-configure an explicit `obf_mode` instead of deriving it.
`bootstrap_key` provides **no confidentiality** — anyone who knows the sender's identifier can
derive it; it exists only to give the certificate message AEAD-shaped bytes for the disguise coder
to run on.

**Phase 1 — certificate exchange.** Each side generates a fresh, conversation-scoped ephemeral
X25519 keypair (never a long-term identity key). `Certificate = { sender: sender_id,
ephemeral_public_key: eph_pub }`, unsigned, encrypted under `bootstrap_key(own sender_id)`, disguised
with `obf_mode(own sender_id)`. The receiver already knows who it's from (transport-level, before
decrypting anything), so it derives the same `obf_mode`/`bootstrap_key` independently. Order between
the two sides' certificates doesn't matter; they can cross in flight.

**Phase 2 — session key.** Standard ECDH: `shared_secret = X25519(own eph_priv, peer's eph_pub)`,
then `session_key = BLAKE2b(shared_secret, min(eph_pub_A, eph_pub_B), max(eph_pub_A, eph_pub_B))`.
The `min`/`max` byte-ordering is required, not cosmetic — without a canonical order, the two sides
would hash the public keys in opposite order and derive different keys.

**Phase 3 — data transfer.** Proceeds exactly as `chunking.py` already implements
(`pack_hyperchunk`/`send_hyperchunk`), using `session_key` for AEAD confidentiality and
`obf_mode(own sender_id)` for disguise, unchanged for the life of the session.
**No key rotation, no per-direction keys, no message counter** — one `session_key`, used until the
session ends.

**Security properties (as implemented):**

| Property | Provided? | Notes |
| --- | --- | --- |
| Data-phase confidentiality | Yes | `session_key` is secret by construction (ECDH of freshly-generated, never-transmitted-in-the-clear private keys). |
| Handshake-message confidentiality | **No** | `bootstrap_key` is derivable by anyone who knows the sender's public transport ID. Its disguise is cosmetic (uniform wire shape), not secrecy. |
| Tamper-evidence | Yes, against accidental/unsophisticated tampering | Every message is AEAD-tagged; corruption fails decryption cleanly. |
| Authentication / active-MITM resistance at first contact | **No** | Bare unauthenticated ephemeral DH — no persistent identity to pin. An active (not just passive) adversary at first contact can substitute their own ephemeral keys on both sides, undetected. Accepted, deliberate trade-off of "plain TOFU" scope, the same one SSH and Signal both accept on literal first contact. |
| Disguise consistency (no visible transition) | Yes | `obf_mode` is a pure function of `sender_id`, computed identically and independently by both parties, never transmitted, constant for the life of a sender's stream. |

Closing the MITM gap needs a persistent identity to pin (a long-term signing key per user, added to
the certificate as a signature, verified against whatever key was seen last time) — a real, buildable
upgrade path, not taken because `crypto.py` has no signing primitive yet and it wasn't asked for.

**Post-quantum migration** is reasoned about but not implemented: X25519 is the one asymmetric
operation in the whole protocol, and is the piece vulnerable to a sufficiently large quantum
computer (Grover's algorithm only halves symmetric key strength, so XChaCha20-Poly1305 is not
considered urgent to migrate). "Harvest now, decrypt later" is the actual present-tense threat this
matters for. The standard mitigation, when prioritized, is a hybrid exchange — run ML-KEM alongside
X25519 and derive `session_key` from both shared secrets, so breaking either alone isn't enough.
Not pursued: no PQ KEM primitive exists in this codebase yet (PyNaCl doesn't bundle ML-KEM).

## Target spec (`docs/superpowers/specs/2026-08-27-messaging-protocol-design.md` §4–§6) — not yet implemented

A materially different, more advanced crypto scheme for the eventual real protocol:

- **Directional keys with rotation**, not one static `session_key`. From the ECDH shared secret:
  `root_key`, `key_min2max`, `key_max2min` (each `derive_key(shared_secret, min_pub, max_pub, label,
  32)`) — whichever matches your own sorted pubkey position is your outgoing key, the other is
  incoming.
- **A per-direction `message_counter`**, incrementing per message, reset to 0 on rotation.
- **Nonces derived from `(key, message_counter)`, not transmitted at all** for ordinary data
  messages: `header_nonce = derive_key(directional_key, "airwire-header-nonce", counter, 24)`,
  `data_nonce` the same shape with a different label. The certificate (handshake bootstrap) message
  is the one exception — its `header_nonce` is transmitted, because `bootstrap_key` can legitimately
  be reused across a wipe-and-recover scenario where a counter can't be trusted to have survived.
- **Key rotation mid-session**: when `message_counter + 1 == rotation_interval` (a value each side
  announces for its own outgoing key), a message carries 32 fresh random bytes (`material`) in its
  header, and both sides derive `new_key = derive_key(root_key, current_directional_key, material,
  32)`. The rotated message's header is still encrypted with the *old* key (material lives inside
  the header, so the header can't be encrypted with the key it's used to derive); the data is
  encrypted with `new_key`. After sending, the counter resets to 0 and **the old key must be
  erased** — forward secrecy depends on the erasure, not just on `new_key`'s derivation.
- **Header encryption is a stream cipher (XChaCha20, no Poly1305)**, not full AEAD — only the data
  portion gets a Poly1305 tag; the header's own tag lives inside its (stream-encrypted) plaintext,
  covering the header fields via a separate `n_tag` derivation.

None of this — directional keys, rotation, counter-derived nonces, stream-cipher headers — exists in
`core/sources/crypto.py`/`chunking.py` today. If a future Dart or Python change starts implementing
rotation, it belongs here as a status update, not as a silent assumption that it already matches this
section.
