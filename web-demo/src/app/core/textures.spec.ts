import { attractor, reactionDiffusion, textureByName, valueNoise, voronoi } from './textures';

// Small parameters throughout: these generators' cost scales with size/steps/iterations, and
// determinism/difference are checkable at any scale -- there's no need to pay for a full-size,
// production-quality render just to test that.
const SIZE = 16;

describe('valueNoise', () => {
  it('is deterministic for the same seed and differs across seeds', () => {
    const a = valueNoise(SIZE, 1);
    const b = valueNoise(SIZE, 1);
    const c = valueNoise(SIZE, 2);
    expect(a.data).toEqual(b.data);
    expect(a.data).not.toEqual(c.data);
  });

  it('produces a Texture of the requested size with row-major RGB data', () => {
    const texture = valueNoise(SIZE, 1);
    expect(texture.size).toBe(SIZE);
    expect(texture.data.length).toBe(SIZE * SIZE * 3);
  });
});

describe('voronoi', () => {
  it('is deterministic for the same seed and differs across seeds', () => {
    const a = voronoi(SIZE, 1);
    const b = voronoi(SIZE, 1);
    const c = voronoi(SIZE, 2);
    expect(a.data).toEqual(b.data);
    expect(a.data).not.toEqual(c.data);
  });
});

describe('reactionDiffusion', () => {
  it('is deterministic for the same seed and differs across seeds', () => {
    const a = reactionDiffusion(SIZE, 1, 50);
    const b = reactionDiffusion(SIZE, 1, 50);
    const c = reactionDiffusion(SIZE, 2, 50);
    expect(a.data).toEqual(b.data);
    expect(a.data).not.toEqual(c.data);
  });
});

describe('attractor', () => {
  it('is deterministic for the same seed and differs across seeds', () => {
    const a = attractor(SIZE, 1, 5000);
    const b = attractor(SIZE, 1, 5000);
    const c = attractor(SIZE, 2, 5000);
    expect(a.data).toEqual(b.data);
    expect(a.data).not.toEqual(c.data);
  });
});

describe('textureByName', () => {
  it('dispatches each registered flavor name to its own generator', () => {
    expect(textureByName('value_noise', SIZE, 1).data).toEqual(valueNoise(SIZE, 1).data);
    expect(textureByName('voronoi', SIZE, 1).data).toEqual(voronoi(SIZE, 1).data);
    expect(textureByName('reaction_diffusion', SIZE, 1).data).toEqual(reactionDiffusion(SIZE, 1).data);
    expect(textureByName('attractor', SIZE, 1).data).toEqual(attractor(SIZE, 1).data);
  });
});
