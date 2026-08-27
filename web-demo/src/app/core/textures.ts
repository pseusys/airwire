/**
 * TypeScript port of core/sources/textures.py's four procedural texture generators -- see that
 * file's docstring for what each one is meant to look like and why. Ported algorithm-for-algorithm
 * (same math, same structure), but seeded by `Prng` (see prng.ts) rather than NumPy's PCG64 -- so
 * a given seed produces a *different* (but still fully deterministic, still reproducible within
 * this page) texture than the real Python generator would. See prng.ts for why that's an
 * acceptable, deliberate simplification for this demo.
 */

import { Prng } from './prng';

export interface Texture {
  readonly size: number;
  /** Row-major RGB, no alpha: `data[(y * size + x) * 3 + channel]`. */
  readonly data: Uint8Array;
}

function clampByte(value: number): number {
  return Math.trunc(Math.max(0, Math.min(255, value)));
}

export function valueNoise(size: number, seed: number, cell = 8): Texture {
  const rng = new Prng(seed);
  const gridSize = Math.floor(size / cell) + 2;
  const grid = new Float64Array(gridSize * gridSize * 3);
  for (let i = 0; i < grid.length; i++) grid[i] = rng.nextInt(0, 256);
  const gridAt = (yy: number, xx: number, c: number) => grid[(yy * gridSize + xx) * 3 + c];

  const data = new Uint8Array(size * size * 3);
  for (let y = 0; y < size; y++) {
    const gy = y / cell;
    const y0 = Math.floor(gy);
    const fy = gy - y0;
    for (let x = 0; x < size; x++) {
      const gx = x / cell;
      const x0 = Math.floor(gx);
      const fx = gx - x0;
      for (let c = 0; c < 3; c++) {
        const top = gridAt(y0, x0, c) * (1 - fx) + gridAt(y0, x0 + 1, c) * fx;
        const bot = gridAt(y0 + 1, x0, c) * (1 - fx) + gridAt(y0 + 1, x0 + 1, c) * fx;
        data[(y * size + x) * 3 + c] = clampByte(top * (1 - fy) + bot * fy);
      }
    }
  }
  return { size, data };
}

export function voronoi(size: number, seed: number, nCells = 40): Texture {
  const rng = new Prng(seed);
  const points: [number, number][] = [];
  for (let i = 0; i < nCells; i++) points.push([rng.nextInt(0, size), rng.nextInt(0, size)]);
  const colors: [number, number, number][] = [];
  for (let i = 0; i < nCells; i++) colors.push([rng.nextInt(40, 256), rng.nextInt(40, 256), rng.nextInt(40, 256)]);

  const data = new Uint8Array(size * size * 3);
  const normFactor = size / Math.sqrt(nCells);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let nearestIdx = 0;
      let nearestDistSq = Infinity;
      for (let i = 0; i < nCells; i++) {
        const dy = y - points[i][0];
        const dx = x - points[i][1];
        const distSq = dy * dy + dx * dx;
        if (distSq < nearestDistSq) {
          nearestDistSq = distSq;
          nearestIdx = i;
        }
      }
      const shade = 1.0 - 0.35 * Math.max(0, Math.min(1, Math.sqrt(nearestDistSq) / normFactor));
      const [r, g, b] = colors[nearestIdx];
      const idx = (y * size + x) * 3;
      data[idx] = clampByte(r * shade);
      data[idx + 1] = clampByte(g * shade);
      data[idx + 2] = clampByte(b * shade);
    }
  }
  return { size, data };
}

export function reactionDiffusion(size: number, seed: number, steps = 3000): Texture {
  const rng = new Prng(seed);
  const diffusionU = 0.16;
  const diffusionV = 0.08;
  const feed = 0.06;
  const kill = 0.062;
  const n = size * size;
  let u = new Float64Array(n).fill(1);
  let v = new Float64Array(n).fill(0);

  const wrap = (i: number) => ((i % size) + size) % size;
  const at = (y: number, x: number) => wrap(y) * size + wrap(x);

  for (let blob = 0; blob < 8; blob++) {
    const eighth = Math.floor(size / 8);
    const cy = rng.nextInt(eighth, size - eighth);
    const cx = rng.nextInt(eighth, size - eighth);
    const radius = Math.floor(size / 10);
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        if ((y - cy) ** 2 + (x - cx) ** 2 < radius * radius) {
          v[y * size + x] = 1.0;
          u[y * size + x] = 0.5;
        }
      }
    }
  }
  for (let i = 0; i < n; i++) v[i] += rng.nextNormal(0, 0.02);

  function laplacianInto(z: Float64Array, out: Float64Array): void {
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const center = z[y * size + x];
        const orthogonal = z[at(y - 1, x)] + z[at(y + 1, x)] + z[at(y, x - 1)] + z[at(y, x + 1)];
        const diagonal = z[at(y - 1, x - 1)] + z[at(y - 1, x + 1)] + z[at(y + 1, x - 1)] + z[at(y + 1, x + 1)];
        out[y * size + x] = -center + 0.2 * orthogonal + 0.05 * diagonal;
      }
    }
  }

  const lapU = new Float64Array(n);
  const lapV = new Float64Array(n);
  const nextU = new Float64Array(n);
  const nextV = new Float64Array(n);
  for (let step = 0; step < steps; step++) {
    laplacianInto(u, lapU);
    laplacianInto(v, lapV);
    for (let i = 0; i < n; i++) {
      const reaction = u[i] * v[i] * v[i];
      nextU[i] = u[i] + diffusionU * lapU[i] - reaction + feed * (1 - u[i]);
      nextV[i] = v[i] + diffusionV * lapV[i] + reaction - (feed + kill) * v[i];
    }
    u.set(nextU);
    v.set(nextV);
  }

  let vMin = Infinity;
  let vMax = -Infinity;
  for (let i = 0; i < n; i++) {
    if (v[i] < vMin) vMin = v[i];
    if (v[i] > vMax) vMax = v[i];
  }
  const data = new Uint8Array(n * 3);
  for (let i = 0; i < n; i++) {
    const gray = Math.max(0, Math.min(255, ((v[i] - vMin) / (vMax - vMin + 1e-9)) * 255));
    data[i * 3] = clampByte(255 - gray);
    data[i * 3 + 1] = clampByte(gray * 0.6 + 40);
    data[i * 3 + 2] = clampByte(gray);
  }
  return { size, data };
}

export function attractor(size: number, seed: number, iterations = 300_000): Texture {
  const rng = new Prng(seed);
  const a = rng.nextFloat(-2, 2);
  const b = rng.nextFloat(-2, 2);
  const c = rng.nextFloat(-2, 2);
  const d = rng.nextFloat(-2, 2);
  let x = 0.1;
  let y = 0.1;
  const xs = new Float64Array(iterations);
  const ys = new Float64Array(iterations);
  for (let i = 0; i < iterations; i++) {
    const nx = Math.sin(a * y) - Math.cos(b * x);
    const ny = Math.sin(c * x) - Math.cos(d * y);
    x = nx;
    y = ny;
    xs[i] = x;
    ys[i] = y;
  }

  let xMin = Infinity;
  let xMax = -Infinity;
  let yMin = Infinity;
  let yMax = -Infinity;
  for (let i = 0; i < iterations; i++) {
    if (xs[i] < xMin) xMin = xs[i];
    if (xs[i] > xMax) xMax = xs[i];
    if (ys[i] < yMin) yMin = ys[i];
    if (ys[i] > yMax) yMax = ys[i];
  }

  const hist = new Float64Array(size * size);
  for (let i = 0; i < iterations; i++) {
    const xi = Math.min(size - 1, Math.max(0, Math.floor(((xs[i] - xMin) / (xMax - xMin + 1e-9)) * (size - 1))));
    const yi = Math.min(size - 1, Math.max(0, Math.floor(((ys[i] - yMin) / (yMax - yMin + 1e-9)) * (size - 1))));
    hist[yi * size + xi] += 1;
  }

  const density = new Float64Array(size * size);
  let densityMax = 0;
  for (let i = 0; i < size * size; i++) {
    density[i] = Math.log1p(hist[i]);
    if (density[i] > densityMax) densityMax = density[i];
  }

  const data = new Uint8Array(size * size * 3);
  for (let i = 0; i < size * size; i++) {
    const scaled = densityMax > 0 ? (density[i] / densityMax) * 255 : 0;
    data[i * 3] = clampByte(scaled);
    data[i * 3 + 1] = clampByte(scaled * 0.4);
    data[i * 3 + 2] = clampByte(255 - scaled);
  }
  return { size, data };
}

export const TEXTURE_FLAVORS = ['value_noise', 'voronoi', 'reaction_diffusion', 'attractor'] as const;
export type TextureFlavor = (typeof TEXTURE_FLAVORS)[number];

export function textureByName(name: TextureFlavor, size: number, seed: number): Texture {
  switch (name) {
    case 'value_noise':
      return valueNoise(size, seed);
    case 'voronoi':
      return voronoi(size, seed);
    case 'reaction_diffusion':
      return reactionDiffusion(size, seed);
    case 'attractor':
      return attractor(size, seed);
  }
}
