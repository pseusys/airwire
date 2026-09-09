import { anchorMask, decode, DEFAULT_CANVAS_WIDTH, DEFAULT_PATCH_SIZE, DEFAULT_TEXTURE_SIZE, encode, Image, isAnchor, maskSeed } from './synthesis';
import { reactionDiffusion, textureByName, TextureFlavor, valueNoise, voronoi } from './textures';

// Small enough to keep the patch library modest and tests fast, large enough (with patchSize=8)
// to yield a real, varied 4x4-patch library -- see PatchLibrary's own "fewer than 2 distinct
// patches" guard for why a texture can't be arbitrarily small or flat.
const TEXTURE_SIZE = 32;

describe('image steganography: encode/decode round trip', () => {
  it('round-trips payloads of various sizes, including empty', () => {
    const texture = valueNoise(TEXTURE_SIZE, 1);
    for (const size of [0, 1, 5, 13, 37]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const canvas = encode(data, texture);
      const decoded = decode(canvas, texture, size);
      expect(decoded).toEqual(data);
    }
  });

  it('produces a canvas whose dimensions are whole multiples of the patch size', () => {
    const texture = valueNoise(TEXTURE_SIZE, 2);
    const canvas = encode(crypto.getRandomValues(new Uint8Array(20)), texture);
    expect(canvas.width % DEFAULT_PATCH_SIZE).toBe(0);
    expect(canvas.height % DEFAULT_PATCH_SIZE).toBe(0);
    expect(canvas.width / DEFAULT_PATCH_SIZE).toBe(DEFAULT_CANVAS_WIDTH);
  });

  it('is deterministic for the same data and texture', () => {
    const texture = valueNoise(TEXTURE_SIZE, 3);
    const data = crypto.getRandomValues(new Uint8Array(20));
    const first = encode(data, texture);
    const second = encode(data, texture);
    expect(first.data).toEqual(second.data);
  });

  it('fails to decode against the wrong texture (different seed)', () => {
    const realTexture = valueNoise(TEXTURE_SIZE, 4);
    const wrongTexture = valueNoise(TEXTURE_SIZE, 5);
    const data = crypto.getRandomValues(new Uint8Array(20));
    const canvas = encode(data, realTexture);
    // Wrong source texture means the receiver's PatchLibrary won't recognize the encoded patches
    // at all -- exactly the same "no confidentiality without the right seed" gate this project's
    // other disguise (Markov text) now has too (see memory/wire-protocol.md).
    expect(() => decode(canvas, wrongTexture, data.length)).toThrow();
  });

  it('fails closed when a gap patch is tampered with', () => {
    const texture = valueNoise(TEXTURE_SIZE, 6);
    const data = crypto.getRandomValues(new Uint8Array(20));
    const canvas = encode(data, texture);

    // Find a gap cell (not an anchor) to corrupt -- anchor content isn't validated on decode by
    // design (trusted and used as-is for neighboring gap cells' cost computation), so corrupting
    // one wouldn't necessarily raise.
    const period = Math.floor(texture.size / DEFAULT_PATCH_SIZE);
    const mask = anchorMask(maskSeed(texture), period);
    const totalRows = canvas.height / DEFAULT_PATCH_SIZE;
    let row = 0;
    let col = 0;
    outer: for (row = 0; row < totalRows; row++) {
      for (col = 0; col < DEFAULT_CANVAS_WIDTH; col++) {
        if (!isAnchor(mask, row, col)) break outer;
      }
    }

    const tampered: Image = { width: canvas.width, height: canvas.height, data: new Uint8Array(canvas.data) };
    const pixelIndex = (row * DEFAULT_PATCH_SIZE * canvas.width + col * DEFAULT_PATCH_SIZE) * 3;
    tampered.data[pixelIndex] = (tampered.data[pixelIndex] + 128) % 256;

    expect(() => decode(tampered, texture, data.length)).toThrow();
  });
});

describe('anchorMask', () => {
  it('is deterministic and periodic', () => {
    const maskA = anchorMask(7, 16);
    const maskB = anchorMask(7, 16);
    expect(maskA).toEqual(maskB);
    expect(maskA.length).toBe(16);
    // isAnchor wraps modulo the mask's own period, so a position many periods out still resolves.
    expect(isAnchor(maskA, 3, 5)).toBe(isAnchor(maskA, 3 + 16 * 4, 5 + 16 * 7));
  });

  it('has a sane density -- not empty, not clumped', () => {
    for (let seed = 0; seed < 5; seed++) {
      const mask = anchorMask(seed, 16);
      const anchorCount = mask.reduce((sum, row) => sum + row.filter(Boolean).length, 0);
      const density = anchorCount / (16 * 16);
      expect(density).toBeGreaterThan(0.25);
      expect(density).toBeLessThan(0.5);
    }
  });
});

describe('image steganography: every texture flavor, at production alignment', () => {
  const FLAVORS: TextureFlavor[] = ['value_noise', 'voronoi', 'reaction_diffusion', 'attractor'];

  for (const flavor of FLAVORS) {
    it(`round-trips for ${flavor}, including past one texture period`, () => {
      const positionGuided = flavor !== 'attractor';
      const texture = textureByName(flavor, DEFAULT_TEXTURE_SIZE, 42);
      // Large enough that the canvas grows taller than one texture period, so guidePatch's
      // modulo wraparound actually gets exercised (not just position 0..DEFAULT_CANVAS_WIDTH-1).
      const data = crypto.getRandomValues(new Uint8Array(400));
      const canvas = encode(data, texture, DEFAULT_PATCH_SIZE, DEFAULT_CANVAS_WIDTH, positionGuided);
      expect(canvas.height / DEFAULT_PATCH_SIZE).toBeGreaterThan(DEFAULT_TEXTURE_SIZE / DEFAULT_PATCH_SIZE);
      const decoded = decode(canvas, texture, data.length, DEFAULT_PATCH_SIZE, positionGuided);
      expect(decoded).toEqual(data);
    });
  }
});

describe('texture periodicity', () => {
  function tileSeamMse(size: number, data: Uint8Array): number {
    // Mean squared difference between the texture's own left edge and what would be its
    // neighbor's matching edge one tile to the right (data wrapped) -- zero for a perfectly
    // seamless tile.
    let sum = 0;
    let n = 0;
    for (let y = 0; y < size; y++) {
      for (let c = 0; c < 3; c++) {
        const rightEdge = data[(y * size + (size - 1)) * 3 + c];
        const leftEdgeOfNextTile = data[(y * size + 0) * 3 + c];
        const diff = rightEdge - leftEdgeOfNextTile;
        sum += diff * diff;
        n++;
      }
    }
    return sum / n;
  }

  it('voronoi tiles seamlessly (toroidal distance)', () => {
    // A non-toroidal implementation shows a large, consistent color jump at the wrap boundary;
    // a real Voronoi cell's shading changes smoothly, so the true value is small either way --
    // this just guards against reintroducing the hard seam a naive (non-wrapped) distance gave.
    const texture = voronoi(32, 7);
    expect(tileSeamMse(32, texture.data)).toBeLessThan(2000);
  });

  it('value_noise tiles seamlessly (wrapped grid)', () => {
    const texture = valueNoise(32, 7);
    expect(tileSeamMse(32, texture.data)).toBeLessThan(2000);
  });

  it('reaction_diffusion tiles seamlessly (already toroidal)', () => {
    const texture = reactionDiffusion(32, 7, 50);
    expect(tileSeamMse(32, texture.data)).toBeLessThan(2000);
  });
});
