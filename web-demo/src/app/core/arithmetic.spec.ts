import { addDigitsToRange, BitAccumulator, BitCursor, Candidate, candidateRanges, ceilLog2Ratio, commonLeadingBits, stripTopBits, topBits } from './arithmetic';

describe('ceilLog2Ratio', () => {
  it('returns 0 when a <= b', () => {
    expect(ceilLog2Ratio(1n, 1n)).toBe(0);
    expect(ceilLog2Ratio(1n, 5n)).toBe(0);
  });

  it('is exact at powers of two, not off by one either side', () => {
    expect(ceilLog2Ratio(2n, 1n)).toBe(1); // log2(2) = 1 exactly
    expect(ceilLog2Ratio(4n, 1n)).toBe(2); // log2(4) = 2 exactly
    expect(ceilLog2Ratio(8n, 1n)).toBe(3); // log2(8) = 3 exactly -- the case a naive float log2 can round wrong on
  });

  it('rounds non-exact ratios up', () => {
    expect(ceilLog2Ratio(3n, 1n)).toBe(2); // log2(3) ~ 1.585
    expect(ceilLog2Ratio(5n, 1n)).toBe(3); // log2(5) ~ 2.322
    expect(ceilLog2Ratio(9n, 2n)).toBe(3); // 9/2 = 4.5, log2(4.5) ~ 2.17
  });

  it('handles large bigints past the float53 safe-integer range', () => {
    const a = (1n << 100n) + 1n;
    const b = 1n << 90n;
    expect(ceilLog2Ratio(a, b)).toBe(11); // just over 2^10 wider than b
  });
});

describe('addDigitsToRange', () => {
  it('does not widen when the range already has enough positions', () => {
    const [low, high, width] = addDigitsToRange(0n, 7n, 3, 8n, 32);
    expect([low, high, width]).toEqual([0n, 7n, 3]);
  });

  it('widens exactly enough to cover desiredRangeLen', () => {
    const [low, high, width] = addDigitsToRange(0n, 1n, 1, 10n, 32);
    expect(high - low + 1n >= 10n).toBeTrue();
    expect(width).toBeGreaterThan(1);
  });

  it('never widens past maxDigits, even if that leaves the range still too narrow', () => {
    const [low, high, width] = addDigitsToRange(0n, 1n, 1, 1000000n, 4);
    expect(width).toBe(4);
    expect(high - low + 1n).toBe(16n);
  });
});

describe('candidateRanges', () => {
  it('partitions [low, high] proportionally to weight, contiguously and with no gaps', () => {
    const candidates: Candidate<string>[] = [
      ['a', 1n],
      ['b', 2n],
      ['c', 1n],
    ];
    const [ranges, low, high] = candidateRanges(0n, 0n, 0, candidates, 8);
    expect(ranges.length).toBe(3);
    expect(ranges[0][1]).toBe(low); // first range starts exactly at low
    expect(ranges[ranges.length - 1][2]).toBe(high); // last range ends exactly at high
    for (let i = 1; i < ranges.length; i++) {
      expect(ranges[i][1]).toBe(ranges[i - 1][2] + 1n); // no gap, no overlap
    }
    // Heavier-weighted candidate gets a strictly wider sub-range than an equal-or-lighter one.
    const widthOf = (r: (typeof ranges)[number]) => r[2] - r[1] + 1n;
    expect(widthOf(ranges[1]) > widthOf(ranges[0])).toBeTrue();
  });

  it('drops a candidate that cannot fit any position once the range is as wide as the budget allows', () => {
    // A budget of 0 extra bits leaves [low, high] = [0, 0] (a single position) -- only one of
    // these three equally-weighted candidates can occupy it.
    const candidates: Candidate<string>[] = [
      ['a', 1n],
      ['b', 1n],
      ['c', 1n],
    ];
    const [ranges] = candidateRanges(0n, 0n, 0, candidates, 0);
    expect(ranges.length).toBe(1);
  });
});

describe('commonLeadingBits / stripTopBits / topBits', () => {
  it('finds the shared leading bits between low and high', () => {
    // 0b1010 and 0b1011 share their top 3 bits.
    expect(commonLeadingBits(0b1010n, 0b1011n, 4)).toBe(3);
  });

  it('finds zero common leading bits when low/high disagree on the very first bit', () => {
    expect(commonLeadingBits(0b0111n, 0b1000n, 4)).toBe(0);
  });

  it('strips exactly n top bits from both low and high, narrowing width', () => {
    const [low, high, width] = stripTopBits(0b1010n, 0b1011n, 4, 3);
    expect(width).toBe(1);
    expect(low).toBe(0b0n);
    expect(high).toBe(0b1n);
  });

  it('extracts the top n bits of a value at a given width', () => {
    expect(topBits(0b1011n, 4, 2)).toBe(0b10n);
    expect(topBits(0b1011n, 4, 0)).toBe(0n);
    expect(topBits(0b1011n, 4, 4)).toBe(0b1011n);
  });
});

describe('BitCursor', () => {
  it('peeks and consumes MSB-first without disturbing unconsumed bits', () => {
    const cursor = new BitCursor(new Uint8Array([0b10110100, 0b01010101]));
    expect(cursor.remaining()).toBe(16);
    expect(cursor.peek(4)).toBe(0b1011n);
    cursor.consume(4);
    expect(cursor.remaining()).toBe(12);
    expect(cursor.peek(4)).toBe(0b0100n);
    cursor.consume(4);
    expect(cursor.peek(8)).toBe(0b01010101n);
    cursor.consume(8);
    expect(cursor.remaining()).toBe(0);
  });

  it('peek(0) always returns 0 without consuming anything', () => {
    const cursor = new BitCursor(new Uint8Array([0xff]));
    expect(cursor.peek(0)).toBe(0n);
    expect(cursor.remaining()).toBe(8);
  });
});

describe('BitAccumulator', () => {
  it('reassembles bytes from the exact chunks a BitCursor would have peeked', () => {
    const accumulator = new BitAccumulator(2);
    accumulator.append(0b1011n, 4, 4);
    accumulator.append(0b0100n, 4, 4);
    accumulator.append(0b01010101n, 8, 8);
    expect(accumulator.done()).toBeTrue();
    expect(accumulator.finish()).toEqual(new Uint8Array([0b10110100, 0b01010101]));
  });

  it('throws if finish() is called before enough bits were accumulated', () => {
    const accumulator = new BitAccumulator(2);
    accumulator.append(0b1011n, 4, 4);
    expect(accumulator.done()).toBeFalse();
    expect(() => accumulator.finish()).toThrow();
  });

  it('append() only ever takes as many bits as remaining(), even if offered more', () => {
    const accumulator = new BitAccumulator(1); // target: 8 bits total
    accumulator.append(0b111111n, 6, 6);
    accumulator.append(0b11n, 2, 4); // offers 4, but only 2 remain
    expect(accumulator.finish()).toEqual(new Uint8Array([0b11111111]));
  });
});

describe('round trip: BitCursor -> BitAccumulator reconstructs arbitrary bytes', () => {
  it('reconstructs random payloads for a variety of chunk widths', () => {
    for (const size of [0, 1, 5, 13, 37]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const cursor = new BitCursor(data);
      const accumulator = new BitAccumulator(size);
      const chunkWidth = 3;
      while (cursor.remaining() > 0) {
        const take = Math.min(chunkWidth, cursor.remaining());
        const value = cursor.peek(take);
        cursor.consume(take);
        accumulator.append(value, take, take);
      }
      expect(accumulator.finish()).toEqual(data);
    }
  });
});
