"""
Manual, human-readable walkthrough of the crypto + chunking + wire-encoding pipeline: encrypts a
message, packs it into wire-sized hyperchunk messages under a chosen `ChunkEncoding`, then
receives and decrypts it back, printing what happens at each step. Not a substitute for the test
suite (`poetry poe test`) -- this is for eyeballing what actually goes over the wire in each mode.
"""

from typing import Dict, Optional

from sources.chunking import DEFAULT_CHUNK_SIZE, ChunkingError, _decrypt_header, decode_ack, pack_hyperchunk, receive_hyperchunk
from sources.crypto import Symmetric
from sources.encodings import BASE64, PLAIN, ChunkEncoding
from sources.markov import MARKOV_ENG

_MODES: Dict[str, ChunkEncoding] = {
    "plain": PLAIN,
    "base64": BASE64,
    "markov": MARKOV_ENG,
}
# Note: MARKOV_RUS isn't offered here. unpack_hyperchunk picks a decoder purely from the header's
# ChunkEncoding identifier, which both MarkovEncoding("eng") and MarkovEncoding("rus") share --
# only one can be registered as *the* MARKOV decoder for auto-detection (see sources/markov.py's
# docstring), and that's MARKOV_ENG. MARKOV_RUS still works, just not through this demo's round
# trip; exercise it directly via `MARKOV_RUS.encode_atoms(...)`/`.decode(...)` instead.


def _printable(data: bytes, limit: int = 200) -> str:
    """Render `data` for terminal display: as text if it decodes to printable UTF-8, else as hex."""

    sample = data[:limit]
    suffix = "..." if len(data) > limit else ""
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return sample.hex() + suffix
    if text and all(character.isprintable() or character.isspace() for character in text):
        return text + suffix
    return sample.hex() + suffix


def run(text: str = "Hello, airwire! This is a demo message.", mode: str = "plain", chunk_size: Optional[int] = None) -> int:
    """
    Encrypt `text`, pack it as one hyperchunk using the `mode` wire encoding, print what actually
    goes over the wire, then receive and decrypt it back to confirm the round trip.
    :return: exit code integer -- 0 on a successful round trip, 1 otherwise.
    """

    if mode not in _MODES:
        print(f"Unknown mode {mode!r}; supported: {sorted(_MODES)}.")
        return 1

    encoding = _MODES[mode]
    resolved_chunk_size = DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
    plaintext = text.encode("utf-8")
    symmetric = Symmetric()  # stands in for an already-established session key.

    print(f"Mode: {mode}  (chunk_size={resolved_chunk_size})")
    print(f"Plaintext ({len(plaintext)} bytes): {text!r}")

    try:
        messages = pack_hyperchunk(symmetric, plaintext, hyperchunk_id=0, chunk_size=resolved_chunk_size, encoding=encoding)
    except ChunkingError as error:
        print(f"\nFailed to pack: {error}")
        return 1

    header, chunks = messages[0], messages[1:]
    wire_bytes = sum(len(message) for message in messages)
    chunk_id_size = _decrypt_header(symmetric, header).chunk_id_size

    print(f"\nPacked into {len(messages)} wire message(s) ({len(chunks)} data chunk(s) + 1 header), {wire_bytes} bytes total:")
    print(f"  header ({len(header)} bytes, encrypted): {_printable(header)}")
    for index, chunk in enumerate(chunks):
        chunk_id, payload = chunk[:chunk_id_size], chunk[chunk_id_size:]
        print(f"  chunk {index}: id={chunk_id.hex()}, payload ({len(payload)} bytes): {_printable(payload)}")

    if wire_bytes:
        print(f"\nRaw-byte efficiency: {len(plaintext)}/{wire_bytes} = {len(plaintext) / wire_bytes * 100:.1f}%")

    recovered, ack = receive_hyperchunk(symmetric, messages)
    if ack is not None:
        acked_id, acked_success = decode_ack(symmetric, ack)
        print(f"\nAck ({len(ack)} bytes, encrypted): hyperchunk {acked_id}, success={acked_success}")

    success = recovered == plaintext
    print(f"Round trip: {'OK' if success else 'FAILED'}")
    if recovered is not None:
        print(f"Recovered ({len(recovered)} bytes): {recovered.decode('utf-8', errors='replace')!r}")

    return 0 if success else 1
