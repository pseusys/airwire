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

How embedding works: each **gap row** cell is filled by ranking every patch in the source
texture's patch library by how well its edges would blend with its neighbors -- the seed rows
immediately above and below (always known, since seed-row content is a fixed function of position,
not of anything already placed) and the already-chosen gap patch to its left, if any. Match quality
(sum of squared pixel differences on the shared edges) becomes an integer weight -- exact
integer arithmetic throughout, never floating point, for the same reason `sources/markov.py`
avoids it: the arithmetic coder needs bit-exact agreement between encode and decode on any device.
The arithmetic coder then picks which patch to place the same way it picks words in the text
case: secret bits select among the weighted candidates, not "the best match."

Known limitations, worth a second look independently of this module:

- The regular seed/gap row layout is a visible artifact once you know to look for it (every other
  row is literally untouched source texture). Wu & Wang's irregular scatter hides this better but
  is substantially more complex to implement; not attempted here.
- Large-scale, long-range structure (e.g. a Voronoi diagram's big flat cells, a reaction-diffusion
  pattern's continuous tubes) does not survive synthesis well, because the blend cost function is
  purely local (immediate edge pixels only) and gap rows are only one patch tall -- there's no
  mechanism to keep a multi-patch-wide feature coherent across a gap row. Locally-stationary
  textures (value noise) hold up much better. A future iteration could widen the comparison beyond
  a single edge, or shrink gap rows relative to seed rows, rather than changing the coder itself.
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
DEFAULT_TEXTURE_SIZE = 64


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


def _seed_index(seed_ordinal: int, col: int, canvas_width: int, library_size: int) -> int:
    return (seed_ordinal * canvas_width + col) % library_size


def _seed_patch(library: PatchLibrary, seed_ordinal: int, col: int, canvas_width: int) -> np.ndarray:
    return library.patches[_seed_index(seed_ordinal, col, canvas_width, len(library))]


def _edge_cost(a: np.ndarray, b: np.ndarray) -> int:
    diff = a.astype(np.int64) - b.astype(np.int64)
    return int(np.sum(diff * diff))


def _candidate_weights(library: PatchLibrary, gap_row: List[np.ndarray], row: int, col: int, canvas_width: int) -> List[Tuple[int, int]]:
    """Weight every library patch by how well it would blend into gap-row position (row, col):
    its top/bottom edges against the seed rows above and below (always known -- seed content is a
    fixed function of position, never of anything already placed) and its left edge against the
    already-chosen gap patch to its left, if any. Comparing a wider overlap region instead of just
    the touching row of pixels was tried and measurably made this worse, not better -- see design
    decision #4 for the measurements and the reasoning for why."""

    above = _seed_patch(library, (row - 1) // 2, col, canvas_width)
    below = _seed_patch(library, (row + 1) // 2, col, canvas_width)
    left = gap_row[col - 1] if col > 0 else None

    costs = []
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


def encode(data: bytes, texture: np.ndarray, patch_size: int = DEFAULT_PATCH_SIZE, canvas_width: int = DEFAULT_CANVAS_WIDTH) -> np.ndarray:
    """Encrypt-then-call: `data` should already be ciphertext. Returns the synthesized canvas as
    an `(H, W, 3)` `uint8` array -- a seed row, then alternating gap/seed row pairs until `data`
    is fully consumed, padded out to a full row with best-match (non-bit-consuming) filler if it
    runs out mid-row, so the result is always rectangular."""

    library = PatchLibrary(texture, patch_size)
    cursor = BitCursor(data)
    rows: List[List[np.ndarray]] = [[_seed_patch(library, 0, col, canvas_width) for col in range(canvas_width)]]
    low, high, width = 0, 1, 1
    seed_ordinal, row_index = 1, 1

    while cursor.remaining() > 0:
        gap_row: List[np.ndarray] = []
        for col in range(canvas_width):
            candidates = _candidate_weights(library, gap_row, row_index, col, canvas_width)
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
        rows.append([_seed_patch(library, seed_ordinal, col, canvas_width) for col in range(canvas_width)])
        seed_ordinal += 1
        row_index += 2

    return _rows_to_canvas(rows)


def decode(canvas: np.ndarray, texture: np.ndarray, length: int, patch_size: int = DEFAULT_PATCH_SIZE) -> bytes:
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

            candidates = _candidate_weights(library, gap_row, row_index, col, canvas_width)
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
    because texture choice was already established to need no confidentiality (design decision #4):
    reusing the nonce for this second, unrelated, non-secret purpose doesn't create an AEAD
    nonce-reuse problem, since nothing about AEAD security depends on the nonce being unpredictable
    or single-purpose, only unique -- which it already is.
    """

    def __init__(self, flavor: str, identifier: hyperchunk_pb2.ChunkEncoding) -> None:
        self.flavor = flavor
        self.identifier = identifier

    def encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]:
        seed = int.from_bytes(nonce[:4], "big")
        texture = texture_by_name(self.flavor, size=DEFAULT_TEXTURE_SIZE, seed=seed)
        canvas = encode(data, texture)
        yield _canvas_to_png(canvas)

    def decode(self, encoded: bytes, length: int, nonce: bytes) -> bytes:
        seed = int.from_bytes(nonce[:4], "big")
        texture = texture_by_name(self.flavor, size=DEFAULT_TEXTURE_SIZE, seed=seed)
        canvas = _png_to_canvas(encoded)
        return decode(canvas, texture, length)


SYNTHESIS_VALUE_NOISE = ImageEncoding("value_noise", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_VALUE_NOISE)
SYNTHESIS_VORONOI = ImageEncoding("voronoi", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_VORONOI)
SYNTHESIS_REACTION_DIFFUSION = ImageEncoding("reaction_diffusion", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_REACTION_DIFFUSION)
SYNTHESIS_ATTRACTOR = ImageEncoding("attractor", hyperchunk_pb2.ChunkEncoding.SYNTHESIS_ATTRACTOR)
