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
});
