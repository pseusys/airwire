import { decode, DEFAULT_CANVAS_WIDTH, DEFAULT_PATCH_SIZE, encode, Image } from './synthesis';
import { valueNoise } from './textures';

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

  it('fails closed when a gap-row patch is tampered with', () => {
    const texture = valueNoise(TEXTURE_SIZE, 6);
    const data = crypto.getRandomValues(new Uint8Array(20));
    const canvas = encode(data, texture);

    // Corrupt one pixel in the first gap row (row index 1, i.e. one patch-height down) so the
    // patch at that position no longer matches ANY entry in the source texture's patch library.
    const tampered: Image = { width: canvas.width, height: canvas.height, data: new Uint8Array(canvas.data) };
    const pixelIndex = (DEFAULT_PATCH_SIZE * canvas.width + 0) * 3;
    tampered.data[pixelIndex] = (tampered.data[pixelIndex] + 128) % 256;

    expect(() => decode(tampered, texture, data.length)).toThrow();
  });
});
