# airwire core (Phase 0 proof of concept)

Platform-independent Python implementation of airwire's crypto, message framing, and SMS
chunking, per the [product README](../README.md) and [roadmap](../docs/roadmap.md#phase-0--core-engine-poc-python-no-app).

No mobile code lives here. The point of this package is to prove the protocol design — and, once
it's frozen, to serve as the source of test vectors the future Android/iOS clients get checked
against — before any platform-specific work starts.

## Contents

- `sources/crypto.py` — X25519 key exchange + XChaCha20-Poly1305 AEAD, via
  [PyNaCl](https://pynacl.readthedocs.io/) (libsodium bindings).
- `sources/proto/envelope.proto` — the message format from the [README's table](../README.md#message-format):
  `id`, `sender`, `recipient`, `type`, `payload`.
- `sources/proto/hyperchunk.proto` — the `HyperchunkHeader` and `HyperchunkAck` messages used by
  `sources/chunking.py` below; both are encrypted as a whole before going on the wire.
- `sources/chunking.py` — cuts a message into large "hyperslices", encrypts each one as a single
  AEAD operation, and splits the result into configurably-sized wire chunks (a plain, variable-
  width sequence number per chunk) with a stop-and-wait acknowledgement/retry layer on top. The
  header and the ack are themselves encrypted, and each hyperchunk carries a session-scoped ID so
  an ack can be tied back to the transfer it belongs to. See the module's docstring for the full
  design and its open questions.

Steganographic obfuscation (Markov-chain text, image stego) is deliberately not included yet —
see the roadmap for why.

## Setup

```bash
poetry install --all-extras
```

## Commands

```bash
poetry poe generate  # regenerate sources/proto/*_pb2.py from the .proto schema
poetry poe test      # run the unit test suite
poetry poe lint       # flake8 + black --check + mypy
poetry poe format     # black (modifies files)
```
