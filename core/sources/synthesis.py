"""
Disguises ciphertext as an abstract, patterned image via reversible patch-based texture
synthesis, using the same arithmetic coder (`sources/arithmetic.py`) built for
`sources/markov.py`'s text disguise -- adapted from Wu & Wang's "Steganography Using Reversible
Texture Synthesis" (IEEE TIP, 2015), with one deliberate departure from their design (see
`memory/wire-protocol.md` for the full story): Wu & Wang also recover the exact original source
texture from the stego image, because in their setting the texture itself is secret content.
Here
the source texture is a public, regenerable "codebook" (see `sources/textures.py`) that both ends
already have via a shared seed, so that whole recovery mechanism -- and the index-table bookkeeping
it needs -- is simply not needed and isn't built.

Two layout mechanisms exist, chosen per texture flavor via `position_guided`:

- **Scattered anchor layout** (`value_noise`, `voronoi`, `reaction_diffusion`): every canvas
  position is either an **anchor** (real, untouched texture content at that exact position,
  carrying no secret data) or a **gap** (synthesized, secret-bit-driven), per a deterministic,
  seed-derived 2-D anchor mask (`_anchor_mask`) -- not confined to whole rows, which is what Wu &
  Wang's "scatter" idea is actually for, and what removes the visible seed/gap row-banding the
  row-alternating layout has.
Gap cells are filled one patch at a time, in a plain row-major raster
  scan, by ranking `PatchLibrary` candidates by how close a whole-patch match they are to the
  texture's true content at that exact position -- plus, where available, their edge agreement
  with the already-resolved neighbor above and to the left (never below or to the right -- those
  aren't resolved yet in raster order).
`PatchLibrary` also supports drawing candidates from
  *overlapping*, pixel-shifted crops (its `stride` parameter) rather than only the non-overlapping
  tile grid, matching the other half of Wu & Wang's technique -- measured directly and not adopted
  as the default (see `DEFAULT_CANDIDATE_STRIDE` below and `memory/rejected-ideas.md`), but kept as
  a real, working, still-available option.
The scattered placement itself is what removes the
  banding; see the 2026-09-09 CHANGELOG.md entries for the before/after evidence.
Once the whole
  canvas is decided, `_feather_canvas` softens the hard edge at every gap patch's own border
  (`SEAM_OVERLAP` pixels wide) by linearly cross-fading it toward each neighbor's nearest edge --
  confined strictly to that border, never the patch's interior, so decode's exact match on the
  untouched core (`PatchLibrary.index_of_core`) recovers the original choice regardless of blend
  strength.
See `SEAM_OVERLAP`'s docstring for why this is a plain linear feather rather than the
  graph-cut/Poisson techniques the literature actually recommends for this problem.
- **Row-alternating layout** (`attractor` only): the original mechanism -- alternating seed rows
  (whole, untouched patches, one full row at a time) and gap rows (filled one patch at a time,
  scored only against the seed rows immediately above/below and the already-chosen patch to the
  left).
`attractor` has no exploitable 2-D positional structure to place scattered anchors by (a
  sparse chaotic-orbit density histogram, not a spatially periodic field -- confirmed by direct
  tiling tests), so it stays on this simpler, already-adequate mechanism, unaffected by feathering.

Match quality (sum of squared pixel differences) becomes an integer weight -- exact integer
arithmetic throughout, never floating point, for the same reason `sources/markov.py` avoids it:
the arithmetic coder needs bit-exact agreement between encode and decode on any device.
The
arithmetic coder then picks which patch to place the same way it picks words in the text case:
secret bits select among the weighted candidates, not "the best match."

Known limitations, worth a second look independently of this module:

- Each gap cell is still an independently-scored choice among discrete candidates, so a cell can
  still visibly mismatch its neighbors even with the position-guided target term -- the scattered
  layout spreads this over the whole canvas instead of confining it to alternating rows, which is
  a real improvement, but doesn't make each individual gap cell's match any better than before.
- `_feather_canvas`'s border is deliberately thin (`SEAM_OVERLAP=1`): the safety margin that
  survives once a border is excluded from candidate matching is already thin for
  `voronoi`/`reaction_diffusion` at 1px and unusable by 2px, so there isn't currently room for a
  wider, more visually effective blend on those two flavors without first finding a way to widen
  that margin (e.g. a stricter, per-flavor `MIN_CANDIDATE_DISTANCE_SQ`).
"""

import base64
import hashlib
import io
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
from PIL import Image

from sources.arithmetic import BitAccumulator, BitCursor, candidate_ranges, common_leading_bits, strip_top_bits
from sources.encodings import ChunkEncoding
from sources.proto import hyperchunk_pb2
from sources.textures import texture_by_name

DEFAULT_PATCH_SIZE = 8
DEFAULT_CANVAS_WIDTH = 16
# Must equal DEFAULT_CANVAS_WIDTH * DEFAULT_PATCH_SIZE: the source texture has to be exactly as
# wide, in patches, as the canvas, or _guide_patch's row/col lookup stops corresponding to a real
# position in the texture (see memory/wire-protocol.md).
DEFAULT_TEXTURE_SIZE = DEFAULT_CANVAS_WIDTH * DEFAULT_PATCH_SIZE

# Excludes only orthogonally-adjacent anchors (squared toroidal distance of 1) -- the natural,
# maximal blue-noise packing density on this small a grid, empirically ~36-39% anchors (measured
# across seeds), not a value tuned to hit a specific target. See the 2026-09-09 CHANGELOG.md entry.
MIN_ANCHOR_DISTANCE = 1.1

# Every unique patch-size-square window starting at a pixel offset that's a multiple of this
# stride, wrapped periodically. Measured directly against smaller strides (1, 2, 4) before picking
# this: the overlapping candidates a smaller stride adds showed no consistent quality win across
# texture flavors (better for one, worse for another, inconsistent per-flavor optima) while costing
# up to ~90x more wall-clock time per message -- not worth it for this arithmetic-coder-driven,
# weighted-random selection (the same lesson the OVERLAP experiment already found: a richer
# candidate pool doesn't reliably help a weighted-random pick the way it would a strict minimizer).
# See memory/rejected-ideas.md's "Overlapping candidate patches" entry for the full measurements.
DEFAULT_CANDIDATE_STRIDE = DEFAULT_PATCH_SIZE

# Minimum squared pixel distance (summed over all patch_size*patch_size*3 values) guaranteed
# between every pair of distinct candidates in a PatchLibrary -- see MIN_CANDIDATE_DISTANCE_SQ's
# use in PatchLibrary below. Measured per flavor before picking this: reaction_diffusion's default
# (exact-dedup-only) library had two candidates differing by a single color unit in a single
# pixel -- nowhere near enough separation for any pixel-level blending to stay decodable. See the
# 2026-09-10 CHANGELOG.md entry for the measured library-size trade-off this threshold costs.
MIN_CANDIDATE_DISTANCE_SQ = 19200  # ~10 RMS per pixel-channel (out of 255), for an 8x8x3 patch.

# Border width, in pixels, softened at every gap patch's edge by _feather_canvas. Kept
# intentionally thin: re-measuring the minimum-distance guarantee over just the core (patch
# content minus this border) showed it's already thin for voronoi/reaction_diffusion at 1px, and
# collapses entirely by 2px -- see the 2026-09-10 CHANGELOG.md entry. Plain linear feathering was
# chosen over graph-cut seam-finding or Poisson blending because a 1px overlap band leaves neither
# technique any real room to route a seam or blend a gradient through -- their usual advantage
# needs a much wider overlap than the safety numbers allow here.
SEAM_OVERLAP = 1


class PatchLibrary:
    """The candidate palette a source texture is divided into. `stride=patch_size` (the default)
        reproduces the original non-overlapping tile grid; a smaller stride yields overlapping,
        pixel-shifted candidates -- a much finer-grained palette, at the cost of a bigger library to
        build and score.
    `min_distance_sq` additionally rejects any candidate within that squared pixel
        distance of an already-accepted one -- not just byte-identical duplicates -- guaranteeing a
        minimum separation between every pair of accepted patches, needed before any pixel-level
        blending can stay safely decodable (see `MIN_CANDIDATE_DISTANCE_SQ`)."""

    def __init__(self, texture: np.ndarray, patch_size: int, stride: Optional[int] = None, min_distance_sq: float = 0.0) -> None:
        size = texture.shape[0]
        if texture.shape[0] != texture.shape[1] or size % patch_size != 0:
            raise ValueError(f"Texture must be square with a side length that's a multiple of patch_size ({patch_size})!")

        self.patch_size = patch_size
        self.patches: List[np.ndarray] = []
        self.patch_origins: List[Tuple[int, int]] = []
        lookup: Dict[bytes, int] = {}
        accepted_i64: List[np.ndarray] = []

        for row in range(0, size, stride or patch_size):
            for col in range(0, size, stride or patch_size):
                patch = _periodic_extract(texture, row, col, patch_size)
                key = patch.tobytes()
                if key in lookup:
                    continue  # byte-identical duplicate; always rejected, regardless of min_distance_sq.

                if min_distance_sq > 0 and accepted_i64:
                    candidate_i64 = patch.astype(np.int64)
                    too_close = any(np.sum((candidate_i64 - other) ** 2) < min_distance_sq for other in accepted_i64)
                    if too_close:
                        continue

                lookup[key] = len(self.patches)
                self.patches.append(patch)
                self.patch_origins.append((row, col))
                if min_distance_sq > 0:
                    accepted_i64.append(patch.astype(np.int64))

        if len(self.patches) < 2:
            raise ValueError("Source texture yields fewer than 2 distinct patches; pick a larger or more varied texture!")
        self._lookup = lookup
        self.patches_array = np.stack(self.patches)  # (N, patch_size, patch_size, 3) uint8, for vectorized scoring.
        self._core_lookups: Dict[int, Dict[bytes, int]] = {}

    def __len__(self) -> int:
        return len(self.patches)

    def index_of(self, patch: np.ndarray) -> int:
        try:
            return self._lookup[patch.tobytes()]
        except KeyError:
            raise ValueError("Patch doesn't match any entry in this source texture's patch library!") from None

    def _core(self, patch: np.ndarray, overlap: int) -> np.ndarray:
        return patch[overlap : self.patch_size - overlap, overlap : self.patch_size - overlap, :]

    def core_lookup(self, overlap: int) -> Dict[bytes, int]:
        """A byte-keyed lookup from each candidate's core (patch content minus an `overlap`-pixel
                border on every side) to its index -- built once per `overlap` value and cached.
        Used by
                decode to identify a gap patch whose border may have been softened by `_feather_canvas`,
                without needing those (deliberately modified) border pixels to match exactly.
        Raises if two
                distinct candidates ever share an identical core: `MIN_CANDIDATE_DISTANCE_SQ` guarantees
                every pair of full patches differs, but that's a guarantee about the whole patch, not
                automatically about a smaller sub-region -- this is the actual, not assumed, check."""

        cached = self._core_lookups.get(overlap)
        if cached is not None:
            return cached

        lookup: Dict[bytes, int] = {}
        for index, patch in enumerate(self.patches):
            key = self._core(patch, overlap).tobytes()
            if key in lookup:
                raise ValueError(f"Patches {lookup[key]} and {index} share an identical core at overlap={overlap}; MIN_CANDIDATE_DISTANCE_SQ isn't wide enough for this texture!")
            lookup[key] = index
        self._core_lookups[overlap] = lookup
        return lookup

    def index_of_core(self, patch: np.ndarray, overlap: int) -> int:
        try:
            return self.core_lookup(overlap)[self._core(patch, overlap).tobytes()]
        except KeyError:
            raise ValueError("Patch's core doesn't match any entry in this source texture's patch library!") from None


def _periodic_extract(texture: np.ndarray, row0: int, col0: int, patch_size: int) -> np.ndarray:
    """Crop a patch_size-square window starting at pixel offset (row0, col0), wrapping each axis
    independently modulo the texture's own size. An overlapping candidate can start at any pixel
    offset, including ones where the window would otherwise run off the edge -- unlike the
    always-tile-aligned crops this reduces to at stride=patch_size, which never actually need to
    wrap mid-patch."""

    size = texture.shape[0]
    rows = [(row0 + offset) % size for offset in range(patch_size)]
    cols = [(col0 + offset) % size for offset in range(patch_size)]
    return texture[np.ix_(rows, cols)]


def _guide_patch(texture: np.ndarray, row: int, col: int, patch_size: int) -> np.ndarray:
    """The literal patch this (periodic) texture holds at canvas position (row, col) -- used to
    render every anchor cell exactly (real content, no bits consumed) and, for the scattered
    layout's gap cells, as the ground truth candidates are scored against. Wraps modulo the
    texture's own patch grid, so it's well-defined for a canvas of any height, even past one full
    texture period (see memory/wire-protocol.md)."""

    rows_per_period = texture.shape[0] // patch_size
    cols_per_period = texture.shape[1] // patch_size
    return _periodic_extract(texture, (row % rows_per_period) * patch_size, (col % cols_per_period) * patch_size, patch_size)


def _mask_seed(texture: np.ndarray) -> int:
    """A deterministic seed for the anchor mask, derived from the texture's own content -- so
    encode and decode agree without needing the original integer seed threaded through (only the
    regenerated texture array is available at this layer). Not a secrecy boundary: like texture
    choice itself, the anchor mask needs no confidentiality (see memory/wire-protocol.md), so a
    plain non-keyed hash is fine."""

    digest = hashlib.blake2b(texture.tobytes(), digest_size=4).digest()
    return int.from_bytes(digest, "big")


def _anchor_mask(seed: int, period: int, min_distance: float) -> np.ndarray:
    """A (period, period) boolean grid of which patch-grid positions are anchors, via deterministic
    Poisson-disk-style dart-throwing: shuffle every cell with a seeded RNG, accept a cell if it's
    at least min_distance from every already-accepted anchor, until no more qualify. Distance is
    toroidal (wrapped), matching how the mask itself gets tiled modulo its own period for canvases
    taller than one period. The domain is tiny (period^2 cells), so a plain rejection loop -- no
    spatial-acceleration structure -- is fast enough."""

    rng = np.random.default_rng(seed)
    positions = [(row, col) for row in range(period) for col in range(period)]
    order = rng.permutation(len(positions))
    accepted: List[Tuple[int, int]] = []
    mask = np.zeros((period, period), dtype=bool)
    min_distance_sq = min_distance * min_distance

    for index in order:
        row, col = positions[index]
        far_enough = True
        for accepted_row, accepted_col in accepted:
            row_gap = min(abs(row - accepted_row), period - abs(row - accepted_row))
            col_gap = min(abs(col - accepted_col), period - abs(col - accepted_col))
            if row_gap * row_gap + col_gap * col_gap < min_distance_sq:
                far_enough = False
                break
        if far_enough:
            accepted.append((row, col))
            mask[row, col] = True

    return mask


def _is_anchor(mask: np.ndarray, row: int, col: int) -> bool:
    return bool(mask[row % mask.shape[0], col % mask.shape[1]])


def _edge_cost(a: np.ndarray, b: np.ndarray) -> int:
    diff = a.astype(np.int64) - b.astype(np.int64)
    return int(np.sum(diff * diff))


def _weights_from_costs(costs: np.ndarray) -> List[Tuple[int, int]]:
    max_cost = int(costs.max())
    return [(index, int(max_cost - cost) + 1) for index, cost in enumerate(costs)]


def _candidate_weights_scattered(library: PatchLibrary, texture: np.ndarray, row: int, col: int, above: Optional[np.ndarray], left: Optional[np.ndarray]) -> List[Tuple[int, int]]:
    """Weight every library patch by how close a whole-patch match it is to the texture's true
    content at this exact position -- always known, since it's a pure function of position and the
    shared seed, not of anything already placed -- plus its top/left edges against the
    already-resolved neighbors above and to the left, when they exist (never below or right --
    those aren't resolved yet in this raster-order walk). Vectorized over the whole candidate pool
    at once, since the overlapping library can hold thousands of candidates."""

    target = _guide_patch(texture, row, col, library.patch_size).astype(np.int64)
    patches = library.patches_array.astype(np.int64)
    costs = np.sum((patches - target) ** 2, axis=(1, 2, 3))

    if left is not None:
        left_edge = left[:, -1, :].astype(np.int64)
        diff = patches[:, :, 0, :] - left_edge
        costs = costs + np.sum(diff * diff, axis=(1, 2))

    if above is not None:
        above_edge = above[-1, :, :].astype(np.int64)
        diff = patches[:, 0, :, :] - above_edge
        costs = costs + np.sum(diff * diff, axis=(1, 2))

    return _weights_from_costs(costs)


def _candidate_weights_rows(library: PatchLibrary, gap_row: List[np.ndarray], texture: np.ndarray, row: int, col: int) -> List[Tuple[int, int]]:
    """`attractor`'s unchanged mechanism: rank every library patch purely by local edge agreement
    with the seed rows immediately above and below, plus the already-chosen gap patch to its left,
    if any (comparing a wider overlap region instead of just the touching row of pixels was tried
    and measurably made this worse, not better -- see memory/rejected-ideas.md's OVERLAP entry)."""

    above = _guide_patch(texture, row - 1, col, library.patch_size)
    below = _guide_patch(texture, row + 1, col, library.patch_size)
    left = gap_row[col - 1] if col > 0 else None

    costs = []
    for patch in library.patches:
        cost = _edge_cost(patch[0, :, :], above[-1, :, :]) + _edge_cost(patch[-1, :, :], below[0, :, :])
        if left is not None:
            cost += _edge_cost(patch[:, 0, :], left[:, -1, :])
        costs.append(cost)

    return _weights_from_costs(np.array(costs))


def _rows_to_canvas(rows: List[List[np.ndarray]]) -> np.ndarray:
    row_blocks = [np.concatenate(row, axis=1) for row in rows]
    return np.concatenate(row_blocks, axis=0)


def _extract_patch(canvas: np.ndarray, row: int, col: int, patch_size: int) -> np.ndarray:
    r0, c0 = row * patch_size, col * patch_size
    return canvas[r0 : r0 + patch_size, c0 : c0 + patch_size]


def _feather_canvas(canvas: np.ndarray, mask: np.ndarray, patch_size: int, overlap: int) -> np.ndarray:
    """Softens the hard edge at every boundary that touches at least one gap patch, by linearly
        cross-fading an `overlap`-pixel-wide band on the gap side(s) of that boundary toward the
        neighbor's own nearest edge pixels.
    Anchors are never modified -- only a gap patch's own outer
        border is touched, and only that far, so decode's exact match on the interior (core) region is
        unaffected by this pass regardless of how visible the untreated boundary would otherwise be.
        Every gap patch gets every one of its internal edges treated the same way, uniformly, so decode
        doesn't need to know which specific neighbors were anchors versus gaps -- it just always reads
        the core.
    Corners (touched by both an edge blend and its neighboring perpendicular blend) get a
        small compounding effect, an accepted simplification for this first, deliberately thin pass."""

    original = canvas.astype(np.float64)
    blended = original.copy()
    total_rows = canvas.shape[0] // patch_size
    canvas_width = canvas.shape[1] // patch_size

    for row in range(total_rows):
        for col in range(canvas_width - 1):
            left_is_anchor = _is_anchor(mask, row, col)
            right_is_anchor = _is_anchor(mask, row, col + 1)
            if left_is_anchor and right_is_anchor:
                continue
            r0, r1 = row * patch_size, (row + 1) * patch_size
            left_edge = original[r0:r1, col * patch_size + patch_size - 1, :]
            right_edge = original[r0:r1, (col + 1) * patch_size, :]
            for offset in range(overlap):
                weight = (offset + 1) / (overlap + 1)
                if not left_is_anchor:
                    c = col * patch_size + patch_size - overlap + offset
                    blended[r0:r1, c, :] = original[r0:r1, c, :] * (1 - weight) + right_edge * weight
                if not right_is_anchor:
                    c = (col + 1) * patch_size + (overlap - 1 - offset)
                    blended[r0:r1, c, :] = original[r0:r1, c, :] * (1 - weight) + left_edge * weight

    for row in range(total_rows - 1):
        for col in range(canvas_width):
            top_is_anchor = _is_anchor(mask, row, col)
            bottom_is_anchor = _is_anchor(mask, row + 1, col)
            if top_is_anchor and bottom_is_anchor:
                continue
            c0, c1 = col * patch_size, (col + 1) * patch_size
            top_edge = original[row * patch_size + patch_size - 1, c0:c1, :]
            bottom_edge = original[(row + 1) * patch_size, c0:c1, :]
            for offset in range(overlap):
                weight = (offset + 1) / (overlap + 1)
                if not top_is_anchor:
                    r = row * patch_size + patch_size - overlap + offset
                    blended[r, c0:c1, :] = blended[r, c0:c1, :] * (1 - weight) + bottom_edge * weight
                if not bottom_is_anchor:
                    r = (row + 1) * patch_size + (overlap - 1 - offset)
                    blended[r, c0:c1, :] = blended[r, c0:c1, :] * (1 - weight) + top_edge * weight

    return np.clip(blended, 0, 255).astype(np.uint8)


def _encode_scattered(data: bytes, texture: np.ndarray, patch_size: int, canvas_width: int) -> np.ndarray:
    library = PatchLibrary(texture, patch_size, stride=DEFAULT_CANDIDATE_STRIDE, min_distance_sq=MIN_CANDIDATE_DISTANCE_SQ)
    mask = _anchor_mask(_mask_seed(texture), texture.shape[1] // patch_size, MIN_ANCHOR_DISTANCE)
    cursor = BitCursor(data)
    rows: List[List[np.ndarray]] = []
    low, high, width = 0, 1, 1
    row_index = 0

    while True:
        row_patches: List[np.ndarray] = []
        for col in range(canvas_width):
            if _is_anchor(mask, row_index, col):
                row_patches.append(_guide_patch(texture, row_index, col, patch_size))
                continue

            above = rows[row_index - 1][col] if row_index > 0 else None
            left = row_patches[col - 1] if col > 0 else None
            candidates = _candidate_weights_scattered(library, texture, row_index, col, above, left)

            if cursor.remaining() <= 0:
                best_index = max(candidates, key=lambda iw: iw[1])[0]
                row_patches.append(library.patches[best_index])
                continue

            budget = cursor.remaining()
            ranges, low, high, width = candidate_ranges(low, high, width, candidates, budget)
            peeked = cursor.peek(width)
            index, low, high = next((i, lo, hi) for i, lo, hi in ranges if lo <= peeked <= hi)
            row_patches.append(library.patches[index])

            common = common_leading_bits(low, high, width)
            if common:
                cursor.consume(min(common, cursor.remaining()))
                low, high, width = strip_top_bits(low, high, width, common)

        rows.append(row_patches)
        row_index += 1
        if cursor.remaining() <= 0:
            break

    canvas = _rows_to_canvas(rows)
    return _feather_canvas(canvas, mask, patch_size, SEAM_OVERLAP)


def _decode_scattered(canvas: np.ndarray, texture: np.ndarray, length: int, patch_size: int) -> bytes:
    library = PatchLibrary(texture, patch_size, stride=DEFAULT_CANDIDATE_STRIDE, min_distance_sq=MIN_CANDIDATE_DISTANCE_SQ)
    canvas_width = canvas.shape[1] // patch_size
    total_rows = canvas.shape[0] // patch_size
    mask = _anchor_mask(_mask_seed(texture), texture.shape[1] // patch_size, MIN_ANCHOR_DISTANCE)

    accumulator = BitAccumulator(length)
    low, high, width = 0, 1, 1
    rows: List[List[np.ndarray]] = []

    for row_index in range(total_rows):
        row_patches: List[np.ndarray] = []
        for col in range(canvas_width):
            raw_patch = _extract_patch(canvas, row_index, col, patch_size)

            if _is_anchor(mask, row_index, col):
                row_patches.append(raw_patch)  # anchors are never touched by feathering; exact already.
                continue

            # Gap patches may have had their border softened by _feather_canvas, so identify them
            # by their (untouched) core -- then use the library's pristine copy, not the raw
            # (possibly blended) canvas pixels, for every later cell's above/left reference, so
            # decode's scoring stays bit-for-bit consistent with what encode actually used.
            actual_index = library.index_of_core(raw_patch, SEAM_OVERLAP)
            resolved_patch = library.patches[actual_index]
            row_patches.append(resolved_patch)

            if accumulator.done():
                continue

            above = rows[row_index - 1][col] if row_index > 0 else None
            left = row_patches[col - 1] if col > 0 else None
            candidates = _candidate_weights_scattered(library, texture, row_index, col, above, left)
            ranges, low, high, width = candidate_ranges(low, high, width, candidates, accumulator.remaining())
            match: Optional[Tuple[int, int]] = next(((lo, hi) for i, lo, hi in ranges if i == actual_index), None)
            if match is None:
                raise ValueError(f"Patch at (row={row_index}, col={col}) is not a valid candidate at this point in the synthesis walk!")
            low, high = match

            common = common_leading_bits(low, high, width)
            if common:
                accumulator.append(low, width, common)
                low, high, width = strip_top_bits(low, high, width, common)

        rows.append(row_patches)
        if accumulator.done():
            break

    return accumulator.finish()


def _encode_rows(data: bytes, texture: np.ndarray, patch_size: int, canvas_width: int) -> np.ndarray:
    """`attractor`'s unchanged mechanism: a seed row, then alternating gap/seed row pairs until
    `data` is fully consumed, padded out to a full row with best-match (non-bit-consuming) filler
    if it runs out mid-row, so the result is always rectangular."""

    library = PatchLibrary(texture, patch_size)
    cursor = BitCursor(data)
    rows: List[List[np.ndarray]] = [[_guide_patch(texture, 0, col, patch_size) for col in range(canvas_width)]]
    low, high, width = 0, 1, 1
    row_index = 1

    while cursor.remaining() > 0:
        gap_row: List[np.ndarray] = []
        for col in range(canvas_width):
            candidates = _candidate_weights_rows(library, gap_row, texture, row_index, col)
            if cursor.remaining() <= 0:
                best_index = max(candidates, key=lambda iw: iw[1])[0]
                gap_row.append(library.patches[best_index])
                continue

            budget = cursor.remaining()
            ranges, low, high, width = candidate_ranges(low, high, width, candidates, budget)
            peeked = cursor.peek(width)
            index, low, high = next((i, lo, hi) for i, lo, hi in ranges if lo <= peeked <= hi)
            gap_row.append(library.patches[index])

            common = common_leading_bits(low, high, width)
            if common:
                cursor.consume(min(common, cursor.remaining()))
                low, high, width = strip_top_bits(low, high, width, common)

        rows.append(gap_row)
        rows.append([_guide_patch(texture, row_index + 1, col, patch_size) for col in range(canvas_width)])
        row_index += 2

    return _rows_to_canvas(rows)


def _decode_rows(canvas: np.ndarray, texture: np.ndarray, length: int, patch_size: int) -> bytes:
    """Invert `_encode_rows`."""

    library = PatchLibrary(texture, patch_size)
    canvas_width = canvas.shape[1] // patch_size
    total_rows = canvas.shape[0] // patch_size

    accumulator = BitAccumulator(length)
    low, high, width = 0, 1, 1
    row_index = 1

    while row_index < total_rows and not accumulator.done():
        gap_row: List[np.ndarray] = []
        for col in range(canvas_width):
            patch = _extract_patch(canvas, row_index, col, patch_size)
            if accumulator.done():
                gap_row.append(patch)
                continue

            candidates = _candidate_weights_rows(library, gap_row, texture, row_index, col)
            ranges, low, high, width = candidate_ranges(low, high, width, candidates, accumulator.remaining())
            actual_index = library.index_of(patch)
            match: Optional[Tuple[int, int]] = next(((lo, hi) for i, lo, hi in ranges if i == actual_index), None)
            if match is None:
                raise ValueError(f"Patch at (row={row_index}, col={col}) is not a valid candidate at this point in the synthesis walk!")
            low, high = match
            gap_row.append(patch)

            common = common_leading_bits(low, high, width)
            if common:
                accumulator.append(low, width, common)
                low, high, width = strip_top_bits(low, high, width, common)

        row_index += 2

    return accumulator.finish()


def encode(data: bytes, texture: np.ndarray, patch_size: int = DEFAULT_PATCH_SIZE, canvas_width: int = DEFAULT_CANVAS_WIDTH, position_guided: bool = True) -> np.ndarray:
    """Encrypt-then-call: `data` should already be ciphertext. Returns the synthesized canvas as
    an `(H, W, 3)` `uint8` array, via the scattered-anchor layout (`position_guided=True`) or the
    row-alternating layout (`position_guided=False`, `attractor` only) -- see the module docstring.
    `canvas_width` must equal `texture.shape[1] // patch_size`, or positions stop corresponding to
    real texture content (see `DEFAULT_TEXTURE_SIZE`'s docstring)."""

    if position_guided:
        return _encode_scattered(data, texture, patch_size, canvas_width)
    return _encode_rows(data, texture, patch_size, canvas_width)


def decode(canvas: np.ndarray, texture: np.ndarray, length: int, patch_size: int = DEFAULT_PATCH_SIZE, position_guided: bool = True) -> bytes:
    """Invert `encode`: recover exactly `length` bytes from a synthesized canvas."""

    if position_guided:
        return _decode_scattered(canvas, texture, length, patch_size)
    return _decode_rows(canvas, texture, length, patch_size)


def _patch_to_data_uri(patch: np.ndarray) -> str:
    buffer = io.BytesIO()
    Image.fromarray(patch).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def to_svg(canvas: np.ndarray, patch_size: int = DEFAULT_PATCH_SIZE) -> str:
    """Render `canvas` as an SVG document: each distinct tile is embedded once (as a base64 PNG)
    in `<defs>`, and the grid references them via `<use>` -- much smaller than embedding a full
    raster tile per cell, and keeps the markup genuinely tile-structured rather than a PNG image
    wrapped in an `<svg>` tag."""

    height, width = canvas.shape[0], canvas.shape[1]
    rows, cols = height // patch_size, width // patch_size

    tile_ids: Dict[bytes, int] = {}
    defs: List[str] = []
    uses: List[str] = []
    for row in range(rows):
        for col in range(cols):
            tile = _extract_patch(canvas, row, col, patch_size)
            key = tile.tobytes()
            if key not in tile_ids:
                tile_ids[key] = len(tile_ids)
                defs.append(f'<image id="t{tile_ids[key]}" width="{patch_size}" height="{patch_size}" href="{_patch_to_data_uri(tile)}"/>')
            uses.append(f'<use href="#t{tile_ids[key]}" x="{col * patch_size}" y="{row * patch_size}"/>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges">\n'
        f"<defs>\n" + "\n".join(defs) + "\n</defs>\n" + "\n".join(uses) + "\n</svg>\n"
    )


def save_svg(canvas: np.ndarray, path: str, patch_size: int = DEFAULT_PATCH_SIZE) -> None:
    Path(path).write_text(to_svg(canvas, patch_size), encoding="utf-8")


def _canvas_to_png(canvas: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(canvas).save(buffer, format="PNG")
    return buffer.getvalue()


def _png_to_canvas(data: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(data)).convert("RGB"))


class ImageEncoding(ChunkEncoding):
    """
    Wraps this module's patch-synthesis codec as a `ChunkEncoding`: `encode_atoms` yields exactly
    **one atom, the whole synthesized image** (PNG-encoded -- verified bit-exact round-trip through
    Pillow for this module's canvas arrays), rather than many small pieces. One atom always fills
    exactly one wire chunk, so `pack_hyperchunk` naturally produces `[header, one big chunk]` for an
    image hyperslice -- the "one hyperslice, one image" MMS-attachment shape, achieved by reusing
    `chunking.py`'s existing header/ack/retry machinery unchanged rather than a second delivery
    path, as long as `chunk_size` is set to an MMS-scale budget instead of an SMS one.

    Each texture flavor gets its own identifier/instance (`SYNTHESIS_VALUE_NOISE` etc. below) --
    both because that's the natural way to expose "which flavor" at all (the same mechanism
    `PLAIN`/`BASE64`/`MARKOV_ENG`/`MARKOV_RUS` already use), and because it costs nothing extra: the
    header's `encoding` field already exists regardless of which `ChunkEncoding` is chosen. The
    source texture's *seed*, unlike its flavor, needs to vary every call rather than just per
    conversation, so it's derived from `nonce` (the hyperslice's own AEAD nonce, already unique per
    hyperchunk) instead -- real per-message variety at zero extra wire cost, and safe precisely
    because texture choice was already established to need no confidentiality (memory/wire-protocol.md):
    reusing the nonce for this second, unrelated, non-secret purpose doesn't create an AEAD
    nonce-reuse problem, since nothing about AEAD security depends on the nonce being unpredictable
    or single-purpose, only unique -- which it already is.
    """

    def __init__(self, flavor: str, identifier: hyperchunk_pb2.ChunkEncoding, position_guided: bool = True) -> None:
        self.flavor = flavor
        self.identifier = identifier
        self.position_guided = position_guided

    def encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]:
        seed = int.from_bytes(nonce[:4], "big")
        texture = texture_by_name(self.flavor, size=DEFAULT_TEXTURE_SIZE, seed=seed)
        canvas = encode(data, texture, position_guided=self.position_guided)
        yield _canvas_to_png(canvas)

    def decode(self, encoded: bytes, length: int, nonce: bytes) -> bytes:
        seed = int.from_bytes(nonce[:4], "big")
        texture = texture_by_name(self.flavor, size=DEFAULT_TEXTURE_SIZE, seed=seed)
        canvas = _png_to_canvas(encoded)
        return decode(canvas, texture, length, position_guided=self.position_guided)


SYNTHESIS_VALUE_NOISE = ImageEncoding("value_noise", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_VALUE_NOISE)
SYNTHESIS_VORONOI = ImageEncoding("voronoi", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_VORONOI)
SYNTHESIS_REACTION_DIFFUSION = ImageEncoding("reaction_diffusion", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_REACTION_DIFFUSION)
# attractor has no exploitable 2-D positional structure (a sparse density histogram of a chaotic
# orbit, not a spatially periodic field -- confirmed by direct tiling tests, see
# memory/rejected-ideas.md): it keeps the original row-alternating, local-edge-only mechanism.
SYNTHESIS_ATTRACTOR = ImageEncoding("attractor", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_ATTRACTOR, position_guided=False)
