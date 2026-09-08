import { Component, computed, signal, WritableSignal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { decodeText, encodeText } from './core/markov';
import { blobToImage, imageToPngBlob } from './core/png';
import { decode as decodeImage, DEFAULT_TEXTURE_SIZE, encode as encodeImage, Image } from './core/synthesis';
import { TEXTURE_FLAVORS, TextureFlavor, textureByName } from './core/textures';

type DisguiseType = 'text' | 'image';
type Language = 'eng' | 'rus';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent {
  readonly disguiseType = signal<DisguiseType>('text');

  // --- Text (Markov chain) mode ---

  readonly message = signal('Hello, airwire! This is a demo message.');
  readonly language = signal<Language>('eng');
  readonly textSeed = signal(this.randomSeed());

  readonly obfuscatedText = signal('');
  readonly originalByteLength = signal(0);
  readonly revealedText = signal<string | null>(null);

  readonly obfuscating = signal(false);
  readonly revealing = signal(false);
  readonly obfuscateError = signal<string | null>(null);
  readonly revealError = signal<string | null>(null);

  readonly messageByteLength = computed(() => new TextEncoder().encode(this.message()).length);
  readonly obfuscatedByteLength = computed(() => new TextEncoder().encode(this.obfuscatedText()).length);

  async obfuscate(): Promise<void> {
    this.obfuscateError.set(null);
    this.revealError.set(null);
    this.revealedText.set(null);
    this.obfuscating.set(true);
    try {
      const bytes = new TextEncoder().encode(this.message());
      const text = await encodeText(this.language(), bytes, this.textSeed());
      this.obfuscatedText.set(text);
      this.originalByteLength.set(bytes.length);
    } catch (error) {
      this.obfuscateError.set(error instanceof Error ? error.message : String(error));
      this.obfuscatedText.set('');
    } finally {
      this.obfuscating.set(false);
    }
  }

  async reveal(): Promise<void> {
    this.revealError.set(null);
    this.revealedText.set(null);
    this.revealing.set(true);
    try {
      const bytes = await decodeText(this.language(), this.obfuscatedText(), this.originalByteLength());
      this.revealedText.set(new TextDecoder('utf-8', { fatal: false }).decode(bytes));
    } catch (error) {
      this.revealError.set(error instanceof Error ? error.message : String(error));
    } finally {
      this.revealing.set(false);
    }
  }

  // --- Image (texture synthesis) mode ---

  readonly imageFlavors = TEXTURE_FLAVORS;
  readonly imageMessage = signal('Hello, airwire! This is a demo message.');
  readonly imageFlavor = signal<TextureFlavor>('value_noise');
  readonly imageSeed = signal(this.randomSeed());
  readonly imageByteLength = computed(() => new TextEncoder().encode(this.imageMessage()).length);

  readonly obfuscatedImage = signal<Image | null>(null);
  readonly obfuscatedImageUrl = signal<string | null>(null);
  readonly imageObfuscating = signal(false);
  readonly imageObfuscateError = signal<string | null>(null);

  readonly revealFlavor = signal<TextureFlavor>('value_noise');
  readonly revealSeed = signal(0);
  readonly revealLength = signal(0);
  readonly uploadedImage = signal<Image | null>(null);
  readonly uploadedImageUrl = signal<string | null>(null);
  readonly imageRevealing = signal(false);
  readonly imageRevealError = signal<string | null>(null);
  readonly revealedImageText = signal<string | null>(null);

  private randomSeed(): number {
    return Math.floor(Math.random() * 1_000_000);
  }

  randomizeImageSeed(): void {
    this.imageSeed.set(this.randomSeed());
  }

  randomizeTextSeed(): void {
    this.textSeed.set(this.randomSeed());
  }

  async obfuscateImage(): Promise<void> {
    this.imageObfuscateError.set(null);
    this.imageRevealError.set(null);
    this.revealedImageText.set(null);
    this.imageObfuscating.set(true);
    try {
      const bytes = new TextEncoder().encode(this.imageMessage());
      const flavor = this.imageFlavor();
      const seed = this.imageSeed();
      const texture = textureByName(flavor, DEFAULT_TEXTURE_SIZE, seed);
      const canvas = encodeImage(bytes, texture);
      this.obfuscatedImage.set(canvas);
      const blob = await imageToPngBlob(canvas);
      this.replaceObjectUrl(this.obfuscatedImageUrl, blob);

      // Auto-fill the reveal-side fields to match what was just generated -- editable afterward,
      // e.g. to reveal a PNG that was uploaded instead (see onImageFileSelected below).
      this.revealFlavor.set(flavor);
      this.revealSeed.set(seed);
      this.revealLength.set(bytes.length);
      this.clearUploadedImage();
    } catch (error) {
      this.imageObfuscateError.set(error instanceof Error ? error.message : String(error));
      this.obfuscatedImage.set(null);
      this.replaceObjectUrl(this.obfuscatedImageUrl, null);
    } finally {
      this.imageObfuscating.set(false);
    }
  }

  async onImageFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.imageRevealError.set(null);
    this.revealedImageText.set(null);
    try {
      const image = await blobToImage(file);
      this.uploadedImage.set(image);
      this.replaceObjectUrl(this.uploadedImageUrl, file);
    } catch (error) {
      this.imageRevealError.set(error instanceof Error ? error.message : String(error));
    } finally {
      input.value = '';
    }
  }

  clearUploadedImage(): void {
    this.uploadedImage.set(null);
    this.replaceObjectUrl(this.uploadedImageUrl, null);
  }

  async revealImage(): Promise<void> {
    this.imageRevealError.set(null);
    this.revealedImageText.set(null);
    this.imageRevealing.set(true);
    try {
      const source = this.uploadedImage() ?? this.obfuscatedImage();
      if (!source) {
        throw new Error('No image to reveal -- obfuscate a message above, or upload a PNG first.');
      }
      const texture = textureByName(this.revealFlavor(), DEFAULT_TEXTURE_SIZE, this.revealSeed());
      const bytes = decodeImage(source, texture, this.revealLength());
      this.revealedImageText.set(new TextDecoder('utf-8', { fatal: false }).decode(bytes));
    } catch (error) {
      this.imageRevealError.set(error instanceof Error ? error.message : String(error));
    } finally {
      this.imageRevealing.set(false);
    }
  }

  private replaceObjectUrl(target: WritableSignal<string | null>, source: Blob | null): void {
    const previous = target();
    if (previous) URL.revokeObjectURL(previous);
    target.set(source ? URL.createObjectURL(source) : null);
  }
}
