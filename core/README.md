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
  `sources/chunking.py` below, plus the `ChunkEncoding` enum described next; header and ack are
  both encrypted as a whole before going on the wire.
- `sources/encodings.py` — pluggable strategies (`ChunkEncoding`) for turning hyperchunk ciphertext
  bytes into the bytes that actually travel in wire chunks: `PlainEncoding` (raw bytes),
  `Base64Encoding` (visible ASCII, a middle ground between raw binary and a fully disguised
  encoding), and (registered by `sources/chunking.py` from `sources/markov.py`, to keep this
  module free of any one encoding's own dependencies) the Markov-chain text disguise below.
- `sources/chunking.py` — cuts a message into large "hyperslices", encrypts each one as a single
  AEAD operation, and splits the result into configurably-sized wire chunks (a plain, variable-
  width sequence number per chunk, followed by a `ChunkEncoding`-transformed payload) with a
  stop-and-wait acknowledgement/retry layer on top. The header and the ack are themselves
  encrypted, and each hyperchunk carries a session-scoped ID so an ack can be tied back to the
  transfer it belongs to. See the module's docstring for the full design and its open questions.
- `sources/corpus.py` — downloads and locally caches the plain-text sentence corpora (English and
  Russian, from [Tatoeba](https://tatoeba.org/en/downloads)) used to train the Markov-chain text
  disguise model. Downloads once per language, on first use; later calls reuse the cached file.
- `sources/data/*.json` — frozen, pre-trained Markov chains (one per language), built from the
  corpora above via `poetry poe train-stego-model` (`scripts/model.py`). Generated, not committed
  — see that file's docstring for why the corpus is capped in size, and regenerate with
  `poetry poe train-stego-model` if it's missing.
- `sources/markov.py` — `MarkovEncoding`, the `ChunkEncoding.MARKOV` implementation: disguises
  ciphertext as plausible sentences by walking the frozen chain above, using a from-scratch,
  pure-integer arithmetic coder (not a general-purpose entropy-coding library -- see the module's
  docstring for why `constriction` was tried and rejected, and
  [design decision #2](../docs/design-decisions.md) for the full story) so encode/decode agree
  byte-for-byte on any device, with no floating point or ML inference anywhere in that path. Two
  language instances exist (`MARKOV_ENG`, `MARKOV_RUS`), but only `MARKOV_ENG` is registered for
  the header-driven auto-detection `unpack_hyperchunk` relies on -- see the module's docstring for
  why, and what a real fix would need.

Image steganography is not started yet — see the roadmap.

## Setup

```bash
poetry install --all-extras
```

## Commands

```bash
poetry poe generate           # regenerate sources/proto/*_pb2.py from the .proto schema
poetry poe train-stego-model  # download/cache corpora, (re)train sources/data/markov_*.json
poetry poe demo                 # encrypt + wire-encode a demo message end-to-end, print each step
poetry poe test                 # run the unit test suite
poetry poe lint                 # flake8 + black --check + mypy
poetry poe format               # black (modifies files)
```

`demo` takes options: `poetry poe demo --mode markov --text "some message" --chunk-size 120`
(`--mode` is `plain`, `base64`, or `markov`; the latter needs `sources/data/markov_eng.json` to
exist first -- run `poetry poe train-stego-model` if it doesn't).
