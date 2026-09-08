/**
 * A small, self-contained seeded PRNG for the image-texture generators in `textures.ts`.
 *
 * Deliberately *not* a port of NumPy's `default_rng` (PCG64), unlike `arithmetic.ts`/`markov.ts`,
 * which are bit-exact ports of their Python counterparts. The real `sources/textures.py` uses
 * PCG64 so that two independently-built *protocol* clients regenerate an identical source texture
 * from the same seed (see that file's docstring) -- a real, load-bearing requirement there. This
 * demo has no such requirement: it only needs *this page* to regenerate the same texture from the
 * same seed for its own obfuscate/reveal round trip, so a much simpler generator (mulberry32) is
 * enough, at the cost of this page's synthesized images not matching what the real Python encoder
 * would produce for the same seed. Flagged here so it isn't mistaken for a cross-platform claim.
 */
export class Prng {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  /** Uniform in [0, 1). */
  next(): number {
    this.state |= 0;
    this.state = (this.state + 0x6d2b79f5) | 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  /** Uniform integer in [min, max). */
  nextInt(min: number, max: number): number {
    return min + Math.floor(this.next() * (max - min));
  }

  /** Uniform float in [min, max). */
  nextFloat(min: number, max: number): number {
    return min + this.next() * (max - min);
  }

  /** Standard-ish normal via Box-Muller, scaled to (mean, std). */
  nextNormal(mean: number, std: number): number {
    const u1 = Math.max(this.next(), Number.EPSILON);
    const u2 = this.next();
    const z0 = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    return mean + z0 * std;
  }
}

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
