# Markov Seed-Gating Broadening — Design

**Date:** 2026-09-08
**Status:** Approved, pending implementation plan.

## Background

The Markov-chain text disguise (`core/sources/markov.py`, ported to
`web-demo/src/app/core/markov.ts`) currently ignores its `nonce`/`seed`
parameter for everything except the cosmetic filler tail added by the
newline+filler feature (`docs/superpowers/specs/2026-09-08-markov-boundary-and-filler-design.md`).
Every state's candidate list is loaded once from the frozen model file in a
fixed alphabetical order (`sorted(candidates.items())` in Python,
equivalent `.sort()` in TypeScript), and that fixed order is what
`candidate_ranges`/`candidateRanges` uses to assign bit-range boundaries to
each word during the arithmetic-coding walk. Anyone with the shipped model
file — which is everyone who has the airwire codebase — can therefore
invert *any* Markov-disguised text back to its underlying ciphertext bytes
without knowing anything about the session: no nonce, no key, nothing.

This does not match the image disguise (`core/sources/synthesis.py`,
`core/sources/textures.py`): there, `seed = int.from_bytes(nonce[:4], "big")`
genuinely gates decoding — a decoder must regenerate the identical source
texture/patch library to recover the embedded bytes, which requires the
correct seed. Without it, decoding fails outright, the same way a wrong key
fails AEAD decryption. The user flagged this asymmetry after the
newline+filler feature shipped and asked for the two disguises' seed
treatment to match; that request was deliberately deferred until now (see
that feature's design doc) so the newline+filler work could ship first.

**Is this asymmetry real in the actual protocol, or only in the
standalone web-demo?** Traced through `core/sources/chunking.py`: the
hyperslice `nonce` (`token_bytes(Symmetric.nonce_size)`,
`chunking.py:214`) is used both to AEAD-encrypt the hyperslice itself
*and* passed to `ChunkEncoding.encode_atoms`/`decode` — the same value.
It is then stored in the `HyperchunkHeader` protobuf, and that header is
always AEAD-encrypted before transmission (`chunking.py:240-244`),
independent of whether `header_encoding` disguises it further. A passive
wire eavesdropper without the session key cannot observe this nonce. So
this is a real gap in the actual protocol, not just a web-demo cosmetic
concern — closing it gives Markov text the same genuine (informal,
brute-force-cost-raising, not cryptographically proven) protection image
already has. Confirmed with the user; this change applies to both
`core/` (Python) and `web-demo/` (TypeScript).

**Caveat, restated from the filler-completion design and equally true
here:** this does not make the scheme cryptographically secure. It is a
deterministic, unauthenticated, unproven construction. It raises the cost
of extracting/detecting a disguised payload from "trivial, zero
knowledge required" to "brute-force the seed space" — the same informal
protection level image's seed already provides, no more.

## Approaches Considered

**A. Seed-derived per-state candidate permutation (chosen).** Derive a
permutation seed from the nonce, and use it to shuffle each state's
candidate list before it's handed to `candidate_ranges`. Both encode and
decode must agree on the permutation to agree on which word owns which
bit-range; a wrong seed still recognizes words as valid (same word set,
membership is order-independent) but recovers the wrong bits, corrupting
output the same way a wrong image seed produces the wrong texture and
garbage bytes. Failure surfaces downstream, at the AEAD tag check, not in
the encoding layer — consistent with how image's wrong-seed failure mode
already works.

**B. Seed-derived rotation/offset instead of full shuffle (rejected).**
Simpler, but a much smaller permutation space per state and no clearer to
reason about. Strictly dominated by A.

**C. XOR the input ciphertext bits with a seed-derived keystream before
arithmetic-coding them (rejected).** The input is already AEAD ciphertext,
indistinguishable from random; XOR-ing it again adds no real defense and
just moves the seed-dependency into the wrong layer — it conflates the
disguise encoding (which should only reshape bytes into atoms, never
touch their meaning) with the crypto layer that already owns this
property. A is cleaner and keeps the seed-dependency a property of the
*encoding*, matching how image's seed is a property of its texture
generator, not of the plaintext.

## Design

### Seed derivation (Python)

A new domain-separated label, distinct from the existing filler-seed
label, both derived from the same `nonce`:

```python
_PERMUTATION_SEED_LABEL = b"airwire-markov-permutation-seed"
permutation_seed = derive_key(nonce, _PERMUTATION_SEED_LABEL, size=_FILLER_SEED_SIZE)
```

Kept separate from `_FILLER_SEED_LABEL` even though both trace back to
the same nonce: cheap domain separation, and it keeps "what gates real
content" and "what drives cosmetic filler" independently reasoned about
and independently testable.

### Per-state permutation (Python)

A new helper, called every time `encode_atoms`/`decode` visit a state in
their main walk loop, memoized per-call via a plain local `dict` — *not*
the module-level `lru_cache` used for the raw frozen chain, since the
permutation depends on the nonce and must not leak across calls with
different nonces:

```python
def _permuted_candidates(chain: _Chain, state: _State, permutation_seed: bytes, cache: Dict[_State, _Candidates]) -> _Candidates:
    cached = cache.get(state)
    if cached is not None:
        return cached
    candidates = _candidates_for(chain, state)
    key = derive_key(permutation_seed, "".join(state).encode("utf-8"), size=8)
    shuffled = list(candidates)
    Random(int.from_bytes(key, "big")).shuffle(shuffled)
    cache[state] = shuffled
    return shuffled
```

Both `encode_atoms`'s and `decode`'s main walk loops call
`_permuted_candidates` instead of `_candidates_for` directly, feeding the
result into `candidate_ranges`. `_candidates_for` itself is unchanged and
still used directly by `_finish_sentence` (see below).

### Filler completion is unaffected

`_finish_sentence`/`finishSentence` pick words via weighted random choice
over `(word, weight)` pairs — order-invariant, since `random.choices`
(Python) / the manual cumulative-weight walk (TypeScript) don't care what
order the pairs arrive in. They keep calling `_candidates_for`/
`candidatesFor` directly, untouched by this change. The state filler
starts from will differ across seeds now (since the real walk that
precedes it is now seed-dependent too), but filler completion from any
given state remains exactly as correct as before.

### TypeScript parity

Same shape, reusing the primitives already established for filler
(`chainSeed`, the mulberry32 `Prng` — explicitly not required to be
bit-exact with Python's `random.Random`, each side only needs to
round-trip with itself):

```typescript
function permutedCandidates(chain: Chain, state: readonly string[], permutationSeed: number, cache: Map<string, Candidate<string>[]>): Candidate<string>[] {
  const key = stateKey(state);
  const cached = cache.get(key);
  if (cached) return cached;
  const candidates = candidatesFor(chain, state);
  const seed = chainSeed(permutationSeed, key);
  const prng = new Prng(seed);
  const shuffled = [...candidates];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = prng.nextInt(0, i + 1);
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  cache.set(key, shuffled);
  return shuffled;
}
```

### API change: `decodeText` gains a `seed` parameter

This is the one real breaking change. Today, `decodeText(language,
encoded, length)` takes no seed at all — decode never needed one before,
since filler is generate-only-on-encode and word validity never depended
on order. Now it must:

```typescript
export async function decodeText(language: string, encoded: string, length: number, seed = 0): Promise<Uint8Array>
```

Python's `MarkovEncoding.decode` needs **no signature change** — it
already threads `nonce: bytes` through the `ChunkEncoding` interface
(previously unused by Markov). Only its behavior changes.

### UI wiring

`reveal()` in `app.component.ts` must pass `this.textSeed()` into
`decodeText`. Text mode reuses the *same* `textSeed()` signal for both
obfuscate and reveal — no separate "reveal seed" field like image mode
has — since text mode, unlike image mode, has no "upload a foreign
disguised text with independently-known metadata" flow; it only ever
reveals what was just obfuscated on the same page, the same way
`originalByteLength()` is already silently reused for reveal's `length`
today.

### Tamper-detection demo behavior is preserved

Word validity at a given state still doesn't depend on order (same word
set, just reassigned bit ranges), so editing the disguised text before
hitting Reveal still fails the same way it does today: an invalid word
raises "not a valid continuation," a valid-but-wrong word desyncs the bit
recovery and produces garbled output.

### Behavior change worth documenting explicitly: cover-text length is no longer seed-invariant

Two different "lengths" are in play, and only one of them stays invariant:

- The **original data byte length** decode recovers
  (`length`/`BitAccumulator`) stays exactly correct: with the right seed,
  decode always reconstructs precisely the original bytes. Round-trip
  correctness is fully preserved.
- The **length of the generated cover text itself** (word/character
  count) is no longer seed-invariant for the same input data.
  `candidate_ranges` builds cumulative bit-range boundaries in candidate
  list order (`core/sources/arithmetic.py:36-61`); reordering candidates
  moves where each word's boundary falls, so a different seed can make a
  step consume a different number of bits, hence choose a different word,
  hence produce a different total word count. Before this change, only
  the filler tail's length varied by nonce; after, the whole text's
  length can vary. This mirrors how image's cover texture also looks
  different per seed — expected, not a bug, and it doesn't affect
  anything downstream (chunk packing in `chunking.py`'s `_greedy_pack` is
  streaming/greedy and never assumed a fixed encoded length).

## Error Handling

No new error paths. Decoding with the wrong seed does not raise a
distinct exception at the Markov-encoding layer — words remain
recognizable as valid state transitions (membership is order-independent),
so the walk completes, but recovers corrupted bits. This is caught by the
existing AEAD tag check one layer up (`Symmetric.decrypt`), exactly the
same failure shape image's wrong-seed case already has. No behavior
change needed to `MarkovModelError`/decode's existing `ValueError` cases.

## Testing

For both languages, add:

- Round-trip still holds per-seed (same seed used for encode and decode
  recovers the original bytes exactly).
- Decoding with the *wrong* seed reliably produces different output than
  the original bytes (checked across several payload sizes, following the
  same multi-size pattern already used for
  `test_filler_completion_differs_across_nonces`/its TypeScript
  equivalent, to avoid the same class of flakiness where a single random
  sample might not exercise the affected code path).
- Existing filler-completion tests continue to pass unmodified, proving
  filler stayed decoupled from this change.
- Existing tamper-detection tests continue to pass unmodified.
