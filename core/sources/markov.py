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
decoding. See [design decision #2](../../docs/design-decisions.md) for the full story.

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
  inference anywhere in this path -- the property [design decision #1](../../docs/design-decisions.md)
  requires.

Known limitations, worth a second look independently of this module:

- The sentence-boundary token is rendered verbatim as `___END__` rather than something that reads
  as ordinary punctuation. Correct and unambiguous, but an obvious tell to a human reader; a nicer
  rendering (e.g. a period) is a follow-up, not attempted here to avoid the risk of it colliding
  with a genuine one-character vocabulary word.
- Only one `MarkovEncoding` instance is registered under the shared `ChunkEncoding.MARKOV`
  identifier for header-driven auto-detection on the receiving end (see `sources/encodings.py`),
  since the wire format doesn't carry a language tag -- both ends must already agree on the
  language out of band, the same way they already agree on the symmetric key. Both `MARKOV_ENG`
  and `MARKOV_RUS` work correctly end to end (`encode_atoms`/`decode` are fully functional for
  either), but only `MARKOV_ENG` is in `sources.encodings._ENCODINGS`, so `unpack_hyperchunk`
  won't automatically pick the Russian model even if that's what was actually used to pack a
  hyperchunk. A real fix needs a wire-visible language selector, not attempted here.
"""

import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from sources.encodings import ChunkEncoding
from sources.proto import hyperchunk_pb2

_DATA_DIR = Path(__file__).resolve().parent / "data"

BEGIN_TOKEN = "___BEGIN__"
END_TOKEN = "___END__"

_State = Tuple[str, ...]
_Candidates = List[Tuple[str, int]]
_Chain = Dict[_State, _Candidates]


class MarkovModelError(Exception):
    """The frozen per-language model is missing, unreadable, or malformed -- a setup problem,
    not a wire-tamper one, so it's intentionally not a `ValueError` chunking.py would catch."""


@lru_cache(maxsize=None)
def _load_model(language: str) -> Tuple[int, _Chain]:
    import json

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


def _next_state(state: _State, word: str, begin_state: _State) -> _State:
    return begin_state if word == END_TOKEN else state[1:] + (word,)


def _add_digits_to_range(low: int, high: int, width: int, desired_range_len: int, max_digits: int) -> Tuple[int, int, int]:
    range_possible_values = high - low + 1
    if desired_range_len <= range_possible_values:
        return low, high, width
    extra = math.ceil(math.log2(desired_range_len / range_possible_values))
    if width + extra > max_digits:
        extra = max_digits - width
    if extra <= 0:
        return low, high, width
    return low << extra, (high << extra) | ((1 << extra) - 1), width + extra


def _word_ranges(low: int, high: int, width: int, candidates: _Candidates, budget: int) -> Tuple[List[Tuple[str, int, int]], int, int, int]:
    """Subdivide `[low, high]` (a `width`-bit range) among `candidates`, proportionally to their
    integer counts, growing the range (up to `budget` bits) first if it isn't wide enough to give
    every candidate at least one position -- candidates that still don't fit even then are simply
    unreachable at this step. Pure integer arithmetic throughout: no floating point anywhere."""

    denominator = sum(count for _, count in candidates)
    low, high, width = _add_digits_to_range(low, high, width, denominator, budget)
    range_size = high - low + 1
    base = low

    boundaries: List[Tuple[str, int]] = []
    cumulative = 0
    for word, count in candidates:
        cumulative += count
        boundaries.append((word, (cumulative * range_size) // denominator - 1))
    last_word, _ = boundaries[-1]
    boundaries[-1] = (last_word, range_size - 1)  # force the exact top, guards against floor-division shortfall.

    result = []
    cursor = 0
    for word, end in boundaries:
        if end >= cursor:
            result.append((word, cursor + base, end + base))
            cursor = end + 1
    return result, low, high, width


def _common_leading_bits(low: int, high: int, width: int) -> int:
    count = 0
    while width - count >= 1 and (low >> (width - count - 1)) & 1 == (high >> (width - count - 1)) & 1:
        count += 1
    return count


def _strip_top_bits(low: int, high: int, width: int, n: int) -> Tuple[int, int, int]:
    if n >= width:
        return 0, 0, 0
    mask = (1 << (width - n)) - 1
    return low & mask, high & mask, width - n


def _top_bits(value: int, width: int, n: int) -> int:
    if n == 0:
        return 0
    return (value >> (width - n)) & ((1 << n) - 1)


class _BitCursor:
    """Reads a fixed byte buffer as a peekable/consumable bit stream, MSB-first."""

    def __init__(self, data: bytes) -> None:
        self._value = int.from_bytes(data, "big")
        self._total = len(data) * 8
        self._pos = 0

    def remaining(self) -> int:
        return self._total - self._pos

    def peek(self, n: int) -> int:
        if n == 0:
            return 0
        shift = self._total - self._pos - n
        return (self._value >> shift) & ((1 << n) - 1)

    def consume(self, n: int) -> None:
        self._pos += n


class MarkovEncoding(ChunkEncoding):
    identifier = hyperchunk_pb2.ChunkEncoding.MARKOV

    def __init__(self, language: str) -> None:
        self.language = language

    def encode_atoms(self, data: bytes) -> Iterator[bytes]:
        state_size, chain = _load_model(self.language)
        begin_state: _State = (BEGIN_TOKEN,) * state_size
        cursor = _BitCursor(data)
        low, high, width = 0, 1, 1
        state = begin_state

        while cursor.remaining() > 0:
            budget = cursor.remaining()
            candidates = _candidates_for(chain, state)
            ranges, low, high, width = _word_ranges(low, high, width, candidates, budget)
            peeked = cursor.peek(width)
            word, low, high = next((w, lo, hi) for w, lo, hi in ranges if lo <= peeked <= hi)
            yield (word + " ").encode("utf-8")
            state = _next_state(state, word, begin_state)
            common = _common_leading_bits(low, high, width)
            if common:
                cursor.consume(min(common, cursor.remaining()))
                low, high, width = _strip_top_bits(low, high, width, common)

    def decode(self, encoded: bytes, length: int) -> bytes:
        state_size, chain = _load_model(self.language)
        begin_state: _State = (BEGIN_TOKEN,) * state_size

        try:
            words = encoded.decode("utf-8").split()
        except UnicodeDecodeError as error:
            raise ValueError(f"Markov-encoded chunk payload isn't valid UTF-8: {error}!") from error

        target_bits = length * 8
        out_value = 0
        out_bits = 0
        low, high, width = 0, 1, 1
        state = begin_state

        for word in words:
            if out_bits >= target_bits:
                break
            budget = target_bits - out_bits
            candidates = _candidates_for(chain, state)
            ranges, low, high, width = _word_ranges(low, high, width, candidates, budget)
            match = next(((lo, hi) for w, lo, hi in ranges if w == word), None)
            if match is None:
                raise ValueError(f"{word!r} is not a valid continuation at this point in the Markov walk!")
            low, high = match
            state = _next_state(state, word, begin_state)
            common = _common_leading_bits(low, high, width)
            if common:
                take = min(common, target_bits - out_bits)
                out_value = (out_value << take) | _top_bits(low, width, take)
                out_bits += take
                low, high, width = _strip_top_bits(low, high, width, common)

        if out_bits != target_bits:
            raise ValueError(f"Markov-encoded chunk payload only decodes to {out_bits}/{target_bits} bits!")
        return out_value.to_bytes(length, "big") if length else b""


MARKOV_ENG = MarkovEncoding("eng")
MARKOV_RUS = MarkovEncoding("rus")
