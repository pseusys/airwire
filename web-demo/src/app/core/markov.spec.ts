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
    const data = crypto.getRandomValues(new Uint8Array(30));
    const a = await encodeText('eng', data, 1);
    const b = await encodeText('eng', data, 2);
    expect(a).not.toEqual(b);
  });

  it('still round-trips correctly when filler completion is used', async () => {
    for (const size of [1, 5, 13, 37, 80]) {
      const data = crypto.getRandomValues(new Uint8Array(size));
      const text = await encodeText('eng', data, 7);
      const decoded = await decodeText('eng', text, size);
      expect(decoded).toEqual(data);
    }
  });
});
