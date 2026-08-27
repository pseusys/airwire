import numpy as np
import pytest

from sources.textures import attractor, reaction_diffusion, texture_by_name, value_noise, voronoi


def test_value_noise_shape_and_dtype() -> None:
    texture = value_noise(32, seed=1)
    assert texture.shape == (32, 32, 3)
    assert texture.dtype == np.uint8


def test_value_noise_deterministic() -> None:
    assert np.array_equal(value_noise(32, seed=1), value_noise(32, seed=1))


def test_value_noise_seed_changes_output() -> None:
    assert not np.array_equal(value_noise(32, seed=1), value_noise(32, seed=2))


def test_voronoi_shape_and_dtype() -> None:
    texture = voronoi(32, seed=1)
    assert texture.shape == (32, 32, 3)
    assert texture.dtype == np.uint8


def test_reaction_diffusion_shape_and_dtype() -> None:
    texture = reaction_diffusion(32, seed=1, steps=200)
    assert texture.shape == (32, 32, 3)
    assert texture.dtype == np.uint8


def test_attractor_shape_and_dtype() -> None:
    texture = attractor(32, seed=1, iterations=5_000)
    assert texture.shape == (32, 32, 3)
    assert texture.dtype == np.uint8


def test_texture_by_name_resolves_known_generator() -> None:
    texture = texture_by_name("value_noise", size=32, seed=1)
    assert texture.shape == (32, 32, 3)


def test_texture_by_name_rejects_unknown_generator() -> None:
    with pytest.raises(ValueError):
        texture_by_name("nonexistent", size=32, seed=1)
