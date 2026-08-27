/**
 * TypeScript port of core/sources/synthesis.py's patch-based reversible texture synthesis -- see
 * that file's docstring for the full explanation of how this works. This ports the encode/decode
 * mechanism itself faithfully (same algorithm, same arithmetic-coder primitives from
 * arithmetic.ts); only the source *texture generation* differs from Python (see textures.ts) --
 * this module doesn't care how a texture was produced, only that both sides derive an identical
 * one, which `textures.ts`'s deterministic seeded generation still guarantees within this page.
 */

import { BitAccumulator, BitCursor, Candidate, candidateRanges, commonLeadingBits, stripTopBits } from './arithmetic';
import { Texture } from './textures';

export const DEFAULT_PATCH_SIZE = 8;
export const DEFAULT_CANVAS_WIDTH = 16;
export const DEFAULT_TEXTURE_SIZE = 64;

export interface Image {
  readonly width: number;
  readonly height: number;
  /** Row-major RGB, no alpha: `data[(y * width + x) * 3 + channel]`. */
  readonly data: Uint8Array;
}

function subImage(image: Image, r0: number, c0: number, size: number): Image {
  const data = new Uint8Array(size * size * 3);
  for (let y = 0; y < size; y++) {
    const srcStart = ((r0 + y) * image.width + c0) * 3;
    data.set(image.data.subarray(srcStart, srcStart + size * 3), y * size * 3);
  }
  return { width: size, height: size, data };
}

function patchKey(patch: Image): string {
  return patch.data.join(',');
}

/** The fixed palette of candidate patches a source texture is divided into. */
export class PatchLibrary {
  readonly patchSize: number;
  readonly patches: Image[] = [];
  private readonly lookup = new Map<string, number>();

  constructor(texture: Texture, patchSize: number) {
    const size = texture.size;
    if (size % patchSize !== 0) {
      throw new Error(`Texture size must be a multiple of patchSize (${patchSize})!`);
    }
    this.patchSize = patchSize;
    const image: Image = { width: size, height: size, data: texture.data };
    for (let row = 0; row < size; row += patchSize) {
      for (let col = 0; col < size; col += patchSize) {
        const patch = subImage(image, row, col, patchSize);
        const key = patchKey(patch);
        if (this.lookup.has(key)) continue; // flat/repeated regions (e.g. Voronoi cell interiors) can duplicate; skip.
        this.lookup.set(key, this.patches.length);
        this.patches.push(patch);
      }
    }
    if (this.patches.length < 2) {
      throw new Error('Source texture yields fewer than 2 distinct patches; pick a larger or more varied texture!');
    }
  }

  get length(): number {
    return this.patches.length;
  }

  indexOf(patch: Image): number {
    const index = this.lookup.get(patchKey(patch));
    if (index === undefined) {
      throw new Error("Patch doesn't match any entry in this source texture's patch library!");
    }
    return index;
  }
}

function seedIndex(seedOrdinal: number, col: number, canvasWidth: number, librarySize: number): number {
  return (((seedOrdinal * canvasWidth + col) % librarySize) + librarySize) % librarySize;
}

function seedPatch(library: PatchLibrary, seedOrdinal: number, col: number, canvasWidth: number): Image {
  return library.patches[seedIndex(seedOrdinal, col, canvasWidth, library.length)];
}

function topRow(patch: Image): Uint8Array {
  return patch.data.subarray(0, patch.width * 3);
}

function bottomRow(patch: Image): Uint8Array {
  const start = (patch.height - 1) * patch.width * 3;
  return patch.data.subarray(start, start + patch.width * 3);
}

function leftColumn(patch: Image): number[] {
  const out: number[] = [];
  for (let y = 0; y < patch.height; y++) {
    const base = y * patch.width * 3;
    out.push(patch.data[base], patch.data[base + 1], patch.data[base + 2]);
  }
  return out;
}

function rightColumn(patch: Image): number[] {
  const out: number[] = [];
  for (let y = 0; y < patch.height; y++) {
    const base = (y * patch.width + patch.width - 1) * 3;
    out.push(patch.data[base], patch.data[base + 1], patch.data[base + 2]);
  }
  return out;
}

function edgeCost(a: ArrayLike<number>, b: ArrayLike<number>): number {
  let sum = 0;
  for (let i = 0; i < a.length; i++) {
    const diff = a[i] - b[i];
    sum += diff * diff;
  }
  return sum;
}

/** Weight every library patch by how well it would blend into gap-row position (row, col) --
 * mirrors `_candidate_weights` in synthesis.py, including that decision's outcome: a wider
 * overlap window was tried in the Python original and made results worse, not better (design
 * decision #4), so this stays a single-row/column edge comparison. */
function candidateWeights(library: PatchLibrary, gapRow: Image[], row: number, col: number, canvasWidth: number): Candidate<number>[] {
  const above = seedPatch(library, Math.floor((row - 1) / 2), col, canvasWidth);
  const below = seedPatch(library, Math.floor((row + 1) / 2), col, canvasWidth);
  const left = col > 0 ? gapRow[col - 1] : null;

  const costs: number[] = [];
  for (const patch of library.patches) {
    let cost = edgeCost(topRow(patch), bottomRow(above)) + edgeCost(bottomRow(patch), topRow(below));
    if (left !== null) {
      cost += edgeCost(leftColumn(patch), rightColumn(left));
    }
    costs.push(cost);
  }
  const maxCost = Math.max(...costs);
  return costs.map((cost, index) => [index, BigInt(maxCost - cost + 1)] as Candidate<number>);
}

function blit(dst: Uint8Array, dstWidth: number, patch: Image, r0: number, c0: number): void {
  for (let y = 0; y < patch.height; y++) {
    const srcStart = y * patch.width * 3;
    const dstStart = ((r0 + y) * dstWidth + c0) * 3;
    dst.set(patch.data.subarray(srcStart, srcStart + patch.width * 3), dstStart);
  }
}

function rowsToCanvas(rows: Image[][]): Image {
  const patchSize = rows[0][0].height;
  const canvasWidth = rows[0].length * patchSize;
  const canvasHeight = rows.length * patchSize;
  const data = new Uint8Array(canvasWidth * canvasHeight * 3);
  for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
    for (let colIdx = 0; colIdx < rows[rowIdx].length; colIdx++) {
      blit(data, canvasWidth, rows[rowIdx][colIdx], rowIdx * patchSize, colIdx * patchSize);
    }
  }
  return { width: canvasWidth, height: canvasHeight, data };
}

function extractPatchAt(canvas: Image, patchRow: number, patchCol: number, patchSize: number): Image {
  return subImage(canvas, patchRow * patchSize, patchCol * patchSize, patchSize);
}

/** Synthesize `data` into an image: a seed row, then alternating gap/seed row pairs until `data`
 * is fully consumed, padded with best-match filler (no bits consumed) if it runs out mid-row, so
 * the result is always rectangular. Mirrors `encode` in synthesis.py. */
export function encode(data: Uint8Array, texture: Texture, patchSize = DEFAULT_PATCH_SIZE, canvasWidth = DEFAULT_CANVAS_WIDTH): Image {
  const library = new PatchLibrary(texture, patchSize);
  const cursor = new BitCursor(data);
  const rows: Image[][] = [Array.from({ length: canvasWidth }, (_, col) => seedPatch(library, 0, col, canvasWidth))];
  let low = 0n;
  let high = 1n;
  let width = 1;
  let seedOrdinal = 1;
  let rowIndex = 1;

  while (cursor.remaining() > 0) {
    const gapRow: Image[] = [];
    for (let col = 0; col < canvasWidth; col++) {
      const candidates = candidateWeights(library, gapRow, rowIndex, col, canvasWidth);
      if (cursor.remaining() <= 0) {
        let [bestIndex, bestWeight] = candidates[0];
        for (const [index, weight] of candidates) {
          if (weight > bestWeight) {
            bestWeight = weight;
            bestIndex = index;
          }
        }
        gapRow.push(library.patches[bestIndex]);
        continue;
      }

      const budget = cursor.remaining();
      const [ranges, newLow, newHigh, newWidth] = candidateRanges(low, high, width, candidates, budget);
      low = newLow;
      high = newHigh;
      width = newWidth;
      const peeked = cursor.peek(width);
      const match = ranges.find(([, lo, hi]) => lo <= peeked && peeked <= hi);
      if (!match) {
        throw new Error('No candidate range matched the peeked bits -- this should never happen.');
      }
      const [index, lo, hi] = match;
      gapRow.push(library.patches[index]);
      low = lo;
      high = hi;

      const common = commonLeadingBits(low, high, width);
      if (common) {
        cursor.consume(Math.min(common, cursor.remaining()));
        [low, high, width] = stripTopBits(low, high, width, common);
      }
    }

    rows.push(gapRow);
    rows.push(Array.from({ length: canvasWidth }, (_, col) => seedPatch(library, seedOrdinal, col, canvasWidth)));
    seedOrdinal++;
    rowIndex += 2;
  }

  return rowsToCanvas(rows);
}

/** Invert `encode`: recover exactly `length` bytes from a synthesized canvas. Mirrors `decode` in
 * synthesis.py. */
export function decode(canvas: Image, texture: Texture, length: number, patchSize = DEFAULT_PATCH_SIZE): Uint8Array {
  const library = new PatchLibrary(texture, patchSize);
  const canvasWidth = Math.floor(canvas.width / patchSize);
  const totalRows = Math.floor(canvas.height / patchSize);

  const accumulator = new BitAccumulator(length);
  let low = 0n;
  let high = 1n;
  let width = 1;
  let rowIndex = 1;

  while (rowIndex < totalRows && !accumulator.done()) {
    const gapRow: Image[] = [];
    for (let col = 0; col < canvasWidth; col++) {
      const patch = extractPatchAt(canvas, rowIndex, col, patchSize);
      if (accumulator.done()) {
        gapRow.push(patch);
        continue;
      }

      const candidates = candidateWeights(library, gapRow, rowIndex, col, canvasWidth);
      const [ranges, newLow, newHigh, newWidth] = candidateRanges(low, high, width, candidates, accumulator.remaining());
      low = newLow;
      high = newHigh;
      width = newWidth;
      const actualIndex = library.indexOf(patch);
      const match = ranges.find(([index]) => index === actualIndex);
      if (!match) {
        throw new Error(`Patch at (row=${rowIndex}, col=${col}) is not a valid candidate at this point in the synthesis walk!`);
      }
      const [, lo, hi] = match;
      low = lo;
      high = hi;
      gapRow.push(patch);

      const common = commonLeadingBits(low, high, width);
      if (common) {
        accumulator.append(low, width, common);
        [low, high, width] = stripTopBits(low, high, width, common);
      }
    }
    rowIndex += 2;
  }

  return accumulator.finish();
}
