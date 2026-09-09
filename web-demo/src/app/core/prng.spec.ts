import { chainSeed, Prng } from './prng';

describe('Prng', () => {
  it('is deterministic for the same seed', () => {
    const a = new Prng(42);
    const b = new Prng(42);
    const drawsA = Array.from({ length: 10 }, () => a.next());
    const drawsB = Array.from({ length: 10 }, () => b.next());
    expect(drawsA).toEqual(drawsB);
  });

  it('differs across seeds', () => {
    const a = new Prng(1);
    const b = new Prng(2);
    expect(a.next()).not.toBe(b.next());
  });

  it('next() stays within [0, 1) across many draws', () => {
    const rng = new Prng(7);
    for (let i = 0; i < 1000; i++) {
      const value = rng.next();
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
  });

  it('nextInt(min, max) stays within [min, max) across many draws', () => {
    const rng = new Prng(7);
    for (let i = 0; i < 1000; i++) {
      const value = rng.nextInt(5, 15);
      expect(Number.isInteger(value)).toBeTrue();
      expect(value).toBeGreaterThanOrEqual(5);
      expect(value).toBeLessThan(15);
    }
  });

  it('nextFloat(min, max) stays within [min, max) across many draws', () => {
    const rng = new Prng(7);
    for (let i = 0; i < 1000; i++) {
      const value = rng.nextFloat(-2, 2);
      expect(value).toBeGreaterThanOrEqual(-2);
      expect(value).toBeLessThan(2);
    }
  });

  it('nextNormal(mean, std) is centered roughly on mean over many draws', () => {
    const rng = new Prng(7);
    const draws = Array.from({ length: 2000 }, () => rng.nextNormal(10, 1));
    const mean = draws.reduce((sum, value) => sum + value, 0) / draws.length;
    expect(Math.abs(mean - 10)).toBeLessThan(0.5);
  });
});

describe('chainSeed', () => {
  it('is deterministic for the same seed and text', () => {
    expect(chainSeed(42, 'hello')).toBe(chainSeed(42, 'hello'));
  });

  it('differs when the seed differs', () => {
    expect(chainSeed(1, 'hello')).not.toBe(chainSeed(2, 'hello'));
  });

  it('differs when the text differs', () => {
    expect(chainSeed(42, 'hello')).not.toBe(chainSeed(42, 'goodbye'));
  });

  it('always returns an unsigned 32-bit integer', () => {
    const result = chainSeed(-1, 'some text with unicode: éè');
    expect(Number.isInteger(result)).toBeTrue();
    expect(result).toBeGreaterThanOrEqual(0);
    expect(result).toBeLessThanOrEqual(0xffffffff);
  });
});
