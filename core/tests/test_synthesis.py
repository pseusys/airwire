from pathlib import Path
from secrets import token_bytes

import numpy as np
import pytest

from sources import synthesis
from sources.textures import value_noise

SAMPLES = [b"", b"\x00", b"\xff", token_bytes(1), token_bytes(20), token_bytes(150)]


@pytest.fixture(scope="module")
def texture() -> np.ndarray:
    return value_noise(synthesis.DEFAULT_TEXTURE_SIZE, seed=1)


@pytest.mark.parametrize("data", SAMPLES)
def test_round_trip(data: bytes, texture: np.ndarray) -> None:
    canvas = synthesis.encode(data, texture)
    recovered = synthesis.decode(canvas, texture, len(data))
    assert recovered == data


def test_encode_is_deterministic(texture: np.ndarray) -> None:
    data = token_bytes(50)
    first = synthesis.encode(data, texture)
    second = synthesis.encode(data, texture)
    assert np.array_equal(first, second)


def test_different_inputs_produce_different_canvases(texture: np.ndarray) -> None:
    a = synthesis.encode(token_bytes(50), texture)
    b = synthesis.encode(token_bytes(50), texture)
    assert not np.array_equal(a, b)


def test_canvas_is_rectangular_and_correct_width(texture: np.ndarray) -> None:
    canvas = synthesis.encode(token_bytes(37), texture)
    assert canvas.shape[1] == synthesis.DEFAULT_CANVAS_WIDTH * synthesis.DEFAULT_PATCH_SIZE
    assert canvas.shape[0] % synthesis.DEFAULT_PATCH_SIZE == 0


def test_empty_data_produces_a_single_seed_row(texture: np.ndarray) -> None:
    canvas = synthesis.encode(b"", texture)
    assert canvas.shape[0] == synthesis.DEFAULT_PATCH_SIZE


def test_decode_rejects_a_patch_not_in_the_library(texture: np.ndarray) -> None:
    data = token_bytes(30)
    canvas = synthesis.encode(data, texture)
    tampered = canvas.copy()

    # Find a gap cell (not an anchor) to corrupt -- anchor content isn't validated on decode by
    # design (same as seed-row content in the row-alternating mechanism): it's trusted and used
    # as-is for neighboring gap cells' cost computation, never checked against the guide texture.
    period = texture.shape[1] // synthesis.DEFAULT_PATCH_SIZE
    mask = synthesis._anchor_mask(synthesis._mask_seed(texture), period, synthesis.MIN_ANCHOR_DISTANCE)
    total_rows = canvas.shape[0] // synthesis.DEFAULT_PATCH_SIZE
    row, col = next((r, c) for r in range(total_rows) for c in range(synthesis.DEFAULT_CANVAS_WIDTH) if not synthesis._is_anchor(mask, r, c))

    # Corrupt a pixel in the patch's core (not its outer SEAM_OVERLAP-pixel border, which
    # _feather_canvas deliberately modifies and decode deliberately ignores when matching).
    r0, c0 = row * synthesis.DEFAULT_PATCH_SIZE, col * synthesis.DEFAULT_PATCH_SIZE
    center = synthesis.DEFAULT_PATCH_SIZE // 2
    tampered[r0 + center, c0 + center, 0] ^= 0xFF
    with pytest.raises(ValueError):
        synthesis.decode(tampered, texture, len(data))


def test_anchor_mask_is_deterministic_and_periodic() -> None:
    mask_a = synthesis._anchor_mask(seed=7, period=16, min_distance=synthesis.MIN_ANCHOR_DISTANCE)
    mask_b = synthesis._anchor_mask(seed=7, period=16, min_distance=synthesis.MIN_ANCHOR_DISTANCE)
    assert np.array_equal(mask_a, mask_b)
    assert mask_a.shape == (16, 16)
    # _is_anchor wraps modulo the mask's own period, so a position many periods out still resolves.
    assert synthesis._is_anchor(mask_a, 3, 5) == synthesis._is_anchor(mask_a, 3 + 16 * 4, 5 + 16 * 7)


def test_anchor_mask_density_and_spacing() -> None:
    # No two anchors closer than MIN_ANCHOR_DISTANCE (toroidal), and density lands in a sane
    # band -- not empty, not clumped, not exactly the old row design's 50% (see the module's
    # own docstring and the 2026-09-09 CHANGELOG.md entry for why this is expected to differ).
    period = 16
    for seed in range(5):
        mask = synthesis._anchor_mask(seed, period, synthesis.MIN_ANCHOR_DISTANCE)
        anchors = list(zip(*np.nonzero(mask)))
        assert 0.25 < len(anchors) / mask.size < 0.5
        for i, (row_a, col_a) in enumerate(anchors):
            for row_b, col_b in anchors[i + 1 :]:
                row_gap = min(abs(row_a - row_b), period - abs(row_a - row_b))
                col_gap = min(abs(col_a - col_b), period - abs(col_a - col_b))
                assert row_gap * row_gap + col_gap * col_gap >= synthesis.MIN_ANCHOR_DISTANCE**2


def test_patch_library_rejects_non_square_texture() -> None:
    bad = np.zeros((32, 40, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        synthesis.PatchLibrary(bad, patch_size=8)


def test_patch_library_rejects_size_not_a_multiple_of_patch_size() -> None:
    bad = np.zeros((30, 30, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        synthesis.PatchLibrary(bad, patch_size=8)


def test_patch_library_rejects_too_uniform_a_texture() -> None:
    flat = np.full((32, 32, 3), 128, dtype=np.uint8)
    with pytest.raises(ValueError):
        synthesis.PatchLibrary(flat, patch_size=8)


def test_patch_library_min_distance_sq_shrinks_the_library(texture: np.ndarray) -> None:
    unconstrained = synthesis.PatchLibrary(texture, synthesis.DEFAULT_PATCH_SIZE)
    constrained = synthesis.PatchLibrary(texture, synthesis.DEFAULT_PATCH_SIZE, min_distance_sq=synthesis.MIN_CANDIDATE_DISTANCE_SQ)
    assert len(constrained) <= len(unconstrained)
    assert len(constrained) >= 2


def test_patch_library_min_distance_sq_guarantees_separation(texture: np.ndarray) -> None:
    library = synthesis.PatchLibrary(texture, synthesis.DEFAULT_PATCH_SIZE, min_distance_sq=synthesis.MIN_CANDIDATE_DISTANCE_SQ)
    patches = library.patches_array.astype(np.int64)
    for i in range(len(patches)):
        for j in range(i + 1, len(patches)):
            distance_sq = int(np.sum((patches[i] - patches[j]) ** 2))
            assert distance_sq >= synthesis.MIN_CANDIDATE_DISTANCE_SQ


def test_patch_library_tracks_patch_origins(texture: np.ndarray) -> None:
    library = synthesis.PatchLibrary(texture, synthesis.DEFAULT_PATCH_SIZE)
    assert len(library.patch_origins) == len(library.patches)
    for (row, col), patch in zip(library.patch_origins, library.patches):
        assert np.array_equal(synthesis._periodic_extract(texture, row, col, synthesis.DEFAULT_PATCH_SIZE), patch)


def test_patch_library_index_of_core_matches_full_index(texture: np.ndarray) -> None:
    library = synthesis.PatchLibrary(texture, synthesis.DEFAULT_PATCH_SIZE, min_distance_sq=synthesis.MIN_CANDIDATE_DISTANCE_SQ)
    for index, patch in enumerate(library.patches):
        assert library.index_of_core(patch, synthesis.SEAM_OVERLAP) == index


def test_patch_library_index_of_core_rejects_unknown_core(texture: np.ndarray) -> None:
    library = synthesis.PatchLibrary(texture, synthesis.DEFAULT_PATCH_SIZE, min_distance_sq=synthesis.MIN_CANDIDATE_DISTANCE_SQ)
    bogus = np.zeros((synthesis.DEFAULT_PATCH_SIZE, synthesis.DEFAULT_PATCH_SIZE, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        library.index_of_core(bogus, synthesis.SEAM_OVERLAP)


def test_feather_canvas_never_modifies_anchor_pixels(texture: np.ndarray) -> None:
    canvas = synthesis.encode(token_bytes(80), texture)
    period = texture.shape[1] // synthesis.DEFAULT_PATCH_SIZE
    mask = synthesis._anchor_mask(synthesis._mask_seed(texture), period, synthesis.MIN_ANCHOR_DISTANCE)
    total_rows = canvas.shape[0] // synthesis.DEFAULT_PATCH_SIZE
    for row in range(total_rows):
        for col in range(synthesis.DEFAULT_CANVAS_WIDTH):
            if not synthesis._is_anchor(mask, row, col):
                continue
            actual = synthesis._extract_patch(canvas, row, col, synthesis.DEFAULT_PATCH_SIZE)
            expected = synthesis._guide_patch(texture, row, col, synthesis.DEFAULT_PATCH_SIZE)
            assert np.array_equal(actual, expected)


def test_feather_canvas_softens_at_least_one_gap_to_gap_boundary(texture: np.ndarray) -> None:
    # Not every boundary is guaranteed to change (two adjacent patches could coincidentally
    # already agree at their shared edge), but across a large-enough canvas at least one should.
    canvas = synthesis.encode(token_bytes(400), texture)
    library = synthesis.PatchLibrary(texture, synthesis.DEFAULT_PATCH_SIZE, min_distance_sq=synthesis.MIN_CANDIDATE_DISTANCE_SQ)
    period = texture.shape[1] // synthesis.DEFAULT_PATCH_SIZE
    mask = synthesis._anchor_mask(synthesis._mask_seed(texture), period, synthesis.MIN_ANCHOR_DISTANCE)
    total_rows = canvas.shape[0] // synthesis.DEFAULT_PATCH_SIZE

    changed = False
    for row in range(total_rows):
        for col in range(synthesis.DEFAULT_CANVAS_WIDTH):
            if synthesis._is_anchor(mask, row, col):
                continue
            actual = synthesis._extract_patch(canvas, row, col, synthesis.DEFAULT_PATCH_SIZE)
            index = library.index_of_core(actual, synthesis.SEAM_OVERLAP)
            if not np.array_equal(actual, library.patches[index]):
                changed = True
    assert changed


def test_svg_export_contains_expected_structure(texture: np.ndarray) -> None:
    canvas = synthesis.encode(token_bytes(20), texture)
    svg = synthesis.to_svg(canvas)
    assert svg.startswith("<svg")
    assert "<defs>" in svg
    assert "<use href=" in svg
    assert "data:image/png;base64," in svg


def test_save_svg_writes_a_file(tmp_path: Path, texture: np.ndarray) -> None:
    canvas = synthesis.encode(token_bytes(20), texture)
    path = tmp_path / "out.svg"
    synthesis.save_svg(canvas, str(path))
    assert path.read_text(encoding="utf-8").startswith("<svg")


def test_canvas_to_png_round_trips_bit_exact(texture: np.ndarray) -> None:
    png_bytes = synthesis._canvas_to_png(texture)
    recovered = synthesis._png_to_canvas(png_bytes)
    assert np.array_equal(texture, recovered)


@pytest.mark.parametrize("data", SAMPLES)
def test_image_encoding_round_trip(data: bytes) -> None:
    nonce = token_bytes(24)
    atoms = list(synthesis.SYNTHESIS_VALUE_NOISE.encode_atoms(data, nonce))
    assert len(atoms) == 1, "ImageEncoding should yield exactly one atom -- the whole image."
    recovered = synthesis.SYNTHESIS_VALUE_NOISE.decode(atoms[0], len(data), nonce)
    assert recovered == data


@pytest.mark.parametrize(
    "encoding",
    [
        synthesis.SYNTHESIS_VALUE_NOISE,
        synthesis.SYNTHESIS_VORONOI,
        synthesis.SYNTHESIS_REACTION_DIFFUSION,
        synthesis.SYNTHESIS_ATTRACTOR,
    ],
    ids=lambda encoding: encoding.flavor,
)
@pytest.mark.parametrize("data", SAMPLES)
def test_image_encoding_round_trip_every_flavor(encoding: synthesis.ImageEncoding, data: bytes) -> None:
    nonce = token_bytes(24)
    atom = next(encoding.encode_atoms(data, nonce))
    assert encoding.decode(atom, len(data), nonce) == data


@pytest.mark.parametrize(
    "encoding",
    [
        synthesis.SYNTHESIS_VALUE_NOISE,
        synthesis.SYNTHESIS_VORONOI,
        synthesis.SYNTHESIS_REACTION_DIFFUSION,
        synthesis.SYNTHESIS_ATTRACTOR,
    ],
    ids=lambda encoding: encoding.flavor,
)
def test_image_encoding_round_trip_past_one_texture_period(encoding: synthesis.ImageEncoding) -> None:
    """A payload large enough that the canvas grows taller than one texture period, so
    `_guide_patch`'s modulo wraparound actually gets exercised (not just position 0..15)."""

    data = token_bytes(2_000)
    nonce = token_bytes(24)
    atom = next(encoding.encode_atoms(data, nonce))
    canvas = synthesis._png_to_canvas(atom)
    assert canvas.shape[0] // synthesis.DEFAULT_PATCH_SIZE > synthesis.DEFAULT_TEXTURE_SIZE // synthesis.DEFAULT_PATCH_SIZE
    assert encoding.decode(atom, len(data), nonce) == data


def test_image_encoding_atom_is_a_valid_png() -> None:
    atom = next(synthesis.SYNTHESIS_VALUE_NOISE.encode_atoms(token_bytes(30), token_bytes(24)))
    assert atom[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_encoding_seed_is_derived_from_nonce() -> None:
    data = token_bytes(30)
    atom_a = next(synthesis.SYNTHESIS_VALUE_NOISE.encode_atoms(data, token_bytes(24)))
    atom_b = next(synthesis.SYNTHESIS_VALUE_NOISE.encode_atoms(data, token_bytes(24)))
    assert atom_a != atom_b, "Different nonces should (almost certainly) synthesize different images."


def test_image_encoding_same_nonce_is_deterministic() -> None:
    data = token_bytes(30)
    nonce = token_bytes(24)
    atom_a = next(synthesis.SYNTHESIS_VALUE_NOISE.encode_atoms(data, nonce))
    atom_b = next(synthesis.SYNTHESIS_VALUE_NOISE.encode_atoms(data, nonce))
    assert atom_a == atom_b


def test_all_four_texture_flavors_have_distinct_identifiers() -> None:
    identifiers = {
        synthesis.SYNTHESIS_VALUE_NOISE.identifier,
        synthesis.SYNTHESIS_VORONOI.identifier,
        synthesis.SYNTHESIS_REACTION_DIFFUSION.identifier,
        synthesis.SYNTHESIS_ATTRACTOR.identifier,
    }
    assert len(identifiers) == 4
