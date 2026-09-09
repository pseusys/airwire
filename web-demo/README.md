# airwire obfuscation demo (Angular + TypeScript)

A small, standalone web page that showcases *only* the disguise mechanism behind airwire's text
steganography — message bytes in, plausible-looking sentences out, and back — with none of the
surrounding protocol. See [`core/README.md`](../core/README.md#how-the-steganography-works) for
the full explanation of the underlying trick (an arithmetic coder run backwards) and
[`memory/wire-protocol.md`](../memory/wire-protocol.md) for why the real protocol looks the way
it does.

## What this deliberately is not

This is **not** part of the airwire product's real "Web Mode" transport, and it doesn't touch any
of the actual protocol:

- **No encryption.** What you type is fed to the encoder exactly as typed — in the real protocol
  this input would already be AEAD ciphertext (see
  [`core/sources/crypto.py`](../core/sources/crypto.py)).
- **No chunking.** One message becomes one disguised blob, not a `pack_hyperchunk`-style header +
  sequenced wire chunks (see [`core/sources/chunking.py`](../core/sources/chunking.py)).
- **No handshake.** There's no session, no key exchange, no per-sender obfuscation-mode derivation
  (see [`memory/handshake.md`](../memory/handshake.md)).

Just the encode/decode mechanism, in isolation, so it's easy to see and experiment with.

## Why TypeScript, not the real Python code

This is a second, independent implementation of the same bit-exact arithmetic coder and Markov
walk as [`core/sources/arithmetic.py`](../core/sources/arithmetic.py) and
[`core/sources/markov.py`](../core/sources/markov.py) — chosen deliberately (over a thin frontend
calling a small Python backend) so this page is a fully static, standalone artifact with nothing
to run except a browser. The real, authoritative implementation is the Python one in `core/`; this
port exists to *demonstrate* the mechanism, not to replace or extend it. It was cross-validated
against the Python implementation before being wired into the UI — see `src/app/core/`:

- `arithmetic.ts` — line-for-line port of `arithmetic.py`, using `bigint` throughout (the same
  reason the Python original never uses a float: ranges routinely exceed what a 64-bit float or a
  JS `number` can represent exactly). One deliberate deviation: `ceilLog2Ratio` computes
  `ceil(log2(a/b))` via exact integer comparison rather than `Math.log2` on a float division, to
  avoid that function's only real correctness risk (a ratio landing extremely close to a power of
  two, where floating-point rounding could tip `ceil()` the wrong way) — see the file's docstring.
- `markov.ts` — port of `MarkovEncoding`'s walk, fetching the same frozen per-language model
  (`core/sources/data/markov_<language>.json`) the real Python encoder trains and uses. Candidate
  sorting order matters bit-for-bit here (see the comment at the sort call) — get it wrong and this
  would still round-trip *with itself*, just not match what the real protocol produces.
- `synthesis.ts` — port of the patch-based texture-synthesis encode/decode from `synthesis.py`
  (same `PatchLibrary`, same edge-cost weighting, same arithmetic-coder primitives from
  `arithmetic.ts`), operating on a small internal `Image` type (flat RGB `Uint8Array`).
- `textures.ts` — the four procedural texture generators, ported algorithm-for-algorithm from
  `textures.py`. **Not** seeded compatibly with the real Python generator, unlike the text-mode
  files above: `textures.py` uses NumPy's `default_rng` (PCG64) specifically so two independently
  built *protocol* clients regenerate an identical texture from the same seed, a real requirement
  there. This demo only needs *itself* to regenerate the same texture from the same seed, so
  `prng.ts` uses a much simpler generator instead (mulberry32) — same seed always gives the same
  texture within this page, but not the same texture a real client would produce. See `prng.ts`'s
  docstring; flagged there and here so it doesn't read as a stronger claim than it is.
- `png.ts` — converts between `Image` and real PNG files via `<canvas>`, for the download/upload
  flow described below. `colorSpaceConversion: 'none'` on decode is deliberate, not decoration —
  see the file's docstring for the corruption it's guarding against.

Validated by encoding/decoding identical payloads on both sides and diffing the output
word-for-word (not just checking that each side round-trips on its own) — confirmed byte-identical
for the same input, including hitting the frozen English model text produced by the real
`MarkovEncoding.encode_atoms`. The image path was validated end to end in a real browser
(obfuscate → click Download → upload that exact downloaded file in a *fresh* page → reveal),
across all four texture flavors, not just checked in the abstract.

## Setup

Requires the frozen per-language models to already exist in `core/` — if
`core/sources/data/markov_eng.json` doesn't exist yet, run `poetry poe train-stego-model` from
`core/` first (see [`core/README.md`](../core/README.md)).

```bash
npm install
npm start   # copies the frozen models into public/models/, then ng serve
```

`npm run build` does the same model sync before building. The models aren't committed to this
repo (same reasoning as `core/sources/data/*.json` — generated, not source) — `public/models/` is
gitignored.

## Scope

Both disguise mechanisms work: text (Markov chain, English/Russian) and image (texture synthesis,
all four flavors) — obfuscate a message, then reveal it back. The image mode's output is a real
PNG, downloadable, and the reveal side accepts an uploaded PNG in place of the one just generated
(you'll need to supply the flavor, seed, and original byte length it was made with — there's no
header to carry that here, deliberately, see the scope note at the top of the page).
