import { Image } from './synthesis';
import { blobToImage, imageToPngBlob } from './png';

function makeTestImage(width: number, height: number): Image {
  const data = new Uint8Array(width * height * 3);
  for (let i = 0; i < width * height; i++) {
    // A distinct, non-trivial color per pixel so any channel/pixel mixup would be caught.
    data[i * 3] = (i * 7) % 256;
    data[i * 3 + 1] = (i * 13 + 40) % 256;
    data[i * 3 + 2] = (i * 29 + 90) % 256;
  }
  return { width, height, data };
}

describe('imageToPngBlob / blobToImage round trip', () => {
  it('recovers the exact pixel data and dimensions through a real PNG encode/decode', async () => {
    const image = makeTestImage(9, 6);
    const blob = await imageToPngBlob(image);
    expect(blob.type).toBe('image/png');
    const decoded = await blobToImage(blob);
    expect(decoded.width).toBe(image.width);
    expect(decoded.height).toBe(image.height);
    expect(decoded.data).toEqual(image.data);
  });

  it('round-trips a 1x1 image', async () => {
    const image = makeTestImage(1, 1);
    const decoded = await blobToImage(await imageToPngBlob(image));
    expect(decoded.data).toEqual(image.data);
  });
});
