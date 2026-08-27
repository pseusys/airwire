"""
A small, from-scratch binary arithmetic coder over exact integer arithmetic -- no floating point,
no external entropy-coding library, anywhere in this module. Shared by `sources/markov.py` and
`sources/texture.py`, which both need the same primitive: repeatedly choose among a list of
integer-weighted candidates, driven by a fixed number of secret bits, in a way that is exactly
invertible and self-terminating -- consuming precisely as many bits as the caller says are
available, no length prefix or sentinel required on the wire.

See `sources/markov.py`'s docstring for why this is hand-rolled rather than built on a
general-purpose library (`constriction` was tried first and didn't fit); this module is that
design, factored out once a second consumer (`sources/texture.py`) needed the identical mechanism.
"""

import math
from typing import List, Tuple, TypeVar

Candidate = TypeVar("Candidate")


def add_digits_to_range(low: int, high: int, width: int, desired_range_len: int, max_digits: int) -> Tuple[int, int, int]:
    """Widen `[low, high]` (a `width`-bit range) with extra binary digits, up to `max_digits`
    total, until it has at least `desired_range_len` distinct positions -- or as close to that as
    `max_digits` allows."""

    range_possible_values = high - low + 1
    if desired_range_len <= range_possible_values:
        return low, high, width
    extra = math.ceil(math.log2(desired_range_len / range_possible_values))
    if width + extra > max_digits:
        extra = max_digits - width
    if extra <= 0:
        return low, high, width
    return low << extra, (high << extra) | ((1 << extra) - 1), width + extra


def candidate_ranges(low: int, high: int, width: int, candidates: List[Tuple[Candidate, int]], budget: int) -> Tuple[List[Tuple[Candidate, int, int]], int, int, int]:
    """Subdivide `[low, high]` (a `width`-bit range) among `candidates`, proportionally to their
    integer weights, growing the range (up to `budget` bits) first if it isn't wide enough to give
    every candidate at least one position -- candidates that still don't fit even then are simply
    unreachable at this step. Pure integer arithmetic throughout: no floating point anywhere."""

    denominator = sum(weight for _, weight in candidates)
    low, high, width = add_digits_to_range(low, high, width, denominator, budget)
    range_size = high - low + 1
    base = low

    boundaries: List[Tuple[Candidate, int]] = []
    cumulative = 0
    for candidate, weight in candidates:
        cumulative += weight
        boundaries.append((candidate, (cumulative * range_size) // denominator - 1))
    last_candidate, _ = boundaries[-1]
    boundaries[-1] = (last_candidate, range_size - 1)  # force the exact top, guards against floor-division shortfall.

    result = []
    cursor = 0
    for candidate, end in boundaries:
        if end >= cursor:
            result.append((candidate, cursor + base, end + base))
            cursor = end + 1
    return result, low, high, width


def common_leading_bits(low: int, high: int, width: int) -> int:
    count = 0
    while width - count >= 1 and (low >> (width - count - 1)) & 1 == (high >> (width - count - 1)) & 1:
        count += 1
    return count


def strip_top_bits(low: int, high: int, width: int, n: int) -> Tuple[int, int, int]:
    if n >= width:
        return 0, 0, 0
    mask = (1 << (width - n)) - 1
    return low & mask, high & mask, width - n


def top_bits(value: int, width: int, n: int) -> int:
    if n == 0:
        return 0
    return (value >> (width - n)) & ((1 << n) - 1)


class BitCursor:
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


class BitAccumulator:
    """The write-side counterpart to `BitCursor`: accumulates decoded bits up to a fixed target
    byte count, then renders them as bytes. Raises if `finish()` is called before the target is
    reached -- a short decode means the caller didn't feed it enough candidate selections."""

    def __init__(self, target_bytes: int) -> None:
        self._value = 0
        self._bits = 0
        self._target_bytes = target_bytes
        self._target_bits = target_bytes * 8

    def remaining(self) -> int:
        return self._target_bits - self._bits

    def done(self) -> bool:
        return self._bits >= self._target_bits

    def append(self, value: int, width: int, available: int) -> None:
        take = min(available, self.remaining())
        self._value = (self._value << take) | top_bits(value, width, take)
        self._bits += take

    def finish(self) -> bytes:
        if self._bits != self._target_bits:
            raise ValueError(f"Only accumulated {self._bits}/{self._target_bits} bits!")
        return self._value.to_bytes(self._target_bytes, "big") if self._target_bytes else b""
