# Markov Seed-Gating Broadening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Markov-chain text disguise's seed genuinely gate decoding of the real content — not just the cosmetic filler tail — matching how the image disguise's seed already gates decoding, in both `core/sources/markov.py` (Python) and `web-demo/src/app/core/markov.ts` (TypeScript).

**Architecture:** Every state's candidate list, currently loaded in a fixed alphabetical order, gets shuffled by a seed-derived permutation before being handed to `candidate_ranges`/`candidateRanges` (the function that assigns bit-range boundaries to each word). Both encode and decode derive the same permutation from the same seed/nonce, using a new domain-separated label distinct from the existing filler-seed label. Filler completion (`_finish_sentence`/`finishSentence`) is untouched — it already picks words via order-invariant weighted random choice.

**Tech Stack:** Python 3 (`core/`), TypeScript/Angular 19 (`web-demo/`). No new dependencies.

## Global Constraints

- Domain-separate the new permutation seed from the existing filler seed, even though both derive from the same nonce/seed input (see design doc's "Seed derivation" section) — use `_PERMUTATION_SEED_LABEL = b"airwire-markov-permutation-seed"` (Python) / `PERMUTATION_SEED_LABEL = 'airwire-markov-permutation-seed'` (TypeScript).
- The per-state permutation cache must be scoped to a single `encode_atoms`/`decode` (or `encodeText`/`decodeText`) call — a local `dict`/`Map`, never the module-level `lru_cache` used for the raw frozen chain, since the permutation depends on the nonce/seed and must not leak across calls with different ones.
- `_candidates_for`/`candidatesFor` (raw, unpermuted order) stays exactly as-is and keeps being used directly by `_finish_sentence`/`finishSentence` — do not route filler completion through the new permuted helper.
- Full spec: `docs/superpowers/specs/2026-09-08-markov-seed-broadening-design.md`.

---

### Task 1: Python — seed-derived per-state candidate permutation

**Files:**
- Modify: `core/sources/markov.py`
- Modify: `core/tests/test_markov.py`

**Interfaces:**
- Consumes: existing `_State`, `_Candidates`, `_Chain` types; `_candidates_for(chain, state) -> _Candidates`; `derive_key(*parts: bytes, size: int) -> bytes` from `sources/crypto.py`.
- Produces: `_permuted_candidates(chain: _Chain, state: _State, permutation_seed: bytes, cache: Dict[_State, _Candidates]) -> _Candidates`, used by Task 3's manual verification reasoning (no other task consumes this directly — the web-demo port in Task 2 is independent).

- [ ] **Step 1: Write the failing tests**

Add to `core/tests/test_markov.py`, right after the existing `test_filler_completion_differs_across_nonces` test:

```python
def test_decode_with_wrong_nonce_does_not_recover_original_data() -> None:
    # The seed now gates the ENTIRE walk, not just the filler tail -- decoding with the wrong
    # nonce should recover corrupted bytes, the same way a wrong image seed recovers a garbled
    # payload. Checked across several sizes for the same reason the filler-nonce test is: a
    # single random sample is an unreliable way to check a probabilistic property.
    other_nonce = token_bytes(24)
    saw_mismatch = False
    for size in (1, 5, 13, 37, 80, 199):
        data = token_bytes(size)
        text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
        recovered = MARKOV_ENG.decode(text, len(data), other_nonce)
        if recovered != data:
            saw_mismatch = True
    assert saw_mismatch


def test_encode_output_varies_by_nonce_even_without_filler() -> None:
    # Before this change, only the filler tail depended on the nonce; the real-content walk was
    # nonce-independent (fixed alphabetical candidate order). Confirms that's no longer true.
    other_nonce = token_bytes(24)
    saw_difference = False
    for size in (1, 5, 13, 37, 80, 199):
        data = token_bytes(size)
        a = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
        b = b"".join(MARKOV_ENG.encode_atoms(data, other_nonce))
        if a != b:
            saw_difference = True
    assert saw_difference
```

Also update the `NONCE` comment (currently `# now seeds filler completion -- see
test_filler_completion_differs_across_nonces.`) to:

```python
NONCE = token_bytes(24)  # now seeds real-content candidate order too, not just filler completion --
# see test_decode_with_wrong_nonce_does_not_recover_original_data.
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run (from `core/`): `pytest tests/test_markov.py::test_decode_with_wrong_nonce_does_not_recover_original_data tests/test_markov.py::test_encode_output_varies_by_nonce_even_without_filler -v`
Expected: both FAIL (current code ignores nonce for real content, so `recovered == data` and `a == b` for every size).

- [ ] **Step 3: Implement the permutation helper and wire it into encode/decode**

In `core/sources/markov.py`, add near the existing `_FILLER_SEED_LABEL`/`_FILLER_SEED_SIZE` constants:

```python
_PERMUTATION_SEED_LABEL = b"airwire-markov-permutation-seed"
```

Add a new helper function right after `_candidates_for`:

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

In `MarkovEncoding.encode_atoms`, right after `seed = derive_key(nonce, _FILLER_SEED_LABEL, size=_FILLER_SEED_SIZE)`, add:

```python
            permutation_seed = derive_key(nonce, _PERMUTATION_SEED_LABEL, size=_FILLER_SEED_SIZE)
            permutation_cache: Dict[_State, _Candidates] = {}
```

Then change the main-loop candidate lookup from:

```python
                candidates = _candidates_for(chain, state)
```

to:

```python
                candidates = _permuted_candidates(chain, state, permutation_seed, permutation_cache)
```

In `MarkovEncoding.decode`, right after `state = begin_state`, add:

```python
            permutation_seed = derive_key(nonce, _PERMUTATION_SEED_LABEL, size=_FILLER_SEED_SIZE)
            permutation_cache: Dict[_State, _Candidates] = {}
```

Then change its candidate lookup from:

```python
                candidates = _candidates_for(chain, state)
```

to:

```python
                candidates = _permuted_candidates(chain, state, permutation_seed, permutation_cache)
```

Leave every other call to `_candidates_for` (inside `_finish_sentence`) untouched.

- [ ] **Step 4: Run the full Markov test file to verify everything passes**

Run: `pytest tests/test_markov.py -v`
Expected: all tests PASS, including the two new ones and every pre-existing one (round-trip,
determinism, tampering, filler-completion, newline-boundary tests all still pass unmodified).

- [ ] **Step 5: Run the full core test suite**

Run: `pytest` (from `core/`)
Expected: all tests PASS (no other module touches `markov.py`'s internals directly).

- [ ] **Step 6: Commit**

```bash
git add core/sources/markov.py core/tests/test_markov.py
git commit -m "feat: gate Markov real-content decoding on the nonce, not just filler"
```

---

### Task 2: TypeScript — matching permutation in the web-demo port

**Files:**
- Modify: `web-demo/src/app/core/markov.ts`
- Modify: `web-demo/src/app/core/markov.spec.ts`

**Interfaces:**
- Consumes: existing `Chain`, `Candidate<T>` types; `candidatesFor(chain, state) -> Candidate<string>[]`; `chainSeed(seed: number, text: string): number` and `Prng` from `./prng`.
- Produces: `permutedCandidates(chain: Chain, state: readonly string[], permutationSeed: number, cache: Map<string, Candidate<string>[]>): Candidate<string>[]`; `decodeText`'s new `seed` parameter (5th positional arg after `length`... actually 4th: `decodeText(language, encoded, length, seed = 0)`), consumed by Task 3's UI wiring.

- [ ] **Step 1: Write the failing tests**

Add to `web-demo/src/app/core/markov.spec.ts` (follow the existing file's structure — check its imports and helper patterns first, they mirror `test_markov.py`'s `_round_trip`/multi-size-loop style):

```typescript
it('does not recover the original bytes when decoded with the wrong seed', async () => {
  let sawMismatch = false;
  for (const size of [1, 5, 13, 37, 80, 199]) {
    const data = randomBytes(size);
    const text = await encodeText('eng', data, 42);
    const recovered = await decodeText('eng', text, data.length, 99);
    if (!bytesEqual(recovered, data)) {
      sawMismatch = true;
    }
  }
  expect(sawMismatch).toBeTrue();
});

it('produces different encoded text for different seeds even without filler triggering', async () => {
  let sawDifference = false;
  for (const size of [1, 5, 13, 37, 80, 199]) {
    const data = randomBytes(size);
    const a = await encodeText('eng', data, 42);
    const b = await encodeText('eng', data, 99);
    if (a !== b) {
      sawDifference = true;
    }
  }
  expect(sawDifference).toBeTrue();
});
```

Use whatever random-bytes/bytes-equality helpers the existing spec file already defines (it must have
something equivalent, since its existing determinism/seed-differs tests need the same tools) — reuse
those exact helper names instead of introducing new ones if they already exist.

- [ ] **Step 2: Run the new tests to verify they fail**

Run (from `web-demo/`): `npx ng test --watch=false --browsers=ChromeHeadless`
Expected: the two new tests FAIL (current code ignores the seed for real content, and
`decodeText` doesn't even accept a 4th argument yet — this may be a type error rather than a
runtime failure, which also counts as "fails" here).

- [ ] **Step 3: Implement the permutation helper and wire it into encode/decode**

In `web-demo/src/app/core/markov.ts`, add near the top, after the `MAX_FILLER_WORDS` constant:

```typescript
const PERMUTATION_SEED_LABEL = 'airwire-markov-permutation-seed';
```

Add a new function right after `candidatesFor`:

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

In `encodeText`, right after `let chained = seed;`, add:

```typescript
  const permutationSeed = chainSeed(seed, PERMUTATION_SEED_LABEL);
  const permutationCache = new Map<string, Candidate<string>[]>();
```

Then change its main-loop candidate lookup from:

```typescript
    const candidates = candidatesFor(chain, state);
```

to:

```typescript
    const candidates = permutedCandidates(chain, state, permutationSeed, permutationCache);
```

Change `decodeText`'s signature from:

```typescript
export async function decodeText(language: string, encoded: string, length: number): Promise<Uint8Array> {
```

to:

```typescript
export async function decodeText(language: string, encoded: string, length: number, seed = 0): Promise<Uint8Array> {
```

Right after `let state = beginState;` in `decodeText`, add:

```typescript
  const permutationSeed = chainSeed(seed, PERMUTATION_SEED_LABEL);
  const permutationCache = new Map<string, Candidate<string>[]>();
```

Then change its candidate lookup from:

```typescript
    const candidates = candidatesFor(chain, state);
```

to:

```typescript
    const candidates = permutedCandidates(chain, state, permutationSeed, permutationCache);
```

Leave `finishSentence`'s call to `candidatesFor` untouched.

- [ ] **Step 4: Run the full web-demo test suite to verify everything passes**

Run: `npx ng test --watch=false --browsers=ChromeHeadless`
Expected: all tests PASS, including the two new ones and every pre-existing one.

- [ ] **Step 5: Commit**

```bash
git add web-demo/src/app/core/markov.ts web-demo/src/app/core/markov.spec.ts
git commit -m "feat: gate web-demo Markov decoding on the seed, not just filler"
```

---

### Task 3: Web-demo UI — pass the seed through to reveal, and verify end-to-end

**Files:**
- Modify: `web-demo/src/app/app.component.ts`

**Interfaces:**
- Consumes: `decodeText(language, encoded, length, seed)` from Task 2.
- Produces: nothing consumed by a later task — this is the last task.

- [ ] **Step 1: Wire the seed into `reveal()`**

In `web-demo/src/app/app.component.ts`, change:

```typescript
      const bytes = await decodeText(this.language(), this.obfuscatedText(), this.originalByteLength());
```

to:

```typescript
      const bytes = await decodeText(this.language(), this.obfuscatedText(), this.originalByteLength(), this.textSeed());
```

No HTML changes — the Seed field already exists in `app.component.html` from the newline+filler feature.

- [ ] **Step 2: Run the web-demo test suite once more**

Run (from `web-demo/`): `npx ng test --watch=false --browsers=ChromeHeadless`
Expected: all tests PASS (this file has no dedicated spec; `app.component.spec.ts`'s existing
smoke test doesn't exercise `reveal()`'s internals).

- [ ] **Step 3: Manually verify in a real browser (use the `run` skill)**

Launch the web-demo (`npm start` under `web-demo/`), open it in a real browser session, and:

1. Type a multi-sentence message, leave Seed at its default, click Obfuscate, click Reveal —
   confirm the revealed text matches the original exactly (seed-consistent round trip still
   works).
2. With the same obfuscated text still showing, click Randomize next to the Seed field (changing
   `textSeed` without re-obfuscating), then click Reveal again — confirm the revealed text no
   longer matches the original (demonstrates the seed now genuinely gates decoding of the real
   content, not just cosmetic filler).
3. Click Obfuscate again (now with the new seed) — confirm the obfuscated text differs from the
   first run — then click Reveal — confirm it now matches the original again (seed-consistent
   round trip holds for the new seed too).

- [ ] **Step 4: Commit**

```bash
git add web-demo/src/app/app.component.ts
git commit -m "feat: wire the text seed into web-demo's reveal so it matches obfuscate"
```
