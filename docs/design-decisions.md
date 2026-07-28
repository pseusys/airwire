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

- [ ] **Derive the header/ack nonce instead of transmitting it**, the same trick iteration 1 used
      for chunk nonces — now that every header and ack carries a stable `hyperchunk_id`, its
      encryption nonce could be derived from `(hyperchunk_id, "header"|"ack")` via BLAKE2b instead
      of a fresh random 24 bytes embedded in the output. That's 24 bytes off a 93-byte header
      (~26% smaller) and a much larger fraction off the 44-byte ack. Directly in the spirit of
      this decision, and small to build.
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
