# Handshake — establishing a session before any data transfer

> **Status:** design finalized, implementation in progress.
> **Scope:** the [airwire](../README.md) product track, same boundary as
> [design-decisions.md](./design-decisions.md) and [roadmap.md](./roadmap.md). Split into its own
> document rather than a `design-decisions.md` entry because it's a bigger, single coherent
> protocol rather than one trade-off among many — see that document for everything else.

## Why this exists

Every other document in this repo assumes a session symmetric key already exists.
[`sources/chunking.py`](../core/sources/chunking.py) takes a `Symmetric` and gets to work; nothing
in Phase 0 so far has addressed how the two ends of a conversation get that key, or each other's
identity, in the first place. This document is that missing piece: what happens before the first
byte of real data moves.

## Starting assumptions

- Neither party knows anything about the other going in — no pre-shared long-term key, no prior
  contact required. This is a **plain TOFU (Trust On First Use)** design: whatever's presented at
  first contact is accepted, the same baseline model SSH and Signal both start from.
- Each side does already know one thing about the other, unavoidably: the recipient's
  platform-specific transport address (a phone number in SMS mode, whatever the equivalent
  platform user ID is in web mode) — you cannot route a message to someone without addressing it,
  so this is inherent to the transport, not a design choice.
- **Critical constraint, driving most of what follows:** from an outside observer's point of view,
  nothing about a conversation's *appearance* should change from the first handshake message to
  the last data acknowledgement. Encryption keys are expected to change over a session's lifetime
  (that's the whole point of an ephemeral handshake); which disguise (Markov language / texture
  flavor) a party's messages are wrapped in must not.

## The core problem this design solves

Disguising a message means running its ciphertext through an arithmetic-coder-based encoding
(`sources/markov.py` or `sources/synthesis.py`) — but ciphertext requires a key, and at the start
of a handshake, no session key exists yet. So: what encrypts (and picks a disguise for) the very
first message, before anything has been exchanged?

The answer: derive both from something that requires **no exchange at all**, because it's already
public. Each sender already has a stable, transport-visible identifier — that's `sender_id` in
what follows.

## Design

### Phase 0 — Per-sender constants, no messages sent yet

Both of these are pure functions of `sender_id` alone, computable unilaterally by *anyone* who
knows who's sending (which, per the assumptions above, is everyone — the transport exposes it):

```
obf_mode(sender_id)     = disguise_pool[ int(BLAKE2b(sender_id, "airwire-obfuscation-mode")) % len(disguise_pool) ]
bootstrap_key(sender_id) = Symmetric(BLAKE2b(sender_id, "airwire-handshake-bootstrap"))
```

- `disguise_pool` is a fixed, ordered list of the "real" disguise encodings — the two Markov
  languages and the four texture flavors (not `PLAIN`/`BASE64`, which aren't disguises).
  **The order is part of the wire-compatible protocol**: new entries must be appended, never
  inserted or reordered, or every existing sender's derived choice silently changes.
- `obf_mode(sender_id)` is what that sender's outgoing messages are disguised as, for the *entire*
  conversation — handshake certificate included. It's picked **per sender**, not per conversation:
  Alice's and Bob's outgoing streams can end up with different disguises, and that's fine — two
  real people plausibly have different "voices." What matters is that *each* sender's own stream
  never changes mid-flight, which this guarantees by construction (it's a pure function of an
  identity that doesn't change during a session).
- `bootstrap_key(sender_id)` exists for one reason only: to give the certificate message
  AEAD-shaped bytes for the disguise coder to run on. **It provides no confidentiality** — anyone
  who can see who the sender is (which is everyone, by assumption above) can derive the identical
  key. See "Security properties" below for what this step does and doesn't buy.
- **Manual override:** a deployment or user can pre-configure an explicit `obf_mode` instead of
  deriving it (this is the "given in advance" option) — the derivation above is just the default
  when nothing's been configured. Both paths produce an ordinary `ChunkEncoding` instance; nothing
  downstream needs to know which path it came from.

### Phase 1 — Certificate exchange

Each side generates a fresh, **conversation-scoped ephemeral X25519 keypair** — not a long-term
identity key, regenerated for every new session, so a future key compromise can't retroactively
expose other conversations.

```
Certificate = { sender: sender_id, ephemeral_public_key: eph_pub }
```

No signature — this is the "plain TOFU" choice. To send it: encrypt
`Certificate.SerializeToString()` with `bootstrap_key(own sender_id)`, then disguise the ciphertext
with `obf_mode(own sender_id)`, then send. The receiving side already knows who the message is
from (transport-level, before decrypting anything), so it independently derives the same
`obf_mode`/`bootstrap_key`, undoes the disguise, decrypts, and recovers the peer's `eph_pub`.

Both sides do this — order doesn't matter, they can even cross in flight.

### Phase 2 — Session key derivation

Standard ECDH, both sides land on the same value:

```
shared_secret = X25519(own eph_priv, peer's eph_pub)
session_key   = BLAKE2b(shared_secret, min(eph_pub_A, eph_pub_B), max(eph_pub_A, eph_pub_B))
```

The `min`/`max` byte-ordering is required, not cosmetic: without a canonical order, Alice (using
`self=A, peer=B`) and Bob (using `self=B, peer=A`) would hash the two public keys in opposite
order and derive *different* keys. Sorting the raw bytes first is the simplest fix that doesn't
need either side to know who's "first."

`session_key` is what `chunking.py` uses from here on for the data phase. It is a different value
from either side's `bootstrap_key` — the encryption key has changed, which is expected; the
disguise (`obf_mode`, still keyed only by `sender_id`) has not.

### Phase 3 — Data transfer

Proceeds exactly as `sources/chunking.py` already implements: `pack_hyperchunk`/`send_hyperchunk`
etc., using `session_key` for real AEAD confidentiality, and `obf_mode(own sender_id)` for both
payload and (optional) header disguise — unchanged from Phase 1, for every message either side
sends until the conversation ends.

## Security properties (what this does and doesn't provide)

| Property | Provided? | Notes |
|---|---|---|
| Data-phase confidentiality | Yes | `session_key` is secret by construction (ECDH of two freshly-generated, never-transmitted-in-the-clear private keys). |
| Handshake-message confidentiality | **No** | `bootstrap_key` is derivable by anyone who knows the sender's public transport ID — i.e. everyone. Its disguise step is cosmetic (uniform wire shape), not secrecy. |
| Tamper-evidence | Yes, against accidental/unsophisticated tampering | Every message is AEAD-tagged; corruption fails decryption cleanly. |
| Authentication / active-MITM resistance at first contact | **No** | This is bare unauthenticated ephemeral Diffie-Hellman for the session key — no persistent identity exists to pin across sessions (the ephemeral key legitimately changes *every* session, so there's nothing to compare a new one against). A capable adversary who actively intercepts the handshake (not just passively observes it) can substitute their own ephemeral keys on both sides, undetected, and this design has no way to catch that. This is the well-known, standard limitation of anonymous/unauthenticated DH — the same trade-off SSH and Signal both accept on literal first contact, before any key pinning has happened. |
| Disguise consistency (no visible transition) | Yes | `obf_mode` is a pure function of `sender_id`, computed identically and independently by both parties, never transmitted, constant for the life of a sender's stream. |

The MITM gap is a deliberate, accepted trade-off for this design's "plain TOFU" scope, not an
oversight — closing it needs a *persistent* identity to pin (e.g. a long-term signing key per
user, added to the certificate as a signature over `sender_id || ephemeral_public_key`, verified
against whatever key was seen for that `sender_id` last time). That's a real, buildable upgrade
path, deliberately not taken now because it wasn't asked for and adds a new signing primitive this
codebase doesn't have yet ([crypto.py](../core/sources/crypto.py) only has X25519 today). Noted
here so it isn't rediscovered as a surprise later.

## Open questions, deliberately not resolved here

- **`sender_id` spoofing** (e.g. SMS sender-number spoofing) is a real-world issue inherited
  entirely from the transport; nothing in this design can address it, since the whole scheme is
  keyed on trusting `sender_id` at face value.
- **Session scoping** — what actually triggers a new handshake (per app launch? per conversation
  thread? a time-based re-key?) isn't decided here; this document only covers what happens once a
  handshake is triggered.
- **Cross-session identity pinning**, if first-contact MITM resistance becomes a requirement — see
  the signed-certificate upgrade path above.

## Future direction: post-quantum migration (not implemented — reasoning only)

Every asymmetric operation in this design (and the only one anywhere in the protocol) is X25519 —
classical elliptic-curve Diffie-Hellman, broken outright by a sufficiently large quantum computer
running Shor's algorithm. `Symmetric`'s XChaCha20-Poly1305 (the data phase, and the disguise
coder's AEAD-shaped-bytes trick) is *not* considered quantum-vulnerable in the same way — Grover's
algorithm only halves effective symmetric key strength, and a 256-bit key keeps a comfortable
~128-bit margin against it, which is why current guidance doesn't call for migrating symmetric
primitives at all. X25519 is the one piece that matters here.

This isn't an abstract someday-concern: **"harvest now, decrypt later"** is a real, present-tense
threat model for anything worth protecting for years — an adversary who *records* today's
handshake and resulting ciphertext can, once a sufficiently powerful quantum computer exists,
retroactively break the recorded ECDH and decrypt everything derived from it. Recording is cheap
and can happen today regardless of when the computer arrives.

The standard mitigation, when this becomes a priority, is a **hybrid key exchange**: run a
post-quantum KEM (ML-KEM/Kyber, now NIST-standardized) alongside the existing X25519 exchange, and
derive `session_key` from *both* shared secrets combined
(`BLAKE2b(x25519_secret, mlkem_secret, ...)`), so breaking either primitive alone isn't enough —
both have to fall. This is the same path TLS 1.3 and Signal are both migrating to; it augments
X25519 rather than replacing it, which matters since ML-KEM is comparatively new and less
battle-tested. Not pursued now: no PQ KEM primitive exists in this codebase yet (PyNaCl doesn't
bundle ML-KEM), and Phase 0's job is proving the protocol's shape, not selecting and vetting a
specific PQ library. Flagged here deliberately, as a known next step, rather than left to be
rediscovered.
