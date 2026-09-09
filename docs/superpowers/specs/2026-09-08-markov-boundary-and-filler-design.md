# Markov text disguise: newline sentence boundaries + seed-chained sentence completion — design

> **Status:** approved design, ready for implementation planning.
> **Relationship to other docs:** refines the Markov-chain text disguise encoding from
> [`memory/wire-protocol.md`](../../../memory/wire-protocol.md)
> ([`core/sources/markov.py`](../../../core/sources/markov.py)). Resolves that decision's own
> "Known limitations" note about `___END__` being rendered verbatim, and closes a related gap
> (the final sentence of a hyperslice's text is always cut off mid-walk) that wasn't previously
> recorded as a limitation at all. Doesn't touch `sources/synthesis.py`/`sources/textures.py`
> (image disguise already has its own seed handling) or the `ChunkEncoding`/`chunking.py` wire
> contract (the `nonce` parameter this design uses already exists there).

## Purpose

Two independent, cosmetic-but-real tells currently make Markov-disguised text distinguishable from
plausible prose:

1. Sentence boundaries are rendered as a literal `___END__` token — obviously not natural language.
2. The very last sentence of a hyperslice's rendered text is whatever fragment happens to be
   mid-walk when the real ciphertext bits run out — it never has an ending, unlike every sentence
   before it.

This design fixes both, without changing the wire format, the `ChunkEncoding` interface, or
anything on the decode side beyond how it splits rendered text into words.

## Rejected approach, recorded for the record

The natural first idea — treat the sentence-final period that (most) real sentences already end
with as the boundary signal, drop the explicit token entirely, and reinsert it at decode time by
scanning for periods — was checked against both frozen models
([`markov_eng.json`](../../../core/sources/data/markov_eng.json),
[`markov_rus.json`](../../../core/sources/data/markov_rus.json)) and rejected:

- English: 33 Markov states end in a real period (`Mr.`, `Mrs.`, `Dr.`, `Mt.`, `Ms.`) where
  `___END__` is never offered as a continuation — always followed by a real word, never a sentence
  break. One state where `___END__` *is* offered ends in `:`, not a period.
- Russian: 195 states end in a literal period with `___END__` not offered at all (dialogue
  attribution mid-sentence, e.g. `сказала мама.` continuing into more text), plus 13 END-reachable
  states ending in `»`/`:`/`‽`.

A period is neither necessary nor sufficient for "this is where `___END__` was chosen," in either
language's actual training data. Guessing a boundary at an abbreviation would desync the decoder's
Markov walk from a state the encoder was never in — a hard decode failure, not a cosmetic
imperfection.

## Component 1 — newline-rendered sentence boundaries

**Why it's safe where periods weren't:** every token in both frozen models was checked and *none*
contain an embedded `\n`/`\r`, and this holds structurally, not by luck —
[`corpus.py`](../../../core/sources/corpus.py) caches each Tatoeba sentence as one line, and
`markovify` tokenizes each line's words independently, so the vocabulary and the newline character
live in permanently disjoint spaces. No abbreviation, quote, or future retrain can introduce a word
containing `\n`. It's also better camouflage, not just a safer internal format: a multi-line text
message is completely unremarkable, unlike a literal `___END__` string.

**Encode side** ([`MarkovEncoding.encode_atoms`](../../../core/sources/markov.py#L131)): when the
chosen word is `END_TOKEN`, yield `"\n"` instead of `"___END__ "`. Every other word is rendered as
today (`word + " "`).

**Decode side** ([`MarkovEncoding.decode`](../../../core/sources/markov.py#L151)): the current
`encoded.decode("utf-8").split()` must change — Python's default `.split()` treats `\n` and `" "`
identically, which would silently destroy the boundary signal it's supposed to carry. Decode needs
to split into lines first, then words within each line, reintroducing a synthetic `END_TOKEN` at
each line break before continuing the walk — the walk logic itself (`_candidates_for`,
`_next_state`, the accumulator bookkeeping) is unchanged.

## Component 2 — seed-chained completion of the final sentence

**Decode needs no changes for this part.** `decode` already stops the moment
[`accumulator.done()`](../../../core/sources/arithmetic.py#L119-L121) is true — once `length` bytes
are recovered it never looks at another word. Anything encoded after the real payload ends is
already invisible to the decoder today. This design only changes `encode_atoms`.

**Encode side gains two phases:**

1. **Real phase (unchanged arithmetic coding).** While real ciphertext bits remain, encode exactly
   as today. Additionally, track a running `seed`, starting from
   `derive_key(nonce, "airwire-markov-filler-seed", size=4)` (`derive_key` is the existing
   BLAKE2b-based primitive in [`sources/crypto.py`](../../../core/sources/crypto.py#L30) — a plain,
   public derivation, which is fine here since the rendered sentence text is exactly what travels
   on the wire in the clear, nothing about it is secret). Every time a sentence completes (the walk
   returns to `begin_state`, i.e. an `END_TOKEN` was actually chosen), chain the seed forward:
   `seed = derive_key(seed, sentence_bytes, size=4)`, where `sentence_bytes` is the exact rendered
   bytes of the sentence just completed. This is the CBC-like step — each sentence's own content
   folds into the seed the next one (or the eventual filler) will be derived from.
2. **Filler phase (new), only entered if real bits run out mid-sentence.** If `cursor.remaining()`
   reaches 0 while `state != begin_state`, switch from the arithmetic coder to a `random.Random`
   instance seeded from the current chained `seed` (as an int, same
   `int.from_bytes(..., "big")` conversion `sources/synthesis.py` already uses for its own seed).
   Continue the *same* Markov walk from the *same* in-progress `state`, but choose each next word by
   weighted random draw over `_candidates_for(chain, state)` (weights = corpus frequency, so the
   completion still reads as plausible language) instead of consuming ciphertext bits. Keep drawing
   from that one `random.Random` instance — its own evolving internal state is what "chains" the
   filler words together, no further `derive_key` calls needed here. Stop the instant `END_TOKEN` is
   drawn (state returns to `begin_state`), which renders as `"\n"` exactly like a real sentence
   ending, then end the generator.

**Bound on the filler loop:** cap it at a generous fixed word count (e.g. 50 — the training corpora
are short, conversational Tatoeba sentences per `corpus.py`'s own docstring, so this is well above
any real sentence length). Exceeding the cap raises `MarkovModelError` — a frozen-model/setup
problem by the existing taxonomy in `markov.py`, not a `ValueError` wire-tamper case — rather than
looping indefinitely on a pathological state.

**Edge case:** if the real bits run out exactly when `state == begin_state` already (the last real
sentence happened to complete exactly as data ended), the filler phase is skipped entirely — nothing
needs completing.

## Data flow summary

```
encode_atoms(data, nonce):
    seed = derive_key(nonce, "airwire-markov-filler-seed", size=4)
    real arithmetic-coding walk, as today, EXCEPT:
        - render END_TOKEN as "\n"
        - on each sentence completion: seed = derive_key(seed, sentence_bytes, size=4)
    when cursor exhausted:
        if state == begin_state: done
        else: seed the fallback generator from seed, weighted-random-walk the SAME chain/state
              until END_TOKEN drawn (bounded), render it as "\n", done

decode(encoded, length, nonce):
    split into lines, then words per line (only change from today)
    walk exactly as today; already stops via accumulator.done(), ignoring anything
    (including the whole filler phase) once `length` bytes are recovered
```

## Error handling

- Filler-loop cap exceeded → `MarkovModelError` (setup/model problem).
- Everything else already covered by existing error handling: malformed/missing model
  (`MarkovModelError`), invalid UTF-8 or unrecognized word during decode (`ValueError`), tamper
  detection remains the outer AEAD tag's job, unchanged.

## Testing

- Existing round-trip tests ([`test_markov.py`](../../../core/tests/test_markov.py)) must keep
  passing unchanged in shape, but now exercise the filler phase whenever a sample's length doesn't
  happen to land exactly on a sentence boundary — worth asserting explicitly for at least one
  sample per language that the rendered text contains a completed final sentence (ends in `\n`)
  even though the payload length wasn't chosen to make that happen naturally.
- Determinism test (same `data` + `nonce` → identical output across two calls) must keep holding
  with the filler phase included — true by construction, since `random.Random(seed_int)` is seeded
  deterministically from `nonce` and the real sentence content, not from external entropy.
- New test: two different nonces over the *same* data produce different filler completions (confirms
  the seed is actually doing something, not just present in the signature like today).
- New test: filler-loop cap — a constructed pathological chain (test-only fixture) that never
  reaches `END_TOKEN` raises `MarkovModelError` rather than hanging.
- Decode-side line/word splitting: a rendered blob with an embedded real `\n` mid-payload correctly
  resets the walk state, and a payload with no filler needed (exact sentence-boundary length)
  round-trips with no trailing content at all.

## Risks / open unknowns

- Exact filler-loop cap constant and `derive_key` label/size choices above are reasonable defaults,
  not load-bearing design decisions — fine to tune during implementation.
- Not measured yet: how often real-world hyperslice lengths actually land mid-sentence (i.e. how
  often the filler phase triggers at all in practice). Doesn't block implementation either way,
  since both the triggered and skipped paths are already specified.
