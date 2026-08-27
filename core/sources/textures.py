"""
Procedural source-texture generators for `sources/texture.py`'s patch-based image disguise --
the image-steganography analog of `sources/corpus.py`'s per-language text corpora. Unlike the
text corpora, these need no download and no training step: each generator deterministically
produces a small RGB texture from nothing but a size and an integer seed, so both ends of a
conversation can regenerate an identical source texture from the same fixed, public seed rather
than needing to share a file.

Determinism here rests on NumPy's `default_rng` (PCG64), which NumPy documents as a stable,
version-independent bit stream for a given seed. That's the same category of assumption
`sources/markov.py` had to get right for the arithmetic coder, just delegated to NumPy's own
documented guarantee rather than hand-rolled -- worth another look before this is load-bearing
across independently-built clients (see design-decisions.md).

Every generator returns an `(size, size, 3)` `uint8` NumPy array.
"""

import math
from typing import Callable, Dict

import numpy as np

Generator = Callable[[int, int], np.ndarray]


def value_noise(size: int, seed: int, cell: int = 8) -> np.ndarray:
    """Bilinear-upsampled random grid -- smooth, organic-looking, cloud-like blobs."""

    rng = np.random.default_rng(seed)
    grid_size = size // cell + 2
    grid = rng.integers(0, 256, size=(grid_size, grid_size, 3)).astype(np.float64)

    out = np.zeros((size, size, 3), dtype=np.float64)
    for y in range(size):
        gy = y / cell
        y0, fy = int(gy), gy - int(gy)
        for x in range(size):
            gx = x / cell
            x0, fx = int(gx), gx - int(gx)
            top = grid[y0, x0] * (1 - fx) + grid[y0, x0 + 1] * fx
            bot = grid[y0 + 1, x0] * (1 - fx) + grid[y0 + 1, x0 + 1] * fx
            out[y, x] = top * (1 - fy) + bot * fy
    return np.clip(out, 0, 255).astype(np.uint8)


def voronoi(size: int, seed: int, n_cells: int = 40) -> np.ndarray:
    """Cellular partitioning into flat-ish colored regions, shaded by distance to each cell's
    seed point so interiors aren't perfectly flat (also avoids duplicate patches within a cell)."""

    rng = np.random.default_rng(seed)
    points = rng.integers(0, size, size=(n_cells, 2))
    colors = rng.integers(40, 256, size=(n_cells, 3))

    yy, xx = np.mgrid[0:size, 0:size]
    coords = np.stack([yy, xx], axis=-1).reshape(-1, 1, 2)
    dists = np.sum((coords - points[None, :, :]) ** 2, axis=-1)
    nearest = np.argmin(dists, axis=-1)
    nearest_dist = np.sqrt(np.min(dists, axis=-1)).reshape(size, size)

    shade = 1.0 - 0.35 * np.clip(nearest_dist / (size / math.sqrt(n_cells)), 0, 1)
    base = colors[nearest].reshape(size, size, 3).astype(np.float64)
    result: np.ndarray = np.clip(base * shade[:, :, None], 0, 255).astype(np.uint8)
    return result


def reaction_diffusion(size: int, seed: int, steps: int = 3000) -> np.ndarray:
    """Gray-Scott reaction-diffusion simulation -- coral/fingerprint-like patterns."""

    rng = np.random.default_rng(seed)
    diffusion_u, diffusion_v, feed, kill = 0.16, 0.08, 0.060, 0.062  # classic "coral" regime.

    u = np.ones((size, size))
    v = np.zeros((size, size))
    for _ in range(8):
        cy, cx = rng.integers(size // 8, size - size // 8, size=2)
        radius = size // 10
        yy, xx = np.mgrid[0:size, 0:size]
        mask = (yy - cy) ** 2 + (xx - cx) ** 2 < radius * radius
        v[mask] = 1.0
        u[mask] = 0.5
    v += rng.normal(0, 0.02, size=v.shape)

    def laplacian(z: np.ndarray) -> np.ndarray:
        orthogonal = np.roll(z, 1, 0) + np.roll(z, -1, 0) + np.roll(z, 1, 1) + np.roll(z, -1, 1)
        diagonal = np.roll(np.roll(z, 1, 0), 1, 1) + np.roll(np.roll(z, 1, 0), -1, 1) + np.roll(np.roll(z, -1, 0), 1, 1) + np.roll(np.roll(z, -1, 0), -1, 1)
        result: np.ndarray = -z + 0.2 * orthogonal + 0.05 * diagonal
        return result

    for _ in range(steps):
        reaction = u * v * v
        u += diffusion_u * laplacian(u) - reaction + feed * (1 - u)
        v += diffusion_v * laplacian(v) + reaction - (feed + kill) * v

    gray = np.clip((v - v.min()) / (v.max() - v.min() + 1e-9) * 255, 0, 255)
    rgb = np.stack([255 - gray, gray * 0.6 + 40, gray], axis=-1)
    rgb_bytes: np.ndarray = np.clip(rgb, 0, 255).astype(np.uint8)
    return rgb_bytes


def attractor(size: int, seed: int, iterations: int = 300_000) -> np.ndarray:
    """de Jong-style 2D chaotic attractor, accumulated into a log-density histogram."""

    rng = np.random.default_rng(seed)
    a, b, c, d = rng.uniform(-2, 2, size=4)
    x, y = 0.1, 0.1
    xs = np.empty(iterations)
    ys = np.empty(iterations)
    for i in range(iterations):
        x, y = math.sin(a * y) - math.cos(b * x), math.sin(c * x) - math.cos(d * y)
        xs[i], ys[i] = x, y

    xi = ((xs - xs.min()) / (xs.max() - xs.min() + 1e-9) * (size - 1)).astype(int)
    yi = ((ys - ys.min()) / (ys.max() - ys.min() + 1e-9) * (size - 1)).astype(int)
    hist = np.zeros((size, size), dtype=np.int64)
    np.add.at(hist, (yi, xi), 1)

    density = np.log1p(hist)
    density = density / density.max() * 255
    rgb = np.stack([density, density * 0.4, 255 - density], axis=-1)
    result: np.ndarray = np.clip(rgb, 0, 255).astype(np.uint8)
    return result


TEXTURES: Dict[str, Generator] = {
    "value_noise": value_noise,
    "voronoi": voronoi,
    "reaction_diffusion": reaction_diffusion,
    "attractor": attractor,
}


def texture_by_name(name: str, size: int, seed: int) -> np.ndarray:
    try:
        generator = TEXTURES[name]
    except KeyError:
        raise ValueError(f"No texture generator named {name!r}; supported: {sorted(TEXTURES)}!") from None
    return generator(size, seed)
