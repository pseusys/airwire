"""
Disguises hyperchunk ciphertext as plausible natural-language text, using a frozen per-language
Markov chain (`sources/corpus.py`, `scripts/model.py`, `sources/data/markov_<language>.json`) to
pick which words represent which bits.

This is deliberately *not* built on a general-purpose entropy-coding library. `constriction`
(https://pypi.org/project/constriction/) was tried first -- it's purpose-built for exactly the
determinism this needs (its own docs promise "exactly invertible fixed-point arithmetic") -- but
its public API is shaped for bulk (de)compression of an *already-known* symbol count, not for
"how many words does it take to represent N bytes", which is exactly the question this module
needs answered. Hands-on testing confirmed its `RangeDecoder` cannot safely be asked to keep
decoding past its real input (even generously zero- or randomly-padded) without eventually
corrupting its own internal invariants -- it isn't designed for open-ended, self-terminating
decoding. See [memory/rejected-ideas.md](../../memory/rejected-ideas.md)'s `constriction` entry for
the full story.

Instead, this module implements a small, from-scratch binary arithmetic coder directly on the
frozen model's integer word-transition counts, adapted from Hernan Moraldo's reference design
(https://github.com/hmoraldo/markovTextStego) but using exact integer arithmetic throughout
(cumulative counts scaled by the current range and floor-divided) rather than his floating-point
proportional split -- avoiding floating point anywhere in the encode/decode-critical path
entirely, not just relying on it being safe for scalar operations.

How it works:

- The Markov chain is a bigram model (`state_size=2` in the frozen JSON): a **state** is the last
  two words chosen (or the sentinel `___BEGIN__` pair, initially); each state maps to a list of
  candidate next words with integer corpus-frequency counts. Choosing `___END__` as the next
  "word" ends the current sentence and resets the walk back to the begin state, so a hyperslice's
  worth of bits typically renders as several separate (reserved-token-delimited, see "Known
  limitations" below) sentences rather than one long run-on one.
- Encoding maintains a binary interval `[low, high]` (arbitrary-precision Python integers, not
  fixed-width machine words) that narrows every time a word is chosen, proportionally to that
  word's share of its state's total count -- standard arithmetic coding. The interval is widened
  (more binary digits appended) whenever the current width can't distinguish all of a state's
  candidates, capped at how many *actual* source bits remain -- this cap is what makes the walk
  exactly self-terminating: it never asks for more precision than there is real data left to
  supply it, so it always stops after consuming exactly the right number of bits, no more and no
  less, with no length prefix or sentinel needed on the wire (the hyperchunk header's existing
  `hyperchunk_length` field already carries the target byte count).
- Whenever the interval's leading bits agree between `low` and `high`, those bits are "locked in"
  (can't change no matter what's chosen from here on) and are popped off both the interval and the
  source bit cursor -- the usual arithmetic-coding renormalization step.
- Decoding (recovering the original bytes from a word sequence) runs the identical walk *forwards*
  from the begin state, using each observed word to look up its own committed sub-interval at the
  state that was active when it was chosen, and accumulates the same locked-in bits into the
  output instead of reading them from a cursor. Because it's the same integer arithmetic run in
  the same order, it's byte-for-byte deterministic on any device, with no floating point or ML
  inference anywhere in this path -- the property [memory/wire-protocol.md](../../memory/wire-protocol.md)
  requires.

Known limitations, worth a second look independently of this module:

- Resolved: sentence boundaries used to render as a literal `___END__` token -- correct but an
  obvious tell to a human reader. They're now rendered as a plain `\n` instead: no word in either
  frozen model can ever contain an embedded newline (both are built one Tatoeba sentence per line,
  see `sources/corpus.py`), so `\n` is unambiguous as a boundary marker in a way a period isn't --
  a period *is* a real character inside real vocabulary words (`Mr.`, `Dr.`), which is exactly why
  reinserting boundaries by scanning for periods was tried and rejected; see
  [the design doc](../../docs/superpowers/specs/2026-09-08-markov-boundary-and-filler-design.md)
  for the full evidence. Bonus: a multi-line disguised message is unremarkable, unlike a literal
  `___END__` string ever was.
- Resolved: the very last sentence of a hyperslice's rendered text used to just trail off mid-walk
  whenever the real ciphertext bits ran out before a sentence naturally finished -- unlike every
  sentence before it, which always ends in a real, bit-driven `___END__`/`\n`. `_finish_sentence`
  now completes it with plausible, non-secret filler words (weighted by the same corpus
  frequencies, picked by a seeded PRNG rather than the arithmetic coder) whenever this happens.
  Decode needs no changes for this: it already stops consuming words the moment `length` bytes are
  recovered, so the filler tail is already invisible to it, real or not. See the design doc linked
  above for why the seed is chained across each real sentence's own content
  (`derive_key(seed, sentence_bytes, ...)`) rather than derived from `nonce` alone.
- Resolved: the nonce used to gate only the cosmetic filler tail (previous point);
  every state's candidate order is now also shuffled by a nonce-derived permutation
  (`_permuted_candidates`) before `candidate_ranges` assigns bit-range boundaries to it, so the
  *entire* walk -- not just the filler tail -- depends on the nonce, matching how the image
  disguise's seed already gates its whole texture. Without the right nonce, decode still
  recognizes every word as a valid continuation (membership doesn't depend on order) but recovers
  the wrong bits, failing downstream at the AEAD tag check instead of in this module -- the same
  failure shape a wrong image seed already has. See
  [the design doc](../../docs/superpowers/specs/2026-09-08-markov-seed-broadening-design.md) for
  why this doesn't make the scheme cryptographically secure (it's still deterministic,
  unauthenticated, and unproven) -- it only raises the cost of extracting a payload from "trivial"
  to "brute-force the seed space," the same informal protection level image's seed already gives.
- Resolved: `MARKOV_ENG` and `MARKOV_RUS` each have their own `ChunkEncoding` identifier
  (`hyperchunk.proto`), so the header-driven auto-detection in `unpack_hyperchunk` picks the
  correct language on its own -- no more out-of-band agreement needed than any other encoding
  choice already requires. This also unblocked `sources/handshake.py`'s obfuscation-mode
  derivation, which needs to select a *specific* language/flavor, not just "some Markov text."
"""

import json
from functools import lru_cache
from pathlib import Path
from random import Random
from typing import Dict, Iterator, List, Tuple

from sources.arithmetic import BitAccumulator, BitCursor, candidate_ranges, common_leading_bits, strip_top_bits
from sources.crypto import derive_key
from sources.encodings import ChunkEncoding
from sources.proto import hyperchunk_pb2

_DATA_DIR = Path(__file__).resolve().parent / "data"

BEGIN_TOKEN = "___BEGIN__"
END_TOKEN = "___END__"

_FILLER_SEED_LABEL = b"airwire-markov-filler-seed"
_PERMUTATION_SEED_LABEL = b"airwire-markov-permutation-seed"
_FILLER_SEED_SIZE = 4
_MAX_FILLER_WORDS = 50

_State = Tuple[str, ...]
_Candidates = List[Tuple[str, int]]
_Chain = Dict[_State, _Candidates]


class MarkovModelError(Exception):
    """The frozen per-language model is missing, unreadable, or malformed -- a setup problem,
    not a wire-tamper one, so it's intentionally not a `ValueError` chunking.py would catch."""


@lru_cache(maxsize=None)
def _load_model(language: str) -> Tuple[int, _Chain]:
    path = _DATA_DIR / f"markov_{language}.json"
    if not path.exists():
        raise MarkovModelError(f"No frozen Markov model for language {language!r} at {path}; run `poetry poe train-stego-model` first!")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        state_size = int(raw["state_size"])
        chain_entries = json.loads(raw["chain"])
        chain: _Chain = {tuple(state_words): sorted(candidates.items()) for state_words, candidates in chain_entries}
    except (KeyError, ValueError, TypeError) as error:
        raise MarkovModelError(f"Frozen Markov model at {path} is malformed: {error}!") from error

    return state_size, chain


def _candidates_for(chain: _Chain, state: _State) -> _Candidates:
    try:
        return chain[state]
    except KeyError:
        raise MarkovModelError(f"No transitions recorded for state {state!r}; the frozen model may be truncated!") from None


def _permuted_candidates(chain: _Chain, state: _State, permutation_seed: bytes, cache: Dict[_State, _Candidates]) -> _Candidates:
    """
    Same candidates as `_candidates_for`, but shuffled by a seed derived from `permutation_seed` --
    this is what makes `candidate_ranges`'s bit-range assignment (and therefore every word choice
    in the main walk) genuinely depend on the nonce, not just the cosmetic filler tail. Memoized
    per call via `cache` (never the module-level `_load_model` cache: this depends on the nonce and
    must not leak across calls with different ones).
    """

    cached = cache.get(state)
    if cached is not None:
        return cached
    candidates = _candidates_for(chain, state)
    key = derive_key(permutation_seed, "".join(state).encode("utf-8"), size=8)
    shuffled = list(candidates)
    Random(int.from_bytes(key, "big")).shuffle(shuffled)
    cache[state] = shuffled
    return shuffled


def _next_state(state: _State, word: str, begin_state: _State) -> _State:
    return begin_state if word == END_TOKEN else state[1:] + (word,)


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


_IDENTIFIERS = {
    "eng": hyperchunk_pb2.ChunkEncoding.MARKOV_ENG,
    "rus": hyperchunk_pb2.ChunkEncoding.MARKOV_RUS,
}


class MarkovEncoding(ChunkEncoding):
    def __init__(self, language: str) -> None:
        try:
            self.identifier = _IDENTIFIERS[language]
        except KeyError:
            raise MarkovModelError(f"No wire identifier registered for language {language!r}; supported: {sorted(_IDENTIFIERS)}!") from None
        self.language = language

    def encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]:
        state_size, chain = _load_model(self.language)
        begin_state: _State = (BEGIN_TOKEN,) * state_size
        cursor = BitCursor(data)
        low, high, width = 0, 1, 1
        state = begin_state
        seed = derive_key(nonce, _FILLER_SEED_LABEL, size=_FILLER_SEED_SIZE)
        permutation_seed = derive_key(nonce, _PERMUTATION_SEED_LABEL, size=_FILLER_SEED_SIZE)
        permutation_cache: Dict[_State, _Candidates] = {}
        sentence_words: List[str] = []

        while cursor.remaining() > 0:
            budget = cursor.remaining()
            candidates = _permuted_candidates(chain, state, permutation_seed, permutation_cache)
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

    def decode(self, encoded: bytes, length: int, nonce: bytes) -> bytes:
        state_size, chain = _load_model(self.language)
        begin_state: _State = (BEGIN_TOKEN,) * state_size

        try:
            words = _tokenize(encoded.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise ValueError(f"Markov-encoded chunk payload isn't valid UTF-8: {error}!") from error

        accumulator = BitAccumulator(length)
        low, high, width = 0, 1, 1
        state = begin_state
        permutation_seed = derive_key(nonce, _PERMUTATION_SEED_LABEL, size=_FILLER_SEED_SIZE)
        permutation_cache: Dict[_State, _Candidates] = {}

        for word in words:
            if accumulator.done():
                break
            candidates = _permuted_candidates(chain, state, permutation_seed, permutation_cache)
            ranges, low, high, width = candidate_ranges(low, high, width, candidates, accumulator.remaining())
            match = next(((lo, hi) for w, lo, hi in ranges if w == word), None)
            if match is None:
                raise ValueError(f"{word!r} is not a valid continuation at this point in the Markov walk!")
            low, high = match
            state = _next_state(state, word, begin_state)
            common = common_leading_bits(low, high, width)
            if common:
                accumulator.append(low, width, common)
                low, high, width = strip_top_bits(low, high, width, common)

        return accumulator.finish()


MARKOV_ENG = MarkovEncoding("eng")
MARKOV_RUS = MarkovEncoding("rus")
