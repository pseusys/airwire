# airwire

A messaging application that encrypts and disguises messages before sending them over whatever
medium the conversation actually uses.
All messages are stored locally on the user's device — the server acts only as a relay, never persisting message content.

## Project Scope — Two Tracks

This repository hosts two related but separately-paced efforts:

1. **airwire (product track) — this document.** The immediate, buildable goal: encrypt and
   decrypt **text and images** under a pre-shared key and move them over a real transport medium.
Each payload is
   sent either as a *raw* encrypted-and-encoded blob, or *steganographically* disguised as benign
   content — human-like text via Markov chains, or an information-bearing image.
Right now that means testing against a real messenger-backed medium (Odnoklassniki, via OAuth —
   see [`memory/medium.md`](memory/medium.md)); SMS/MMS was the original transport concept this
   product was scoped around, and remains one, but nothing SMS-specific is built or tested yet —
   see [`memory/medium.md`](memory/medium.md)'s "Future medium idea" section for that reasoning,
   kept separate from what's actually running today.
Everything below
   specifies this track.

2. **airwave (research track) — see [`docs/research-proposal.md`](docs/research-proposal.md).**
   An exploratory research proposal for an adaptive, channel-agnostic protocol that establishes
   **audio** communication over an *unknown* channel (VoIP, a lossy voice codec, or an open-air
   speaker+microphone link) — discovering the channel's transmittable features at runtime and
   adapting its encoding to them.
Framing and bibliography only at this stage; no implementation.

See [`TODO.md`](TODO.md) for the phased implementation plan for this track, starting with a
platform-independent Python proof of concept of the crypto/framing/obfuscation core before any
mobile app work began, and [`memory/wire-protocol.md`](memory/wire-protocol.md) for how that core
actually works, with the reasoning behind the non-obvious choices.

> **Note:** [`web-demo/README.md`](web-demo/README.md) documents a small standalone Angular page
> that showcases both disguise mechanisms (text and image) in a browser. It is not part of the
> product itself — see that file for its deliberately narrow scope.

## Setup

Three independent sub-projects, no shared build step — see [`core/README.md`](core/README.md) and
[`web-demo/README.md`](web-demo/README.md) for their own quickstarts.

```bash
# core/ -- the real protocol implementation (Python 3.11+/3.12, Poetry)
cd core && poetry install --all-extras && poetry poe generate && poetry poe train-stego-model

# client/ -- Flutter Web app + Medium wrapper (Dart pub workspace)
cd client/app && flutter pub get      # or: cd client/medium && dart pub get

# web-demo/ -- standalone Angular disguise demo (Node 22, npm)
cd web-demo && npm install
```

## Useful Commands

```bash
cd core && poetry poe test                            # pytest
cd core && poetry poe lint                             # flake8 + black + mypy --strict
cd client/app && flutter test                          # not run in CI yet
cd client/medium && dart test                          # not run in CI yet
cd web-demo && npx ng test --watch=false --browsers=ChromeHeadless
```

Full reference, with every flag actually used: [`memory/commands.md`](memory/commands.md).

## Core Concepts

### Local-Only Storage

Messages are never stored on the server.
The server receives, relays, and discards.
All message history lives exclusively on the user's device.

### Delivery Statuses

Every message carries a delivery status:

| Status | Meaning |
| --- | --- |
| **Pending** | Message is still being transmitted to the server |
| **Sent** | Server has received the message |
| **Delivered** | Message was delivered to the recipient's device |

### Timeouts and Retries

The server enforces timeouts with retries on every message:

- If a message is not fully **received** from the sender within the timeout, it becomes **unsent** and the sender is notified.
- If a message is not fully **delivered** to the recipient within the timeout, it becomes **undelivered** and the sender is notified.
- In both cases the message is discarded from the server.

**Exception:** notification messages (e.g. presence updates) are fire-and-forget — no retransmission, no timeout.

## Message Format

Every message is a Protobuf structure containing:

| Field | Required | Description |
| --- | --- | --- |
| `id` | Yes | Rolling 4-byte message ID |
| `sender` | Yes | Sender identifier (medium-specific — e.g. an OAuth-derived user ID) |
| `recipient` | Yes | 16-byte receiver ID |
| `type` | Yes | Message type |
| `payload` | No | Optional message body |

## Encryption

Fully asynchronous encryption using **X25519** key exchange and **XChaCha20-Poly1305** for symmetric encryption.

- **Service messages** (e.g. the initial handshake — see [`memory/handshake.md`](memory/handshake.md)
  for the full session-establishment design) carry the full asymmetric overhead.
- **Data message bodies** are encrypted symmetrically only, to save space.

A data message body is cut into large **hyperslices** (configurable, ~1KB by default), and each
hyperslice is encrypted as a single AEAD operation — one nonce and tag cover the whole hyperslice,
not each individual outgoing message.
That's what keeps the per-message overhead low; see
[`memory/wire-protocol.md`](memory/wire-protocol.md) for the
reasoning and the numbers behind it.
The resulting ciphertext is split into small, message-sized
**chunks**, each carrying only a cheap sequence number, preceded by one small header message
(itself encrypted) describing how to reassemble and verify the chunks that follow.
The receiver
acknowledges each hyperslice as a whole (also encrypted); on any failure, the whole hyperslice is
retried.

### Chunk Size Budget

The wire chunk budget is configurable per medium — see [`core/sources/chunking.py`](core/sources/chunking.py)
for the mechanics, and [`memory/wire-protocol.md`](memory/wire-protocol.md) for the current
numbers with the shipped defaults: roughly 91% of raw bytes sent are message content rather than
overhead, versus roughly 68% under an earlier, naive per-message encryption scheme.
The original defaults were sized around SMS's 160-byte budget and an MMS-scale attachment budget —
see [`memory/medium.md`](memory/medium.md)'s "Future medium idea" section for that reasoning,
kept separate from what's actually tested today.

## Documentation

- [`AGENTS.md`](AGENTS.md) — orientation, repo layout, and the working rules
- [`memory/`](memory/README.md) — the knowledge base: how things work now, the house rules, and what was tried and rejected
- [`CHANGELOG.md`](CHANGELOG.md) — what changed, when, and the evidence
- [`TODO.md`](TODO.md) — what's open

## License

Proprietary.
All rights reserved — no license is granted to use, copy, modify, or distribute this
code.
