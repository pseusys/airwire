"""
Pluggable strategies for turning hyperchunk ciphertext bytes into the bytes that actually travel
in wire chunks, and back -- used by `sources/chunking.py`. Every strategy shares one packing
algorithm: `chunking.py` walks an encoding's `encode_atoms()` output greedily, filling each
`chunk_size`-bounded wire chunk with as many whole atoms as fit before starting the next one. This
works even for encodings whose output length per unit of input isn't fixed or predictable ahead of
time -- a future Markov-chain-disguise encoding, for instance, might turn a given number of
ciphertext bits into anywhere from one short word to several long ones, depending on how many
candidate continuations the chain has at that point. The packer never needs to know that ratio in
advance, only how to recognize when the *next* atom would overflow the chunk it's currently
filling; see `chunking._greedy_pack`.

Currently implemented: `PlainEncoding` (raw bytes, the original design) and `Base64Encoding` (a
visible-but-not-plausible middle ground between raw binary and a fully-disguised encoding). See
`sources/markov.py` and `sources/synthesis.py` for the text and image disguise encodings.
"""

from abc import ABC, abstractmethod
from base64 import b64decode, b64encode
from typing import Dict, Iterator

from sources.proto import hyperchunk_pb2


class ChunkEncoding(ABC):
    identifier: hyperchunk_pb2.ChunkEncoding

    @abstractmethod
    def encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]:
        """
        Yield indivisible output atoms that, concatenated in order, encode all of `data`. `nonce`
        is the hyperslice's own AEAD nonce (already unique and transmitted regardless of encoding)
        -- most encodings ignore it, same as most ignore `length` on `decode` below, but one that
        needs an arbitrary per-message seed (`sources/synthesis.py`'s image encoding, for its
        source-texture choice) can derive it from here for free rather than needing a new field.
        """

    @abstractmethod
    def decode(self, encoded: bytes, length: int, nonce: bytes) -> bytes:
        """
        Invert the concatenation of every atom `encode_atoms` would have produced for some
        original data of `length` bytes, encoded with the same `nonce`. `length` comes from the
        hyperchunk header, which already carries it for reassembly validation regardless of
        encoding -- most encodings are self-delimiting and can ignore it, but one that can't tell
        where its own output ends without an external length (a Markov-chain walk, for instance,
        since the number of words needed isn't fixed) needs it to know when to stop.
        """


class PlainEncoding(ChunkEncoding):
    """Identity transform: chunk payloads are the raw ciphertext bytes, unmodified."""

    identifier = hyperchunk_pb2.ChunkEncoding.PLAIN

    def encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]:
        for byte in data:
            yield bytes((byte,))

    def decode(self, encoded: bytes, length: int, nonce: bytes) -> bytes:
        return encoded


class Base64Encoding(ChunkEncoding):
    """
    Base64 transform, one 3-byte group (4 output characters, always -- base64 pads the final
    partial group of the whole message, never an intermediate one) per atom.
    """

    identifier = hyperchunk_pb2.ChunkEncoding.BASE64

    def encode_atoms(self, data: bytes, nonce: bytes) -> Iterator[bytes]:
        for i in range(0, len(data), 3):
            yield b64encode(data[i : i + 3])

    def decode(self, encoded: bytes, length: int, nonce: bytes) -> bytes:
        return b64decode(encoded, validate=True)


PLAIN = PlainEncoding()
BASE64 = Base64Encoding()

_ENCODINGS: Dict[int, ChunkEncoding] = {
    PLAIN.identifier: PLAIN,
    BASE64.identifier: BASE64,
}


def encoding_by_identifier(identifier: int) -> ChunkEncoding:
    try:
        return _ENCODINGS[identifier]
    except KeyError:
        raise ValueError(f"No ChunkEncoding implementation registered for identifier {identifier}!") from None


def register(encoding: ChunkEncoding) -> None:
    """
    Add (or replace) an encoding in the registry `encoding_by_identifier` looks up. Encodings with
    external dependencies of their own (e.g. `sources.markov`'s frozen per-language models) live in
    their own module rather than being imported directly here, to keep this module free of
    dependencies belonging to any one specific encoding; `sources.chunking` wires them in via this
    function at import time instead.
    """

    _ENCODINGS[encoding.identifier] = encoding
