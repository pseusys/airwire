/**
 * TypeScript port of core/sources/synthesis.py's patch-based reversible texture synthesis -- see
 * that file's docstring for the full explanation of how this works (the scattered-anchor layout,
 * the row-alternating fallback for `attractor`, and why the overlapping-candidate half of Wu &
 * Wang's technique isn't the default). This ports the encode/decode mechanism itself faithfully
 * (same algorithm, same arithmetic-coder primitives from arithmetic.ts); only the source *texture
 * generation* differs from Python (see textures.ts) -- this module doesn't care how a texture was
 * produced, only that both sides derive an identical one, which `textures.ts`'s deterministic
 * seeded generation still guarantees within this page. Likewise, the anchor mask is seeded from
 * `Prng` (mulberry32) rather than NumPy's PCG64, so the specific anchor arrangement won't match
 * the real Python encoder's for the same seed -- fine, since nothing here claims cross-platform
 * bit-exactness (see prng.ts).
 */

import { BitAccumulator, BitCursor, Candidate, candidateRanges, commonLeadingBits, stripTopBits } from './arithmetic';
import { hashBytes, Prng } from './prng';
import { Texture } from './textures';

export const DEFAULT_PATCH_SIZE = 8;
export const DEFAULT_CANVAS_WIDTH = 16;
export const DEFAULT_TEXTURE_SIZE = DEFAULT_CANVAS_WIDTH * DEFAULT_PATCH_SIZE;

// Excludes only orthogonally-adjacent anchors (squared toroidal distance of 1) -- the natural,
// maximal blue-noise packing density on this small a grid. Mirrors synthesis.py.
const MIN_ANCHOR_DISTANCE = 1.1;

// Measured against smaller strides and not adopted -- see synthesis.py's docstring and
// memory/rejected-ideas.md for the full evidence. Non-overlapping (== DEFAULT_PATCH_SIZE) by
// default; PatchLibrary still supports a smaller stride if ever needed.
export const DEFAULT_CANDIDATE_STRIDE = DEFAULT_PATCH_SIZE;

// Minimum squared pixel distance (summed over all patchSize*patchSize*3 values) guaranteed
// between every pair of distinct candidates in a PatchLibrary. Mirrors synthesis.py's
// MIN_CANDIDATE_DISTANCE_SQ -- see its docstring for why (reaction_diffusion's default library had
// two candidates differing by a single color unit in a single pixel, nowhere near enough
// separation for any pixel-level blending to stay decodable).
export const MIN_CANDIDATE_DISTANCE_SQ = 19200; // ~10 RMS per pixel-channel (out of 255), for an 8x8x3 patch.

// Border width, in pixels, softened at every gap patch's edge by featherCanvas. Mirrors
// synthesis.py's SEAM_OVERLAP -- see its docstring for why this is a plain linear feather rather
// than graph-cut seam-finding or Poisson blending (a 1px overlap band leaves neither technique any
// real room to work with).
export const SEAM_OVERLAP = 1;

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

/** Crop a patchSize-square window starting at pixel offset (row0, col0), wrapping each axis
 * independently modulo the image's own size. An overlapping candidate can start at any pixel
 * offset, including ones where the window would otherwise run off the edge -- unlike `subImage`,
 * which is only safe for always-in-bounds crops (e.g. a rendered canvas). Mirrors
 * `_periodic_extract` in synthesis.py. */
function periodicExtract(image: Image, row0: number, col0: number, patchSize: number): Image {
  const data = new Uint8Array(patchSize * patchSize * 3);
  for (let y = 0; y < patchSize; y++) {
    const srcRow = (row0 + y) % image.height;
    for (let x = 0; x < patchSize; x++) {
      const srcCol = (col0 + x) % image.width;
      const srcBase = (srcRow * image.width + srcCol) * 3;
      const dstBase = (y * patchSize + x) * 3;
      data[dstBase] = image.data[srcBase];
      data[dstBase + 1] = image.data[srcBase + 1];
      data[dstBase + 2] = image.data[srcBase + 2];
    }
  }
  return { width: patchSize, height: patchSize, data };
}

function patchKey(patch: Image): string {
  return patch.data.join(',');
}

function patchCore(patch: Image, overlap: number): Image {
  return subImage(patch, overlap, overlap, patch.height - 2 * overlap);
}

/** The candidate palette a source texture is divided into. `stride` (default `patchSize`)
 * reproduces the original non-overlapping tile grid; a smaller stride yields overlapping,
 * pixel-shifted candidates -- see `DEFAULT_CANDIDATE_STRIDE`'s docstring for why that isn't the
 * default. `minDistanceSq` additionally rejects any candidate within that squared pixel distance
 * of an already-accepted one -- not just byte-identical duplicates -- guaranteeing a minimum
 * separation between every pair of accepted patches, needed before any pixel-level blending can
 * stay safely decodable (see `MIN_CANDIDATE_DISTANCE_SQ`). Mirrors `PatchLibrary` in
 * synthesis.py. */
export class PatchLibrary {
  readonly patchSize: number;
  readonly patches: Image[] = [];
  readonly patchOrigins: [number, number][] = [];
  private readonly lookup = new Map<string, number>();
  private readonly coreLookups = new Map<number, Map<string, number>>();

  constructor(texture: Texture, patchSize: number, stride?: number, minDistanceSq = 0) {
    const size = texture.size;
    if (size % patchSize !== 0) {
      throw new Error(`Texture size must be a multiple of patchSize (${patchSize})!`);
    }
    this.patchSize = patchSize;
    const image: Image = { width: size, height: size, data: texture.data };
    const step = stride ?? patchSize;
    const accepted: Image[] = [];

    for (let row = 0; row < size; row += step) {
      for (let col = 0; col < size; col += step) {
        const patch = periodicExtract(image, row, col, patchSize);
        const key = patchKey(patch);
        if (this.lookup.has(key)) continue; // byte-identical duplicate; always rejected, regardless of minDistanceSq.

        if (minDistanceSq > 0 && accepted.length > 0) {
          const tooClose = accepted.some((other) => edgeCost(patch.data, other.data) < minDistanceSq);
          if (tooClose) continue;
        }

        this.lookup.set(key, this.patches.length);
        this.patches.push(patch);
        this.patchOrigins.push([row, col]);
        if (minDistanceSq > 0) accepted.push(patch);
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

  /** A key-to-index lookup from each candidate's core (patch content minus an `overlap`-pixel
   * border on every side) to its index -- built once per `overlap` value and cached. Used by
   * decode to identify a gap patch whose border may have been softened by `featherCanvas`, without
   * needing those (deliberately modified) border pixels to match exactly. Throws if two distinct
   * candidates ever share an identical core: `MIN_CANDIDATE_DISTANCE_SQ` guarantees every pair of
   * full patches differs, but that's a guarantee about the whole patch, not automatically about a
   * smaller sub-region -- this is the actual, not assumed, check. Mirrors `core_lookup` in
   * synthesis.py. */
  coreLookup(overlap: number): Map<string, number> {
    const cached = this.coreLookups.get(overlap);
    if (cached) return cached;

    const lookup = new Map<string, number>();
    this.patches.forEach((patch, index) => {
      const key = patchKey(patchCore(patch, overlap));
      if (lookup.has(key)) {
        throw new Error(`Patches ${lookup.get(key)} and ${index} share an identical core at overlap=${overlap}; MIN_CANDIDATE_DISTANCE_SQ isn't wide enough for this texture!`);
      }
      lookup.set(key, index);
    });
    this.coreLookups.set(overlap, lookup);
    return lookup;
  }

  indexOfCore(patch: Image, overlap: number): number {
    const index = this.coreLookup(overlap).get(patchKey(patchCore(patch, overlap)));
    if (index === undefined) {
      throw new Error("Patch's core doesn't match any entry in this source texture's patch library!");
    }
    return index;
  }
}

/** The literal patch this (periodic) texture holds at canvas position (row, col) -- used to
 * render every anchor cell exactly (real content, no bits consumed) and, for the scattered
 * layout's gap cells, as the ground truth candidates are scored against. Wraps modulo the
 * texture's own patch grid, so it's well-defined for a canvas of any height, even past one full
 * texture period. Mirrors `_guide_patch` in synthesis.py. Exported for tests. */
export function guidePatch(texture: Texture, row: number, col: number, patchSize: number): Image {
  const rowsPerPeriod = Math.floor(texture.size / patchSize);
  const colsPerPeriod = Math.floor(texture.size / patchSize);
  const image: Image = { width: texture.size, height: texture.size, data: texture.data };
  return periodicExtract(image, (row % rowsPerPeriod) * patchSize, (col % colsPerPeriod) * patchSize, patchSize);
}

/** A deterministic seed for the anchor mask, derived from the texture's own content -- so encode
 * and decode agree without needing the original integer seed threaded through (only the
 * regenerated texture is available at this layer). Exported for tests that need to find a real
 * gap cell to tamper with. Mirrors `_mask_seed` in synthesis.py. */
export function maskSeed(texture: Texture): number {
  return hashBytes(texture.data);
}

/** A (period, period) boolean grid of which patch-grid positions are anchors, via deterministic
 * Poisson-disk-style dart-throwing: shuffle every cell with a seeded RNG, accept a cell if it's
 * at least MIN_ANCHOR_DISTANCE from every already-accepted anchor, until no more qualify. Distance
 * is toroidal (wrapped), matching how the mask itself gets tiled modulo its own period for
 * canvases taller than one period. Exported for tests that need to find a real gap cell to
 * tamper with. Mirrors `_anchor_mask` in synthesis.py (using `Prng`, not NumPy's PCG64 -- see the
 * module docstring). */
export function anchorMask(seed: number, period: number): boolean[][] {
  const rng = new Prng(seed);
  const positions: [number, number][] = [];
  for (let row = 0; row < period; row++) {
    for (let col = 0; col < period; col++) positions.push([row, col]);
  }
  for (let i = positions.length - 1; i > 0; i--) {
    const j = rng.nextInt(0, i + 1);
    [positions[i], positions[j]] = [positions[j], positions[i]];
  }

  const accepted: [number, number][] = [];
  const mask: boolean[][] = Array.from({ length: period }, () => new Array(period).fill(false));
  const minDistanceSq = MIN_ANCHOR_DISTANCE * MIN_ANCHOR_DISTANCE;

  for (const [row, col] of positions) {
    let farEnough = true;
    for (const [acceptedRow, acceptedCol] of accepted) {
      const rowGap = Math.min(Math.abs(row - acceptedRow), period - Math.abs(row - acceptedRow));
      const colGap = Math.min(Math.abs(col - acceptedCol), period - Math.abs(col - acceptedCol));
      if (rowGap * rowGap + colGap * colGap < minDistanceSq) {
        farEnough = false;
        break;
      }
    }
    if (farEnough) {
      accepted.push([row, col]);
      mask[row][col] = true;
    }
  }

  return mask;
}

export function isAnchor(mask: boolean[][], row: number, col: number): boolean {
  const period = mask.length;
  return mask[((row % period) + period) % period][((col % period) + period) % period];
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

function weightsFromCosts(costs: number[]): Candidate<number>[] {
  const maxCost = Math.max(...costs);
  return costs.map((cost, index) => [index, BigInt(maxCost - cost + 1)] as Candidate<number>);
}

/** Weight every library patch by how close a whole-patch match it is to the texture's true
 * content at this exact position, plus its top/left edges against the already-resolved neighbors
 * above and to the left, when they exist (never below or right -- those aren't resolved yet in
 * this raster-order walk). Mirrors `_candidate_weights_scattered` in synthesis.py. */
function candidateWeightsScattered(library: PatchLibrary, texture: Texture, row: number, col: number, above: Image | null, left: Image | null): Candidate<number>[] {
  const target = guidePatch(texture, row, col, library.patchSize);
  const costs: number[] = [];
  for (const patch of library.patches) {
    let cost = edgeCost(patch.data, target.data);
    if (left !== null) cost += edgeCost(leftColumn(patch), rightColumn(left));
    if (above !== null) cost += edgeCost(topRow(patch), bottomRow(above));
    costs.push(cost);
  }
  return weightsFromCosts(costs);
}

/** `attractor`'s unchanged mechanism: rank every library patch purely by local edge agreement
 * with the seed rows immediately above and below, plus the already-chosen gap patch to its left,
 * if any. Mirrors `_candidate_weights_rows` in synthesis.py. */
function candidateWeightsRows(library: PatchLibrary, gapRow: Image[], texture: Texture, row: number, col: number): Candidate<number>[] {
  const above = guidePatch(texture, row - 1, col, library.patchSize);
  const below = guidePatch(texture, row + 1, col, library.patchSize);
  const left = col > 0 ? gapRow[col - 1] : null;

  const costs: number[] = [];
  for (const patch of library.patches) {
    let cost = edgeCost(topRow(patch), bottomRow(above)) + edgeCost(bottomRow(patch), topRow(below));
    if (left !== null) {
      cost += edgeCost(leftColumn(patch), rightColumn(left));
    }
    costs.push(cost);
  }
  return weightsFromCosts(costs);
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

export function extractPatchAt(canvas: Image, patchRow: number, patchCol: number, patchSize: number): Image {
  return subImage(canvas, patchRow * patchSize, patchCol * patchSize, patchSize);
}

function pixelAt(image: Image, row: number, col: number): [number, number, number] {
  const base = (row * image.width + col) * 3;
  return [image.data[base], image.data[base + 1], image.data[base + 2]];
}

function getPixel(data: Float64Array, width: number, row: number, col: number): [number, number, number] {
  const base = (row * width + col) * 3;
  return [data[base], data[base + 1], data[base + 2]];
}

function setPixel(data: Float64Array, width: number, row: number, col: number, value: [number, number, number]): void {
  const base = (row * width + col) * 3;
  data[base] = value[0];
  data[base + 1] = value[1];
  data[base + 2] = value[2];
}

/** Softens the hard edge at every boundary that touches at least one gap patch, by linearly
 * cross-fading an `overlap`-pixel-wide band on the gap side(s) of that boundary toward the
 * neighbor's own nearest edge pixels. Anchors are never modified -- only a gap patch's own outer
 * border is touched, and only that far, so decode's exact match on the interior (core) region is
 * unaffected by this pass regardless of how visible the untreated boundary would otherwise be.
 * Every gap patch gets every one of its internal edges treated the same way, uniformly, so decode
 * doesn't need to know which specific neighbors were anchors versus gaps -- it just always reads
 * the core. Corners (touched by both an edge blend and its neighboring perpendicular blend) get a
 * small compounding effect, an accepted simplification for this first, deliberately thin pass.
 * Mirrors `_feather_canvas` in synthesis.py. Exported for tests. */
export function featherCanvas(canvas: Image, mask: boolean[][], patchSize: number, overlap: number): Image {
  const totalRows = Math.floor(canvas.height / patchSize);
  const canvasWidth = Math.floor(canvas.width / patchSize);
  const blended = Float64Array.from(canvas.data);

  const mix = (own: [number, number, number], neighbor: [number, number, number], weight: number): [number, number, number] => [
    own[0] * (1 - weight) + neighbor[0] * weight,
    own[1] * (1 - weight) + neighbor[1] * weight,
    own[2] * (1 - weight) + neighbor[2] * weight,
  ];

  for (let row = 0; row < totalRows; row++) {
    for (let col = 0; col < canvasWidth - 1; col++) {
      const leftIsAnchor = isAnchor(mask, row, col);
      const rightIsAnchor = isAnchor(mask, row, col + 1);
      if (leftIsAnchor && rightIsAnchor) continue;
      const r0 = row * patchSize;
      for (let dy = 0; dy < patchSize; dy++) {
        const r = r0 + dy;
        const leftEdge = pixelAt(canvas, r, col * patchSize + patchSize - 1);
        const rightEdge = pixelAt(canvas, r, (col + 1) * patchSize);
        for (let offset = 0; offset < overlap; offset++) {
          const weight = (offset + 1) / (overlap + 1);
          if (!leftIsAnchor) {
            const c = col * patchSize + patchSize - overlap + offset;
            setPixel(blended, canvas.width, r, c, mix(pixelAt(canvas, r, c), rightEdge, weight));
          }
          if (!rightIsAnchor) {
            const c = (col + 1) * patchSize + (overlap - 1 - offset);
            setPixel(blended, canvas.width, r, c, mix(pixelAt(canvas, r, c), leftEdge, weight));
          }
        }
      }
    }
  }

  for (let row = 0; row < totalRows - 1; row++) {
    for (let col = 0; col < canvasWidth; col++) {
      const topIsAnchor = isAnchor(mask, row, col);
      const bottomIsAnchor = isAnchor(mask, row + 1, col);
      if (topIsAnchor && bottomIsAnchor) continue;
      const c0 = col * patchSize;
      for (let dx = 0; dx < patchSize; dx++) {
        const c = c0 + dx;
        const topEdge = pixelAt(canvas, row * patchSize + patchSize - 1, c);
        const bottomEdge = pixelAt(canvas, (row + 1) * patchSize, c);
        for (let offset = 0; offset < overlap; offset++) {
          const weight = (offset + 1) / (overlap + 1);
          if (!topIsAnchor) {
            const r = row * patchSize + patchSize - overlap + offset;
            setPixel(blended, canvas.width, r, c, mix(getPixel(blended, canvas.width, r, c), bottomEdge, weight));
          }
          if (!bottomIsAnchor) {
            const r = (row + 1) * patchSize + (overlap - 1 - offset);
            setPixel(blended, canvas.width, r, c, mix(getPixel(blended, canvas.width, r, c), topEdge, weight));
          }
        }
      }
    }
  }

  const data = Uint8Array.from(blended.map((value) => Math.max(0, Math.min(255, Math.round(value)))));
  return { width: canvas.width, height: canvas.height, data };
}

function encodeScattered(data: Uint8Array, texture: Texture, patchSize: number, canvasWidth: number): Image {
  const library = new PatchLibrary(texture, patchSize, DEFAULT_CANDIDATE_STRIDE, MIN_CANDIDATE_DISTANCE_SQ);
  const period = Math.floor(texture.size / patchSize);
  const mask = anchorMask(maskSeed(texture), period);
  const cursor = new BitCursor(data);
  const rows: Image[][] = [];
  let low = 0n;
  let high = 1n;
  let width = 1;
  let rowIndex = 0;

  for (;;) {
    const rowPatches: Image[] = [];
    for (let col = 0; col < canvasWidth; col++) {
      if (isAnchor(mask, rowIndex, col)) {
        rowPatches.push(guidePatch(texture, rowIndex, col, patchSize));
        continue;
      }

      const above = rowIndex > 0 ? rows[rowIndex - 1][col] : null;
      const left = col > 0 ? rowPatches[col - 1] : null;
      const candidates = candidateWeightsScattered(library, texture, rowIndex, col, above, left);

      if (cursor.remaining() <= 0) {
        let [bestIndex, bestWeight] = candidates[0];
        for (const [index, weight] of candidates) {
          if (weight > bestWeight) {
            bestWeight = weight;
            bestIndex = index;
          }
        }
        rowPatches.push(library.patches[bestIndex]);
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
      rowPatches.push(library.patches[index]);
      low = lo;
      high = hi;

      const common = commonLeadingBits(low, high, width);
      if (common) {
        cursor.consume(Math.min(common, cursor.remaining()));
        [low, high, width] = stripTopBits(low, high, width, common);
      }
    }

    rows.push(rowPatches);
    rowIndex++;
    if (cursor.remaining() <= 0) break;
  }

  const canvas = rowsToCanvas(rows);
  return featherCanvas(canvas, mask, patchSize, SEAM_OVERLAP);
}

function decodeScattered(canvas: Image, texture: Texture, length: number, patchSize: number): Uint8Array {
  const library = new PatchLibrary(texture, patchSize, DEFAULT_CANDIDATE_STRIDE, MIN_CANDIDATE_DISTANCE_SQ);
  const canvasWidth = Math.floor(canvas.width / patchSize);
  const totalRows = Math.floor(canvas.height / patchSize);
  const period = Math.floor(texture.size / patchSize);
  const mask = anchorMask(maskSeed(texture), period);

  const accumulator = new BitAccumulator(length);
  let low = 0n;
  let high = 1n;
  let width = 1;
  const rows: Image[][] = [];

  for (let rowIndex = 0; rowIndex < totalRows; rowIndex++) {
    const rowPatches: Image[] = [];
    for (let col = 0; col < canvasWidth; col++) {
      const rawPatch = extractPatchAt(canvas, rowIndex, col, patchSize);

      if (isAnchor(mask, rowIndex, col)) {
        rowPatches.push(rawPatch); // anchors are never touched by feathering; exact already.
        continue;
      }

      // Gap patches may have had their border softened by featherCanvas, so identify them by
      // their (untouched) core -- then use the library's pristine copy, not the raw (possibly
      // blended) canvas pixels, for every later cell's above/left reference, so decode's scoring
      // stays bit-for-bit consistent with what encode actually used.
      const actualIndex = library.indexOfCore(rawPatch, SEAM_OVERLAP);
      const resolvedPatch = library.patches[actualIndex];
      rowPatches.push(resolvedPatch);

      if (accumulator.done()) continue;

      const above = rowIndex > 0 ? rows[rowIndex - 1][col] : null;
      const left = col > 0 ? rowPatches[col - 1] : null;
      const candidates = candidateWeightsScattered(library, texture, rowIndex, col, above, left);
      const [ranges, newLow, newHigh, newWidth] = candidateRanges(low, high, width, candidates, accumulator.remaining());
      low = newLow;
      high = newHigh;
      width = newWidth;
      const match = ranges.find(([index]) => index === actualIndex);
      if (!match) {
        throw new Error(`Patch at (row=${rowIndex}, col=${col}) is not a valid candidate at this point in the synthesis walk!`);
      }
      const [, lo, hi] = match;
      low = lo;
      high = hi;

      const common = commonLeadingBits(low, high, width);
      if (common) {
        accumulator.append(low, width, common);
        [low, high, width] = stripTopBits(low, high, width, common);
      }
    }
    rows.push(rowPatches);
    if (accumulator.done()) break;
  }

  return accumulator.finish();
}

/** `attractor`'s unchanged mechanism: a seed row, then alternating gap/seed row pairs until `data`
 * is fully consumed, padded with best-match filler (no bits consumed) if it runs out mid-row, so
 * the result is always rectangular. Mirrors `_encode_rows` in synthesis.py. */
function encodeRows(data: Uint8Array, texture: Texture, patchSize: number, canvasWidth: number): Image {
  const library = new PatchLibrary(texture, patchSize);
  const cursor = new BitCursor(data);
  const rows: Image[][] = [Array.from({ length: canvasWidth }, (_, col) => guidePatch(texture, 0, col, patchSize))];
  let low = 0n;
  let high = 1n;
  let width = 1;
  let rowIndex = 1;

  while (cursor.remaining() > 0) {
    const gapRow: Image[] = [];
    for (let col = 0; col < canvasWidth; col++) {
      const candidates = candidateWeightsRows(library, gapRow, texture, rowIndex, col);
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
    rows.push(Array.from({ length: canvasWidth }, (_, col) => guidePatch(texture, rowIndex + 1, col, patchSize)));
    rowIndex += 2;
  }

  return rowsToCanvas(rows);
}

/** Invert `encodeRows`. Mirrors `_decode_rows` in synthesis.py. */
function decodeRows(canvas: Image, texture: Texture, length: number, patchSize: number): Uint8Array {
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

      const candidates = candidateWeightsRows(library, gapRow, texture, rowIndex, col);
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

/** Synthesize `data` into an image: the scattered-anchor layout (`positionGuided=true`, the
 * default) or the row-alternating layout (`positionGuided=false`, `attractor` only). Mirrors
 * `encode` in synthesis.py. */
export function encode(
  data: Uint8Array,
  texture: Texture,
  patchSize = DEFAULT_PATCH_SIZE,
  canvasWidth = DEFAULT_CANVAS_WIDTH,
  positionGuided = true,
): Image {
  if (positionGuided) return encodeScattered(data, texture, patchSize, canvasWidth);
  return encodeRows(data, texture, patchSize, canvasWidth);
}

/** Invert `encode`: recover exactly `length` bytes from a synthesized canvas. Mirrors `decode` in
 * synthesis.py. */
export function decode(canvas: Image, texture: Texture, length: number, patchSize = DEFAULT_PATCH_SIZE, positionGuided = true): Uint8Array {
  if (positionGuided) return decodeScattered(canvas, texture, length, patchSize);
  return decodeRows(canvas, texture, length, patchSize);
}
