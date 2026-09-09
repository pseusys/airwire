/**
 * TypeScript port of core/sources/arithmetic.py -- a small, from-scratch binary arithmetic coder
 * over exact integer arithmetic. See that file's docstring for the full explanation of what this
 * does and why; this is a line-for-line-equivalent reimplementation, not a redesign.
 *
 * Everything here uses `bigint`, not `number`: ranges grow past 2^53 (JS's safe-integer limit)
 * for realistic inputs, and this coder's entire point is exact, lossless integer arithmetic -- the
 * same reason the Python original never touches a float.
 *
 * One deliberate deviation from the Python source: `addDigitsToRange` needs `ceil(log2(a / b))`.
 * Python computes this via `math.log2` on a floating-point division, which is correctly rounded
 * but can, in principle, round the wrong way for a ratio landing extremely close to an exact power
 * of two. `ceilLog2Ratio` below computes the same quantity with exact integer comparisons instead
 * (bit-length estimate, then corrected by direct comparison) -- provably exact, never an
 * approximation, at the cost of no longer being a literal line-for-line port of that one function.
 */

export type Candidate<T> = readonly [T, bigint];
export type CandidateRange<T> = readonly [T, bigint, bigint];

function bitLength(value: bigint): number {
  if (value <= 0n) return 0;
  let bits = 0;
  let remaining = value;
  while (remaining > 0n) {
    remaining >>= 1n;
    bits++;
  }
  return bits;
}

/** Exact integer `ceil(log2(a / b))` for positive bigints -- see module docstring for why this
 * isn't a literal port of the Python original's floating-point version. */
export function ceilLog2Ratio(a: bigint, b: bigint): number {
  if (a <= b) return 0;
  let e = bitLength(a) - bitLength(b);
  if (e < 0) e = 0;
  while (a > b << BigInt(e)) e++;
  while (e > 0 && a <= b << BigInt(e - 1)) e--;
  return e;
}

/** Widen `[low, high]` (a `width`-bit range) with extra binary digits, up to `maxDigits` total,
 * until it has at least `desiredRangeLen` distinct positions -- or as close to that as `maxDigits`
 * allows. */
export function addDigitsToRange(low: bigint, high: bigint, width: number, desiredRangeLen: bigint, maxDigits: number): [bigint, bigint, number] {
  const rangePossibleValues = high - low + 1n;
  if (desiredRangeLen <= rangePossibleValues) {
    return [low, high, width];
  }
  let extra = ceilLog2Ratio(desiredRangeLen, rangePossibleValues);
  if (width + extra > maxDigits) {
    extra = maxDigits - width;
  }
  if (extra <= 0) {
    return [low, high, width];
  }
  const extraBig = BigInt(extra);
  return [low << extraBig, (high << extraBig) | ((1n << extraBig) - 1n), width + extra];
}

/** Subdivide `[low, high]` (a `width`-bit range) among `candidates`, proportionally to their
 * integer weights, growing the range (up to `budget` bits) first if it isn't wide enough to give
 * every candidate at least one position -- candidates that still don't fit even then are simply
 * unreachable at this step. Pure integer (bigint) arithmetic throughout. */
export function candidateRanges<T>(low: bigint, high: bigint, width: number, candidates: readonly Candidate<T>[], budget: number): [CandidateRange<T>[], bigint, bigint, number] {
  const denominator = candidates.reduce((sum, [, weight]) => sum + weight, 0n);
  [low, high, width] = addDigitsToRange(low, high, width, denominator, budget);
  const rangeSize = high - low + 1n;
  const base = low;

  const boundaries: [T, bigint][] = [];
  let cumulative = 0n;
  for (const [candidate, weight] of candidates) {
    cumulative += weight;
    boundaries.push([candidate, (cumulative * rangeSize) / denominator - 1n]);
  }
  const [lastCandidate] = boundaries[boundaries.length - 1];
  boundaries[boundaries.length - 1] = [lastCandidate, rangeSize - 1n]; // force the exact top, guards against floor-division shortfall.

  const result: CandidateRange<T>[] = [];
  let cursor = 0n;
  for (const [candidate, end] of boundaries) {
    if (end >= cursor) {
      result.push([candidate, cursor + base, end + base]);
      cursor = end + 1n;
    }
  }
  return [result, low, high, width];
}

export function commonLeadingBits(low: bigint, high: bigint, width: number): number {
  let count = 0;
  while (width - count >= 1 && ((low >> BigInt(width - count - 1)) & 1n) === ((high >> BigInt(width - count - 1)) & 1n)) {
    count++;
  }
  return count;
}

export function stripTopBits(low: bigint, high: bigint, width: number, n: number): [bigint, bigint, number] {
  if (n >= width) {
    return [0n, 0n, 0];
  }
  const mask = (1n << BigInt(width - n)) - 1n;
  return [low & mask, high & mask, width - n];
}

export function topBits(value: bigint, width: number, n: number): bigint {
  if (n === 0) return 0n;
  return (value >> BigInt(width - n)) & ((1n << BigInt(n)) - 1n);
}

/** Reads a fixed byte buffer as a peekable/consumable bit stream, MSB-first. */
export class BitCursor {
  private value: bigint;
  private readonly total: number;
  private pos = 0;

  constructor(data: Uint8Array) {
    this.total = data.length * 8;
    let value = 0n;
    for (const byte of data) {
      value = (value << 8n) | BigInt(byte);
    }
    this.value = value;
  }

  remaining(): number {
    return this.total - this.pos;
  }

  peek(n: number): bigint {
    if (n === 0) return 0n;
    const shift = BigInt(this.total - this.pos - n);
    return (this.value >> shift) & ((1n << BigInt(n)) - 1n);
  }

  consume(n: number): void {
    this.pos += n;
  }
}

/** The write-side counterpart to `BitCursor`: accumulates decoded bits up to a fixed target byte
 * count, then renders them as bytes. Throws if `finish()` is called before the target is reached
 * -- a short decode means the caller didn't feed it enough candidate selections. */
export class BitAccumulator {
  private value = 0n;
  private bits = 0;
  private readonly targetBytes: number;
  private readonly targetBits: number;

  constructor(targetBytes: number) {
    this.targetBytes = targetBytes;
    this.targetBits = targetBytes * 8;
  }

  remaining(): number {
    return this.targetBits - this.bits;
  }

  done(): boolean {
    return this.bits >= this.targetBits;
  }

  append(value: bigint, width: number, available: number): void {
    const take = Math.min(available, this.remaining());
    this.value = (this.value << BigInt(take)) | topBits(value, width, take);
    this.bits += take;
  }

  finish(): Uint8Array {
    if (this.bits !== this.targetBits) {
      throw new Error(`Only accumulated ${this.bits}/${this.targetBits} bits!`);
    }
    const bytes = new Uint8Array(this.targetBytes);
    let value = this.value;
    for (let i = this.targetBytes - 1; i >= 0; i--) {
      bytes[i] = Number(value & 0xffn);
      value >>= 8n;
    }
    return bytes;
  }
}
