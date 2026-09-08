import { decodeText, encodeText, END_TOKEN } from './markov';

describe('markov text disguise', () => {
  it('round-trips an empty payload', async () => {
    const data = new Uint8Array(0);
    const text = await encodeText('eng', data);
    const decoded = await decodeText('eng', text, 0);
    expect(decoded).toEqual(data);
  });

  it('round-trips arbitrary bytes through English', async () => {
    const data = new TextEncoder().encode('Hello, airwire! This is a demo message.');
    const text = await encodeText('eng', data);
    const decoded = await decodeText('eng', text, data.length);
    expect(decoded).toEqual(data);
  });

  it('round-trips arbitrary bytes through Russian', async () => {
    const data = new TextEncoder().encode('Привет, airwire!');
    const text = await encodeText('rus', data);
    const decoded = await decodeText('rus', text, data.length);
    expect(decoded).toEqual(data);
  });

  it('never contains the literal END token', async () => {
    const data = crypto.getRandomValues(new Uint8Array(200));
    const text = await encodeText('eng', data);
    expect(text).not.toContain(END_TOKEN);
  });

  it('contains a newline sentence boundary for longer input', async () => {
    const data = crypto.getRandomValues(new Uint8Array(200));
    const text = await encodeText('eng', data);
    expect(text).toContain('\n');
  });

  it('always ends with a completed sentence, across sizes that do not land on a boundary', async () => {
    for (const size of [1, 5, 13, 37, 80]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const text = await encodeText('eng', data, 7);
      expect(text.endsWith('\n')).toBeTrue();
    }
  });

  it('is deterministic for the same data and seed', async () => {
    const data = crypto.getRandomValues(new Uint8Array(30));
    const first = await encodeText('eng', data, 99);
    const second = await encodeText('eng', data, 99);
    expect(first).toEqual(second);
  });

  it('produces different output for different seeds over the same data', async () => {
    // Checked across several sizes, not just one sample: whenever a payload happens to land
    // exactly on a sentence boundary, filler never triggers and the seed genuinely has no effect
    // -- that's correct behavior, not a bug, but it means a single random sample is an unreliable
    // way to check this property.
    let sawDifference = false;
    for (const size of [1, 5, 13, 37, 80]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const a = await encodeText('eng', data, 1);
      const b = await encodeText('eng', data, 2);
      if (a !== b) sawDifference = true;
    }
    expect(sawDifference).toBeTrue();
  });

  it('still round-trips correctly when filler completion is used', async () => {
    for (const size of [1, 5, 13, 37, 80]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const text = await encodeText('eng', data, 7);
      const decoded = await decodeText('eng', text, size, 7);
      expect(decoded).toEqual(data);
    }
  });

  it('does not reliably recover the original bytes when decoded with the wrong seed', async () => {
    // The seed now gates the ENTIRE walk, not just the filler tail -- decoding with the wrong
    // seed should either recover corrupted bytes, or (when the wrong candidate order squeezes a
    // real word out of candidateRanges entirely at a narrow bit budget) throw. Both count as "did
    // not recover the original data"; checked across several sizes for the same reason the
    // seed-differs test above is: a single random sample is an unreliable way to check this.
    let sawMismatch = false;
    for (const size of [1, 5, 13, 37, 80, 199]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const text = await encodeText('eng', data, 1);
      try {
        const recovered = await decodeText('eng', text, data.length, 2);
        if (!arraysEqual(recovered, data)) sawMismatch = true;
      } catch {
        sawMismatch = true;
      }
    }
    expect(sawMismatch).toBeTrue();
  });
});

function arraysEqual(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}
