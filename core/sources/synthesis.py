"""
Disguises ciphertext as an abstract, patterned image via reversible patch-based texture
synthesis, using the same arithmetic coder (`sources/arithmetic.py`) built for
`sources/markov.py`'s text disguise -- adapted from Wu & Wang's "Steganography Using Reversible
Texture Synthesis" (IEEE TIP, 2015), with two deliberate departures from their design (see
design-decisions.md for the full story of why):

- Wu & Wang scatter whole source patches at arbitrary positions and fill irregularly-shaped gaps
  between them; this module uses a fixed, regular layout instead -- alternating **seed rows**
  (whole, untouched patches from the source texture, placed by a deterministic rule, carrying no
  secret data) and **gap rows** (synthesized, one patch at a time, secret-bit-driven). Simpler to
  reason about and implement, at the cost of being less space-efficient than an optimal irregular
  packing.
- Wu & Wang also recover the exact original source texture from the stego image, because in their
  setting the texture itself is secret content. Here the source texture is a public, regenerable
  "codebook" (see `sources/textures.py`) that both ends already have, so that whole recovery
  mechanism -- and the index-table bookkeeping it needs -- is simply not needed and isn't built.

Every row of the canvas, seed or gap, corresponds to a real row of one continuous, periodic
source texture (`row % texture_height_in_patches`, see `_guide_patch`) -- not to an arbitrary
placeholder. Seed rows render that row's true content exactly. For three of the four texture
flavors (`position_guided=True` -- everything except `attractor`), each **gap row** cell is filled
by ranking every patch in the source texture's patch library by how close it is to the *true*
patch this same periodic texture holds at that exact position, plus its left edge against the
already-chosen gap patch to its left, if any -- so a gap patch is always pulled toward the real
image that would be there anyway, which is what lets large-scale structure (a Voronoi cell, a
reaction-diffusion tube) survive across a whole row, not just at one edge. `attractor` has no
exploitable 2-D positional structure (confirmed by direct tiling tests -- see
`memory/rejected-ideas.md`), so it keeps the original scheme instead: ranking by edge match against
the seed rows immediately above and below, plus the left neighbor. Match quality (sum of squared
pixel differences) becomes an integer weight -- exact integer arithmetic throughout, never floating
point, for the same reason `sources/markov.py` avoids it: the arithmetic coder needs bit-exact
agreement between encode and decode on any device. The arithmetic coder then picks which patch to
place the same way it picks words in the text case: secret bits select among the weighted
candidates, not "the best match."

Known limitations, worth a second look independently of this module:

- The regular seed/gap row layout is a visible artifact once you know to look for it (every other
  row is literally untouched source texture). Wu & Wang's irregular scatter hides this better but
  is substantially more complex to implement; not attempted here.
- `attractor`'s gap rows are still purely local (immediate edge pixels only), so its large-scale
  behavior is unchanged from the original design -- it was already adequate under the local-only
  cost function, unlike `voronoi`/`reaction_diffusion`, which is why it wasn't included in the
  position-guided mechanism rather than needing a fallback for a regression.
"""

import base64
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
# position in the texture (see memory/wire-protocol.md and memory/rejected-ideas.md).
DEFAULT_TEXTURE_SIZE = DEFAULT_CANVAS_WIDTH * DEFAULT_PATCH_SIZE


class PatchLibrary:
    """The fixed palette of candidate patches a source texture is divided into."""

    def __init__(self, texture: np.ndarray, patch_size: int) -> None:
        size = texture.shape[0]
        if texture.shape[0] != texture.shape[1] or size % patch_size != 0:
            raise ValueError(f"Texture must be square with a side length that's a multiple of patch_size ({patch_size})!")

        self.patch_size = patch_size
        self.patches: List[np.ndarray] = []
        lookup: Dict[bytes, int] = {}
        for row in range(0, size, patch_size):
            for col in range(0, size, patch_size):
                patch = texture[row : row + patch_size, col : col + patch_size].copy()
                key = patch.tobytes()
                if key in lookup:
                    continue  # flat/repeated regions (e.g. Voronoi cell interiors) can duplicate; skip.
                lookup[key] = len(self.patches)
                self.patches.append(patch)

        if len(self.patches) < 2:
            raise ValueError("Source texture yields fewer than 2 distinct patches; pick a larger or more varied texture!")
        self._lookup = lookup

    def __len__(self) -> int:
        return len(self.patches)

    def index_of(self, patch: np.ndarray) -> int:
        try:
            return self._lookup[patch.tobytes()]
        except KeyError:
            raise ValueError("Patch doesn't match any entry in this source texture's patch library!") from None


def _guide_patch(texture: np.ndarray, row: int, col: int, patch_size: int) -> np.ndarray:
    """The literal patch this (periodic) texture holds at canvas position (row, col) -- used to
    render every seed row exactly (real content, no bits consumed) and, for the three
    position-guided flavors, as the ground truth gap-row candidates are scored against. Wraps
    modulo the texture's own patch grid, so it's well-defined for a canvas of any height, even
    past one full texture period (see memory/wire-protocol.md)."""

    rows_per_period = texture.shape[0] // patch_size
    cols_per_period = texture.shape[1] // patch_size
    return _extract_patch(texture, row % rows_per_period, col % cols_per_period, patch_size)


def _edge_cost(a: np.ndarray, b: np.ndarray) -> int:
    diff = a.astype(np.int64) - b.astype(np.int64)
    return int(np.sum(diff * diff))


def _candidate_weights(library: PatchLibrary, gap_row: List[np.ndarray], texture: np.ndarray, row: int, col: int, position_guided: bool) -> List[Tuple[int, int]]:
    """Weight every library patch by how well it would fill gap-row position (row, col), plus its
    left edge against the already-chosen gap patch to its left, if any (comparing a wider overlap
    region instead of just the touching row of pixels was tried and measurably made this worse,
    not better -- see memory/rejected-ideas.md's OVERLAP entry).

    Position-guided flavors (`position_guided=True`) score the *whole patch* against the true
    content this periodic texture holds at exactly this position -- always known, since it's a
    pure function of position and the shared seed, not of anything already placed -- which is what
    lets large-scale structure (a Voronoi cell, a reaction-diffusion tube) survive: every gap
    patch is pulled toward the real image that would be there anyway, not just towards agreeing
    with its immediate neighbors. The one flavor without exploitable positional structure
    (`attractor`) keeps the original, purely local edge-vs-neighboring-seed-rows cost instead."""

    left = gap_row[col - 1] if col > 0 else None
    patch_size = library.patch_size

    costs = []
    if position_guided:
        target = _guide_patch(texture, row, col, patch_size)
        for patch in library.patches:
            cost = _edge_cost(patch, target)
            if left is not None:
                cost += _edge_cost(patch[:, 0, :], left[:, -1, :])
            costs.append(cost)
    else:
        above = _guide_patch(texture, row - 1, col, patch_size)
        below = _guide_patch(texture, row + 1, col, patch_size)
        for patch in library.patches:
            cost = _edge_cost(patch[0, :, :], above[-1, :, :]) + _edge_cost(patch[-1, :, :], below[0, :, :])
            if left is not None:
                cost += _edge_cost(patch[:, 0, :], left[:, -1, :])
            costs.append(cost)

    max_cost = max(costs)
    return [(index, (max_cost - cost) + 1) for index, cost in enumerate(costs)]


def _rows_to_canvas(rows: List[List[np.ndarray]]) -> np.ndarray:
    row_blocks = [np.concatenate(row, axis=1) for row in rows]
    return np.concatenate(row_blocks, axis=0)


def _extract_patch(canvas: np.ndarray, row: int, col: int, patch_size: int) -> np.ndarray:
    r0, c0 = row * patch_size, col * patch_size
    return canvas[r0 : r0 + patch_size, c0 : c0 + patch_size]


def encode(data: bytes, texture: np.ndarray, patch_size: int = DEFAULT_PATCH_SIZE, canvas_width: int = DEFAULT_CANVAS_WIDTH, position_guided: bool = True) -> np.ndarray:
    """Encrypt-then-call: `data` should already be ciphertext. Returns the synthesized canvas as
    an `(H, W, 3)` `uint8` array -- a seed row, then alternating gap/seed row pairs until `data`
    is fully consumed, padded out to a full row with best-match (non-bit-consuming) filler if it
    runs out mid-row, so the result is always rectangular. `canvas_width` must equal
    `texture.shape[1] // patch_size`, or seed rows stop corresponding to real texture positions
    (see `DEFAULT_TEXTURE_SIZE`'s docstring)."""

    library = PatchLibrary(texture, patch_size)
    cursor = BitCursor(data)
    rows: List[List[np.ndarray]] = [[_guide_patch(texture, 0, col, patch_size) for col in range(canvas_width)]]
    low, high, width = 0, 1, 1
    row_index = 1

    while cursor.remaining() > 0:
        gap_row: List[np.ndarray] = []
        for col in range(canvas_width):
            candidates = _candidate_weights(library, gap_row, texture, row_index, col, position_guided)
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


def decode(canvas: np.ndarray, texture: np.ndarray, length: int, patch_size: int = DEFAULT_PATCH_SIZE, position_guided: bool = True) -> bytes:
    """Invert `encode`: recover exactly `length` bytes from a synthesized canvas."""

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

            candidates = _candidate_weights(library, gap_row, texture, row_index, col, position_guided)
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
# orbit, not a spatially-generated field -- confirmed by direct tiling tests, see
# memory/rejected-ideas.md): it keeps the original local-edge-only cost function.
SYNTHESIS_ATTRACTOR = ImageEncoding("attractor", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_ATTRACTOR, position_guided=False)
