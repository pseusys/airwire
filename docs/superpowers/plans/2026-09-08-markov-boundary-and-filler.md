# Markov Newline Boundaries + Seed-Chained Filler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the literal `___END__` sentence-boundary token with a plain `\n`, and complete
the otherwise-truncated final sentence of a Markov-disguised message using seed-chained filler
words, in both the real Python protocol (`core/`) and the standalone web demo (`web-demo/`).

**Architecture:** Two independent behavior changes, each implemented twice (once per codebase):
(1) render/parse sentence boundaries as `\n` instead of `___END__`; (2) when real ciphertext bits
run out mid-sentence, finish it with a seeded-PRNG weighted random walk over the same Markov chain,
seeded from a value chained across every real sentence's own content. Decode-side logic needs no
awareness of the filler at all in either codebase, since both already stop consuming words the
moment the target byte length is recovered.

**Tech Stack:** Python 3.12 (`core/`, pytest), TypeScript/Angular 19 (`web-demo/`, Karma+Jasmine).

## Global Constraints

- No word in either frozen Markov model (`core/sources/data/markov_eng.json`,
  `markov_rus.json`) may ever appear as the literal string `___END__` in rendered output again —
  verified in the design doc that no vocabulary word contains an embedded newline, which is what
  makes `\n` safe as a replacement where a period wasn't.
- Decode-side logic must NOT change to accommodate filler — it already stops via
  `length`/`accumulator.done()` before ever reaching filler content; if a task's decode changes
  more than tokenization, that's a sign of scope creep.
- The filler-completion loop must be bounded (a fixed max word count) and fail closed
  (`MarkovModelError` in Python, a thrown `Error` in TypeScript) rather than loop forever.
- The TypeScript seed/PRNG mechanism does **not** need to be cross-platform bit-exact with Python's
  — it only needs to be deterministic within one page load for one `(data, seed)` pair, exactly
  like the existing `Prng` class in `web-demo/src/app/core/prng.ts` already is for image textures.
- Both frozen languages (`eng`, `rus`) must keep round-tripping correctly in Python; the TypeScript
  demo must keep round-tripping correctly for both `eng` and `rus` model files it can fetch.
- Design reference for all "why" questions in this plan:
  `docs/superpowers/specs/2026-09-08-markov-boundary-and-filler-design.md`.

---

## File Structure

- Modify: `core/sources/markov.py` — encode/decode rendering, tokenization, filler completion,
  seed chaining.
- Modify: `core/tests/test_markov.py` — updated/added tests.
- Modify: `web-demo/src/app/core/markov.ts` — same behavior change, TypeScript port.
- Modify: `web-demo/src/app/core/prng.ts` — add a `chainSeed` helper (the TS side's equivalent of
  Python's `derive_key`, for chaining the filler seed across sentences).
- Create: `web-demo/src/app/core/markov.spec.ts` — no per-module unit tests exist yet for any
  `core/*.ts` file in this demo (only a component-level smoke test does); this plan introduces the
  first one, for exactly the module this plan touches.
- Modify: `web-demo/src/app/app.component.ts` — add a `textSeed` signal + `randomizeTextSeed()`,
  mirroring the existing `imageSeed`/`randomizeImageSeed()` pattern, and thread it into `obfuscate()`.
- Modify: `web-demo/src/app/app.component.html` — add the matching "Seed" field + Randomize button
  to the text-mode panel, mirroring the image-mode markup already in the same file.

---

### Task 1: Python — render sentence boundaries as `\n`, not a literal `___END__` token

**Files:**
- Modify: `core/sources/markov.py`
- Test: `core/tests/test_markov.py`

**Interfaces:**
- Consumes: nothing new — uses the existing `BitCursor`/`BitAccumulator`/`candidate_ranges`/
  `common_leading_bits`/`strip_top_bits` from `sources/arithmetic.py`, unchanged.
- Produces: `MarkovEncoding.encode_atoms`/`decode` keep their existing signatures
  (`encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]`,
  `decode(self, encoded: bytes, length: int, nonce: bytes) -> bytes`). New module-level function
  `_tokenize(text: str) -> List[str]`, which Task 2 also relies on unchanged.

- [ ] **Step 1: Write the failing tests**

Replace the single test `test_output_contains_sentence_boundaries_for_longer_input` in
`core/tests/test_markov.py` with these two, and add a small line-aware helper the later tests in
this task also need. Insert the helper right after the `NONCE` constant (after line 8) and the two
new tests where the old one was (lines 51–53):

```python
def _replace_first_word(text: str, replacement: str) -> str:
    lines = text.split("\n")
    words = lines[0].split()
    words[0] = replacement
    lines[0] = " ".join(words) + " "
    return "\n".join(lines)


def test_output_contains_newline_sentence_boundaries_for_longer_input() -> None:
    text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(200), NONCE)).decode("utf-8")
    assert "\n" in text


def test_output_never_contains_the_literal_end_token() -> None:
    text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(200), NONCE)).decode("utf-8")
    assert END_TOKEN not in text
```

Then update the three tests that currently reconstruct tampered/truncated text by flatly
`.split()`-ing and rejoining with single spaces — that destroys the new `\n` boundaries, so they'd
be testing the wrong thing. Replace `test_decode_rejects_word_not_valid_at_current_state`,
`test_decode_rejects_too_short_word_sequence`, and
`test_tampering_a_still_valid_word_changes_the_recovered_bytes` with:

```python
def test_decode_rejects_word_not_valid_at_current_state() -> None:
    data = token_bytes(20)
    text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE)).decode("utf-8")
    tampered = _replace_first_word(text, "supercalifragilisticexpialidocious").encode("utf-8")
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(tampered, len(data), NONCE)


def test_decode_rejects_too_short_word_sequence() -> None:
    data = token_bytes(50)
    text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE)).decode("utf-8")
    truncated = text[: len(text) // 2].encode("utf-8")
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(truncated, len(data), NONCE)


def test_tampering_a_still_valid_word_changes_the_recovered_bytes() -> None:
    data = token_bytes(20)
    text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE)).decode("utf-8")
    first_word = text.split("\n")[0].split()[0]
    replacement = "The" if first_word != "The" else "A"
    tampered_text = _replace_first_word(text, replacement)
    original_result = MARKOV_ENG.decode(text.encode("utf-8"), len(data), NONCE)
    try:
        tampered_result = MARKOV_ENG.decode(tampered_text.encode("utf-8"), len(data), NONCE)
    except ValueError:
        return  # also an acceptable outcome: the swap desynchronized the walk entirely.
    assert tampered_result != original_result
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd core && poetry run pytest tests/test_markov.py -v`
Expected: the two new tests fail (`test_output_never_contains_the_literal_end_token` fails because
`___END__` is still literally present; `test_output_contains_newline_sentence_boundaries_for_longer_input`
fails because there's no `\n` yet). The three rewritten tests should currently still pass by
coincidence (nothing's broken yet) — that's fine, they'll matter once Step 3 lands.

- [ ] **Step 3: Implement newline rendering and line-aware tokenization**

In `core/sources/markov.py`, replace the "Known limitations" bullet at lines 53–56 (the one
starting "The sentence-boundary token is rendered verbatim...") with:

```markdown
- Resolved: sentence boundaries used to render as a literal `___END__` token -- correct but an
  obvious tell to a human reader. They're now rendered as a plain `\n` instead: no word in either
  frozen model can ever contain an embedded newline (both are built one Tatoeba sentence per line,
  see `sources/corpus.py`), so `\n` is unambiguous as a boundary marker in a way a period isn't --
  a period *is* a real character inside real vocabulary words (`Mr.`, `Dr.`), which is exactly why
  reinserting boundaries by scanning for periods was tried and rejected; see
  [the design doc](../specs/2026-09-08-markov-boundary-and-filler-design.md)
  for the full evidence. Bonus: a multi-line disguised message is unremarkable, unlike a literal
  `___END__` string ever was.
```

In `MarkovEncoding.encode_atoms`, change the line `yield (word + " ").encode("utf-8")` to render
`END_TOKEN` as a newline instead:

```python
            word, low, high = next((w, lo, hi) for w, lo, hi in ranges if lo <= peeked <= hi)
            rendered = "\n" if word == END_TOKEN else word + " "
            yield rendered.encode("utf-8")
            state = _next_state(state, word, begin_state)
```

Add a new module-level function just above the `_IDENTIFIERS` dict:

```python
def _tokenize(text: str) -> List[str]:
    """
    Invert the encode side's sentence-boundary rendering: split rendered text back into a flat
    word stream with a synthetic `END_TOKEN` reinserted at each real sentence boundary (a `\n`).
    The final line only gets one if the text actually ends in `\n` (a genuinely completed sentence)
    -- a mid-sentence fragment with no trailing newline is left without one, since decode never
    needs to see a boundary past the last bit it actually recovers.
    """

    lines = text.split("\n")
    trailing_complete = text.endswith("\n")
    if trailing_complete:
        lines.pop()

    words: List[str] = []
    last_index = len(lines) - 1
    for index, line in enumerate(lines):
        words.extend(line.split())
        if index != last_index or trailing_complete:
            words.append(END_TOKEN)
    return words
```

In `MarkovEncoding.decode`, replace the line `words = encoded.decode("utf-8").split()` with:

```python
        try:
            words = _tokenize(encoded.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise ValueError(f"Markov-encoded chunk payload isn't valid UTF-8: {error}!") from error
```

(This replaces the existing `try`/`except` block that wraps the old `.split()` call — the
`try`/`except` structure stays, only its body changes.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd core && poetry run pytest tests/test_markov.py -v`
Expected: all tests pass, including the two new ones and the three rewritten ones.

- [ ] **Step 5: Run the full core test suite to check for regressions**

Run: `cd core && poetry run pytest -v`
Expected: all tests pass (this also exercises `chunking.py`'s use of `MarkovEncoding` through the
`ChunkEncoding` interface, unaffected by this change since the interface itself didn't change).

- [ ] **Step 6: Commit**

```bash
cd core && git add sources/markov.py tests/test_markov.py
git commit -m "feat: render Markov sentence boundaries as newlines instead of a literal token"
```

---

### Task 2: Python — seed-chained filler completion of the final sentence

**Files:**
- Modify: `core/sources/markov.py`
- Test: `core/tests/test_markov.py`

**Interfaces:**
- Consumes: `_tokenize` and the newline rendering from Task 1, unchanged. `derive_key(*parts:
  bytes, size: int) -> bytes` from `core/sources/crypto.py` (already exists, unmodified).
- Produces: new module-level function `_finish_sentence(chain: _Chain, state: _State, begin_state:
  _State, seed: bytes) -> Iterator[bytes]`, importable by tests. `encode_atoms`'s external
  signature is unchanged; its output now always ends in a completed sentence.

- [ ] **Step 1: Write the failing tests**

Add to `core/tests/test_markov.py`. First, widen the import line at the top of the file from:

```python
from sources.markov import END_TOKEN, MARKOV_ENG, MARKOV_RUS, MarkovEncoding, MarkovModelError
```

to:

```python
from sources.markov import BEGIN_TOKEN, END_TOKEN, MARKOV_ENG, MARKOV_RUS, MarkovEncoding, MarkovModelError, _finish_sentence
```

`nonce` is no longer ignored by `MarkovEncoding` after this task, so its now-stale comment needs
fixing too. Change:

```python
NONCE = token_bytes(24)  # MarkovEncoding ignores it; kept for interface parity with ImageEncoding.
```

to:

```python
NONCE = token_bytes(24)  # now seeds filler completion -- see test_filler_completion_differs_across_nonces.
```

Then append these tests at the end of the file:

```python
def test_encoded_text_always_ends_with_a_completed_sentence() -> None:
    for size in (1, 5, 13, 37, 80, 199):
        text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(size), NONCE)).decode("utf-8")
        assert text.endswith("\n"), f"Expected a completed final sentence for a {size}-byte payload!"


def test_filler_completion_is_deterministic() -> None:
    data = token_bytes(37)
    first = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
    second = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
    assert first == second


def test_filler_completion_differs_across_nonces() -> None:
    data = token_bytes(37)
    other_nonce = token_bytes(24)
    a = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
    b = b"".join(MARKOV_ENG.encode_atoms(data, other_nonce))
    assert a != b


def test_round_trip_still_correct_when_filler_is_used() -> None:
    for size in (1, 5, 13, 37, 80, 199):
        data = token_bytes(size)
        assert _round_trip(MARKOV_ENG, data) == data


def test_finish_sentence_raises_when_no_path_to_end_exists() -> None:
    begin_state = (BEGIN_TOKEN, BEGIN_TOKEN)
    state_a = ("stuck", "here")
    state_b = ("here", "stuck")
    chain = {
        state_a: [("stuck", 1)],
        state_b: [("here", 1)],
    }
    with pytest.raises(MarkovModelError):
        list(_finish_sentence(chain, state_a, begin_state, b"\x00\x00\x00\x00"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd core && poetry run pytest tests/test_markov.py -v`
Expected: `ImportError`/`AttributeError` on `_finish_sentence` (doesn't exist yet), and
`test_encoded_text_always_ends_with_a_completed_sentence` would fail once that import is fixed
(most sizes won't happen to land exactly on a sentence boundary yet).

- [ ] **Step 3: Implement seed chaining and filler completion**

In `core/sources/markov.py`, change the import block from:

```python
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from sources.arithmetic import BitAccumulator, BitCursor, candidate_ranges, common_leading_bits, strip_top_bits
from sources.encodings import ChunkEncoding
from sources.proto import hyperchunk_pb2
```

to:

```python
from functools import lru_cache
from pathlib import Path
from random import Random
from typing import Dict, Iterator, List, Tuple

from sources.arithmetic import BitAccumulator, BitCursor, candidate_ranges, common_leading_bits, strip_top_bits
from sources.crypto import derive_key
from sources.encodings import ChunkEncoding
from sources.proto import hyperchunk_pb2
```

Add these constants right after `END_TOKEN = "___END__"`:

```python
_FILLER_SEED_LABEL = b"airwire-markov-filler-seed"
_FILLER_SEED_SIZE = 4
_MAX_FILLER_WORDS = 50
```

Append this second "Resolved" bullet to the module docstring's "Known limitations" section (after
the one Task 1 rewrote):

```markdown
- Resolved: the very last sentence of a hyperslice's rendered text used to just trail off mid-walk
  whenever the real ciphertext bits ran out before a sentence naturally finished -- unlike every
  sentence before it, which always ends in a real, bit-driven `___END__`/`\n`. `_finish_sentence`
  now completes it with plausible, non-secret filler words (weighted by the same corpus
  frequencies, picked by a seeded PRNG rather than the arithmetic coder) whenever this happens.
  Decode needs no changes for this: it already stops consuming words the moment `length` bytes are
  recovered, so the filler tail is already invisible to it, real or not. See the design doc linked
  above for why the seed is chained across each real sentence's own content
  (`derive_key(seed, sentence_bytes, ...)`) rather than derived from `nonce` alone.
```

Add this new function just above `_IDENTIFIERS`:

```python
def _finish_sentence(chain: _Chain, state: _State, begin_state: _State, seed: bytes) -> Iterator[bytes]:
    """
    Complete an in-progress sentence when real ciphertext bits have run out mid-walk, so the
    rendered text's last sentence always ends like every other one instead of trailing off. Not
    secret -- the completion words carry no ciphertext bits, only cosmetic filler -- so a plain
    seeded PRNG (not the arithmetic coder) picks each one, weighted by the same corpus frequencies
    real words are chosen from, until the walk lands back on `begin_state` (an END_TOKEN draw).
    Bounded by `_MAX_FILLER_WORDS`: a frozen model with no path to END_TOKEN from some state would
    otherwise loop forever, which is a setup problem, not a wire-tamper one.
    """

    rng = Random(int.from_bytes(seed, "big"))
    for _ in range(_MAX_FILLER_WORDS):
        candidates = _candidates_for(chain, state)
        words = [word for word, _ in candidates]
        weights = [count for _, count in candidates]
        word = rng.choices(words, weights=weights, k=1)[0]
        state = _next_state(state, word, begin_state)
        if word == END_TOKEN:
            yield b"\n"
            return
        yield (word + " ").encode("utf-8")

    raise MarkovModelError(f"Could not complete the final sentence within {_MAX_FILLER_WORDS} words; the frozen model may have no path to {END_TOKEN!r} from this state!")
```

Replace the whole body of `MarkovEncoding.encode_atoms` with:

```python
    def encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]:
        state_size, chain = _load_model(self.language)
        begin_state: _State = (BEGIN_TOKEN,) * state_size
        cursor = BitCursor(data)
        low, high, width = 0, 1, 1
        state = begin_state
        seed = derive_key(nonce, _FILLER_SEED_LABEL, size=_FILLER_SEED_SIZE)
        sentence_words: List[str] = []

        while cursor.remaining() > 0:
            budget = cursor.remaining()
            candidates = _candidates_for(chain, state)
            ranges, low, high, width = candidate_ranges(low, high, width, candidates, budget)
            peeked = cursor.peek(width)
            word, low, high = next((w, lo, hi) for w, lo, hi in ranges if lo <= peeked <= hi)
            state = _next_state(state, word, begin_state)
            if word == END_TOKEN:
                yield b"\n"
                seed = derive_key(seed, "".join(sentence_words).encode("utf-8"), size=_FILLER_SEED_SIZE)
                sentence_words = []
            else:
                rendered = word + " "
                yield rendered.encode("utf-8")
                sentence_words.append(rendered)
            common = common_leading_bits(low, high, width)
            if common:
                cursor.consume(min(common, cursor.remaining()))
                low, high, width = strip_top_bits(low, high, width, common)

        if state != begin_state:
            yield from _finish_sentence(chain, state, begin_state, seed)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd core && poetry run pytest tests/test_markov.py -v`
Expected: all tests pass.

- [ ] **Step 5: Run the full core test suite to check for regressions**

Run: `cd core && poetry run pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd core && git add sources/markov.py tests/test_markov.py
git commit -m "feat: complete the final Markov sentence with seed-chained filler words"
```

---

### Task 3: TypeScript — render sentence boundaries as `\n`, not a literal `___END__` token

**Files:**
- Modify: `web-demo/src/app/core/markov.ts`
- Create: `web-demo/src/app/core/markov.spec.ts`

**Interfaces:**
- Consumes: unchanged `BitCursor`/`BitAccumulator`/`candidateRanges`/`commonLeadingBits`/
  `stripTopBits`/`Candidate` from `./arithmetic`.
- Produces: `encodeText(language: string, data: Uint8Array): Promise<string>` and
  `decodeText(language: string, encoded: string, length: number): Promise<Uint8Array>` keep their
  existing signatures for this task (Task 4 adds the `seed` parameter).

- [ ] **Step 1: Set up the model files this test needs, and write the failing tests**

The Karma test runner serves the `public/` directory (see `angular.json`'s `test.options.assets`),
but `public/models/*.json` is only populated by the `sync-models` npm script — run it once now so
`ng test` can fetch the real frozen models:

```bash
cd web-demo && npm run sync-models
```

Create `web-demo/src/app/core/markov.spec.ts`:

```typescript
import { decodeText, encodeText, END_TOKEN } from './markov';

describe('markov text disguise', () => {
  it('round-trips an empty payload', async () => {
    const data = new Uint8Array(0);
    const text = await encodeText('eng', data);
    const decoded = await decodeText('eng', text, 0);
    expect(decoded).toEqual(data);
  });

  it('round-trips arbitrary bytes through English', async () => {
    const data = new TextEncoder().encode('Hello, airwire! This is a demo message.');
    const text = await encodeText('eng', data);
    const decoded = await decodeText('eng', text, data.length);
    expect(decoded).toEqual(data);
  });

  it('round-trips arbitrary bytes through Russian', async () => {
    const data = new TextEncoder().encode('Привет, airwire!');
    const text = await encodeText('rus', data);
    const decoded = await decodeText('rus', text, data.length);
    expect(decoded).toEqual(data);
  });

  it('never contains the literal END token', async () => {
    const data = crypto.getRandomValues(new Uint8Array(200));
    const text = await encodeText('eng', data);
    expect(text).not.toContain(END_TOKEN);
  });

  it('contains a newline sentence boundary for longer input', async () => {
    const data = crypto.getRandomValues(new Uint8Array(200));
    const text = await encodeText('eng', data);
    expect(text).toContain('\n');
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web-demo && npm test -- --watch=false --browsers=ChromeHeadless`
Expected: the round-trip tests pass already (behavior unchanged so far), but "never contains the
literal END token" fails (`___END__` is still literally rendered).

- [ ] **Step 3: Implement newline rendering and line-aware tokenization**

In `web-demo/src/app/core/markov.ts`, update the module docstring (lines 1–6) to:

```typescript
/**
 * TypeScript port of core/sources/markov.py's encode/decode walk -- see that file's docstring for
 * the full explanation. This only reimplements the walk itself, not the `ChunkEncoding` wrapper
 * (there's no chunking/hyperchunk concept in this demo at all, per design -- see the top-level
 * component for why). Sentence boundaries render as a plain '\n', not a literal '___END__' token
 * -- see docs/superpowers/specs/2026-09-08-markov-boundary-and-filler-design.md for why that's
 * both safe (no vocabulary word can ever contain an embedded newline) and better camouflage than
 * either the literal token or a period would be.
 */
```

Replace the entire `encodeText` function body with:

```typescript
export async function encodeText(language: string, data: Uint8Array): Promise<string> {
  const { stateSize, chain } = await loadModel(language);
  const beginState = Array(stateSize).fill(BEGIN_TOKEN);
  const cursor = new BitCursor(data);
  let low = 0n;
  let high = 1n;
  let width = 1;
  let state = beginState;
  let text = '';

  while (cursor.remaining() > 0) {
    const budget = cursor.remaining();
    const candidates = candidatesFor(chain, state);
    const [ranges, newLow, newHigh, newWidth] = candidateRanges(low, high, width, candidates, budget);
    low = newLow;
    high = newHigh;
    width = newWidth;
    const peeked = cursor.peek(width);
    const match = ranges.find(([, lo, hi]) => lo <= peeked && peeked <= hi);
    if (!match) {
      throw new Error('No candidate range matched the peeked bits -- this should never happen.');
    }
    const [word, lo, hi] = match;
    low = lo;
    high = hi;
    state = nextState(state, word, beginState);
    text += word === END_TOKEN ? '\n' : word + ' ';
    const common = commonLeadingBits(low, high, width);
    if (common) {
      cursor.consume(Math.min(common, cursor.remaining()));
      [low, high, width] = stripTopBits(low, high, width, common);
    }
  }

  return text;
}
```

Add a new function directly above `decodeText`:

```typescript
/** Invert the encode side's sentence-boundary rendering: split rendered text back into a flat
 * word stream with a synthetic END_TOKEN reinserted at each real sentence boundary (a '\n'). The
 * final line only gets one if the text actually ends in '\n' (a genuinely completed sentence) --
 * a mid-sentence fragment with no trailing newline is left without one, since decode never needs
 * to see a boundary past the last bit it actually recovers. */
function tokenize(text: string): string[] {
  const lines = text.split('\n');
  const trailingComplete = text.endsWith('\n');
  if (trailingComplete) lines.pop();

  const words: string[] = [];
  const lastIndex = lines.length - 1;
  lines.forEach((line, index) => {
    words.push(...line.split(/\s+/).filter((word) => word.length > 0));
    if (index !== lastIndex || trailingComplete) {
      words.push(END_TOKEN);
    }
  });
  return words;
}
```

In `decodeText`, replace the line
`const words = encoded.split(/\s+/).filter((word) => word.length > 0);` with:

```typescript
  const words = tokenize(encoded);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web-demo && npm test -- --watch=false --browsers=ChromeHeadless`
Expected: all tests in `markov.spec.ts` pass, and the existing `app.component.spec.ts` tests still
pass too.

- [ ] **Step 5: Commit**

```bash
cd web-demo && git add src/app/core/markov.ts src/app/core/markov.spec.ts
git commit -m "feat: render web-demo Markov sentence boundaries as newlines instead of a literal token"
```

---

### Task 4: TypeScript — seed-chained filler completion of the final sentence

**Files:**
- Modify: `web-demo/src/app/core/markov.ts`
- Modify: `web-demo/src/app/core/prng.ts`
- Modify: `web-demo/src/app/core/markov.spec.ts`

**Interfaces:**
- Consumes: `tokenize` and newline rendering from Task 3, unchanged. `Prng` class from `./prng`.
- Produces: `encodeText(language: string, data: Uint8Array, seed = 0): Promise<string>` — new
  optional `seed` parameter, defaulting to `0`. `chainSeed(seed: number, text: string): number`,
  exported from `prng.ts`, for Task 5 to reuse conceptually (Task 5 doesn't call it directly, but
  should know it exists). `decodeText`'s signature is unchanged — it never needs the seed, exactly
  like the Python side's `decode` never needs `nonce` for this purpose either.

- [ ] **Step 1: Write the failing tests**

Append to `web-demo/src/app/core/markov.spec.ts`:

```typescript
  it('always ends with a completed sentence, across sizes that do not land on a boundary', async () => {
    for (const size of [1, 5, 13, 37, 80]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const text = await encodeText('eng', data, 7);
      expect(text.endsWith('\n')).toBeTrue();
    }
  });

  it('is deterministic for the same data and seed', async () => {
    const data = crypto.getRandomValues(new Uint8Array(30));
    const first = await encodeText('eng', data, 99);
    const second = await encodeText('eng', data, 99);
    expect(first).toEqual(second);
  });

  it('produces different output for different seeds over the same data', async () => {
    const data = crypto.getRandomValues(new Uint8Array(30));
    const a = await encodeText('eng', data, 1);
    const b = await encodeText('eng', data, 2);
    expect(a).not.toEqual(b);
  });

  it('still round-trips correctly when filler completion is used', async () => {
    for (const size of [1, 5, 13, 37, 80]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const text = await encodeText('eng', data, 7);
      const decoded = await decodeText('eng', text, size);
      expect(decoded).toEqual(data);
    }
  });
```

(These go inside the existing `describe('markov text disguise', ...)` block, after the tests Task 3
added.)

Note: this plan does **not** add a TypeScript equivalent of Python's
`test_finish_sentence_raises_when_no_path_to_end_exists`. Testing that directly would require
exporting `Chain`/`candidatesFor`/`finishSentence` purely for one low-probability edge case in a
non-authoritative demo; the bounded-loop safety net (`MAX_FILLER_WORDS`) still exists in the
implementation below, it's just not separately unit-tested here the way the Python side is.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web-demo && npm test -- --watch=false --browsers=ChromeHeadless`
Expected: `TS2554` compile error (`encodeText` doesn't accept a third argument yet), or once you
temporarily ignore that, the new tests fail because nothing about the output depends on a seed yet.

- [ ] **Step 3: Implement `chainSeed` and filler completion**

In `web-demo/src/app/core/prng.ts`, add at the end of the file:

```typescript

const FNV_OFFSET_BASIS = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

/**
 * Deterministically combine `seed` with `text` into a new 32-bit seed, via FNV-1a. Mirrors the
 * role of core/sources/crypto.py's `derive_key` for the Markov filler-completion design
 * (docs/superpowers/specs/2026-09-08-markov-boundary-and-filler-design.md) without needing a real
 * hash/crypto dependency in this demo -- fine here since what it seeds only ever drives non-secret
 * cosmetic filler, never anything that needs to resist prediction.
 */
export function chainSeed(seed: number, text: string): number {
  let hash = (seed ^ FNV_OFFSET_BASIS) >>> 0;
  const bytes = new TextEncoder().encode(text);
  for (const byte of bytes) {
    hash ^= byte;
    hash = Math.imul(hash, FNV_PRIME) >>> 0;
  }
  return hash >>> 0;
}
```

In `web-demo/src/app/core/markov.ts`, add this import (alongside the existing one from
`./arithmetic`):

```typescript
import { Prng, chainSeed } from './prng';
```

Add these near the top, after the `BEGIN_TOKEN`/`END_TOKEN` constants:

```typescript
const MAX_FILLER_WORDS = 50;

function stateEquals(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((word, index) => word === b[index]);
}

function weightedChoice(prng: Prng, candidates: Candidate<string>[]): string {
  const weights = candidates.map(([, weight]) => Number(weight));
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  let target = prng.next() * total;
  for (let i = 0; i < candidates.length; i++) {
    target -= weights[i];
    if (target < 0) return candidates[i][0];
  }
  return candidates[candidates.length - 1][0];
}

/** Complete an in-progress sentence when real ciphertext bits have run out mid-walk. Mirrors
 * `_finish_sentence` in markov.py: a seeded PRNG (not the arithmetic coder) picks each word,
 * weighted by the same corpus frequencies real words are chosen from, until the walk lands back
 * on `beginState` (an END_TOKEN draw), bounded by MAX_FILLER_WORDS to fail closed instead of
 * looping forever if a frozen model has no path to END_TOKEN from some state. */
function* finishSentence(chain: Chain, state: string[], beginState: string[], seed: number): Generator<string> {
  const prng = new Prng(seed);
  let current = state;
  for (let i = 0; i < MAX_FILLER_WORDS; i++) {
    const candidates = candidatesFor(chain, current);
    const word = weightedChoice(prng, candidates);
    current = nextState(current, word, beginState);
    if (word === END_TOKEN) {
      yield '\n';
      return;
    }
    yield word + ' ';
  }
  throw new Error(`Could not complete the final sentence within ${MAX_FILLER_WORDS} words; the frozen model may have no path to '${END_TOKEN}' from this state!`);
}
```

Replace the entire `encodeText` function body (written in Task 3) with:

```typescript
export async function encodeText(language: string, data: Uint8Array, seed = 0): Promise<string> {
  const { stateSize, chain } = await loadModel(language);
  const beginState = Array(stateSize).fill(BEGIN_TOKEN);
  const cursor = new BitCursor(data);
  let low = 0n;
  let high = 1n;
  let width = 1;
  let state = beginState;
  let chained = seed;
  let sentence = '';
  let text = '';

  while (cursor.remaining() > 0) {
    const budget = cursor.remaining();
    const candidates = candidatesFor(chain, state);
    const [ranges, newLow, newHigh, newWidth] = candidateRanges(low, high, width, candidates, budget);
    low = newLow;
    high = newHigh;
    width = newWidth;
    const peeked = cursor.peek(width);
    const match = ranges.find(([, lo, hi]) => lo <= peeked && peeked <= hi);
    if (!match) {
      throw new Error('No candidate range matched the peeked bits -- this should never happen.');
    }
    const [word, lo, hi] = match;
    low = lo;
    high = hi;
    state = nextState(state, word, beginState);
    if (word === END_TOKEN) {
      text += '\n';
      chained = chainSeed(chained, sentence);
      sentence = '';
    } else {
      const rendered = word + ' ';
      text += rendered;
      sentence += rendered;
    }
    const common = commonLeadingBits(low, high, width);
    if (common) {
      cursor.consume(Math.min(common, cursor.remaining()));
      [low, high, width] = stripTopBits(low, high, width, common);
    }
  }

  if (!stateEquals(state, beginState)) {
    for (const piece of finishSentence(chain, state, beginState, chained)) {
      text += piece;
    }
  }

  return text;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web-demo && npm test -- --watch=false --browsers=ChromeHeadless`
Expected: all tests pass, including all of `markov.spec.ts` and the existing `app.component.spec.ts`.

- [ ] **Step 5: Commit**

```bash
cd web-demo && git add src/app/core/markov.ts src/app/core/prng.ts src/app/core/markov.spec.ts
git commit -m "feat: complete the final web-demo Markov sentence with seed-chained filler words"
```

---

### Task 5: TypeScript — expose a "Seed" field for text mode in the UI

**Files:**
- Modify: `web-demo/src/app/app.component.ts`
- Modify: `web-demo/src/app/app.component.html`

**Interfaces:**
- Consumes: `encodeText(language, data, seed?)` from Task 4.
- Produces: nothing new for later tasks (final task in this plan).

- [ ] **Step 1: Add the `textSeed` signal and wire it into `obfuscate()`**

In `web-demo/src/app/app.component.ts`, add a new signal right after the existing `language`
signal:

```typescript
  readonly message = signal('Hello, airwire! This is a demo message.');
  readonly language = signal<Language>('eng');
  readonly textSeed = signal(this.randomSeed());
```

Change the `obfuscate()` method's `encodeText` call from:

```typescript
      const text = await encodeText(this.language(), bytes);
```

to:

```typescript
      const text = await encodeText(this.language(), bytes, this.textSeed());
```

Add a new method right after `randomizeImageSeed()`:

```typescript
  randomizeTextSeed(): void {
    this.textSeed.set(this.randomSeed());
  }
```

- [ ] **Step 2: Add the "Seed" field to the text-mode template**

In `web-demo/src/app/app.component.html`, insert this block right after the "Language" `<label
class="field">` block (after line 33, before the "Plaintext message" field) in the text-mode
section:

```html
      <label class="field">
        <span>Seed</span>
        <span class="seed-row">
          <input type="number" [ngModel]="textSeed()" (ngModelChange)="textSeed.set($event)" />
          <button type="button" class="secondary" (click)="randomizeTextSeed()">Randomize</button>
        </span>
      </label>
```

- [ ] **Step 3: Run the existing component test suite to check for regressions**

Run: `cd web-demo && npm test -- --watch=false --browsers=ChromeHeadless`
Expected: all tests pass (the smoke tests in `app.component.spec.ts` don't reference the new field,
so they should be unaffected).

- [ ] **Step 4: Manually verify in a browser**

Run: `cd web-demo && npm start`

Then, in the browser at the printed local URL:
1. Confirm the text-mode panel now shows a "Seed" number input with a "Randomize" button, between
   "Language" and "Plaintext message", matching the image mode's equivalent field visually.
2. Type a message long enough to likely need filler (e.g. paste a few sentences of text), click
   Obfuscate, and confirm the "Obfuscated representation" text ends in a new line (visually, the
   text area's content should not trail off mid-word on its last visible line).
3. Click Reveal and confirm the revealed message still matches the original exactly.
4. Click "Randomize" next to the text Seed field, click Obfuscate again with the same message, and
   confirm the obfuscated text is different from the previous run (the filler tail changed).
5. Confirm the literal string `___END__` never appears anywhere in the obfuscated text area.

- [ ] **Step 5: Commit**

```bash
cd web-demo && git add src/app/app.component.ts src/app/app.component.html
git commit -m "feat: expose a Seed field for text-mode obfuscation in the web demo"
```
