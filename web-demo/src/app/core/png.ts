/**
 * Converts between this demo's internal `Image` (RGB, no alpha -- see synthesis.ts) and real PNG
 * files, via the browser's native `<canvas>`. PNG is lossless, so this round trip must be
 * bit-exact for `decode` to ever work on a downloaded-then-re-uploaded image -- verified in
 * practice via a full browser end-to-end test (encode -> toBlob -> re-decode -> compare), not just
 * assumed from "PNG is lossless" in the abstract. `colorSpaceConversion: 'none'` on decode is
 * deliberate: without it, a browser is free to apply color management that would shift pixel
 * values slightly, which is exactly the kind of silent corruption this format can't tolerate.
 */

import { Image } from './synthesis';

function imageToCanvasElement(image: Image): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = image.width;
  canvas.height = image.height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Could not acquire a 2D canvas context.');
  const imageData = ctx.createImageData(image.width, image.height);
  const pixelCount = image.width * image.height;
  for (let i = 0; i < pixelCount; i++) {
    imageData.data[i * 4] = image.data[i * 3];
    imageData.data[i * 4 + 1] = image.data[i * 3 + 1];
    imageData.data[i * 4 + 2] = image.data[i * 3 + 2];
    imageData.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(imageData, 0, 0);
  return canvas;
}

export async function imageToPngBlob(image: Image): Promise<Blob> {
  const canvas = imageToCanvasElement(image);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('Failed to encode the canvas as a PNG blob.'));
    }, 'image/png');
  });
}

export async function blobToImage(blob: Blob): Promise<Image> {
  const bitmap = await createImageBitmap(blob, { colorSpaceConversion: 'none' });
  const canvas = document.createElement('canvas');
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Could not acquire a 2D canvas context.');
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const pixelCount = canvas.width * canvas.height;
  const data = new Uint8Array(pixelCount * 3);
  for (let i = 0; i < pixelCount; i++) {
    data[i * 3] = imageData.data[i * 4];
    data[i * 3 + 1] = imageData.data[i * 4 + 1];
    data[i * 3 + 2] = imageData.data[i * 4 + 2];
  }
  return { width: canvas.width, height: canvas.height, data };
}
