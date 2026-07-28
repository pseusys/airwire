"""
Split a message into large "hyperslices", encrypt each one as a single AEAD operation, and split
*that* into wire-message-sized "chunks" for transmission — with a stop-and-wait acknowledgement
and retry layer on top. Replaces the earlier per-chunk-crypto design: here the nonce+tag cost is
paid once per hyperslice (configurable, ~1KB by default) and amortized over everything it
contains, at the price of one extra round trip per hyperslice for the acknowledgement.

Terminology, and the wire format that comes out of it:

- A **hyperslice** is a configurably-sized piece of the original plaintext (default 1KB).
- Encrypting one hyperslice (single nonce, single tag, `Symmetric.encrypt`) produces its
  ciphertext. This ciphertext is split into **chunks**, each at most `chunk_size` raw bytes,
  prefixed with a **chunk ID**: a plain sequence number *within this hyperchunk*. Its field width
  is variable, 1 to 8 bytes, sized to the actual number of chunks so a hyperslice that only needs
  a few chunks doesn't pay for 8 bytes of index space on every one of them.
- The chunk sequence is preceded by one more wire message, the **hyperchunk header**
  (`HyperchunkHeader`, `sources/proto/hyperchunk.proto`): a session-scoped hyperchunk ID, the
  ciphertext length, the nonce, the chunk count, the tag, and the chosen chunk ID width. It is
  itself serialized and then encrypted as a whole (its own random nonce, embedded) with the same
  symmetric key — so an observer without that key learns nothing about a hyperslice's size, chunk
  count, or position in the session, only that *some* hyperchunk was sent. A **hyperchunk** is
  this encrypted header plus its chunk sequence: everything needed to reassemble and decrypt one
  hyperslice.
- The receiving side tries to gather every chunk named in the (decrypted) header, reassemble,
  decrypt and verify, then sends back a single acknowledgement (`HyperchunkAck`, same proto file)
  — itself serialized and encrypted the same way, and naming the hyperchunk ID it refers to. On
  anything short of a matching, successful ack — a missing chunk, a failed tag, a timeout, a
  garbled or misattributed ack — the sender resends the *entire* hyperchunk (header included) up
  to a configured retry limit.
- How ciphertext bytes become chunk *payload* bytes is pluggable (`sources/encodings.py`,
  `ChunkEncoding`) -- raw bytes by default, but also base64 or (in the future) Markov-chain-
  disguised text. The chosen encoding is recorded in the (encrypted) header so the receiver can
  invert it without needing it configured out of band. Packing works the same way regardless of
  encoding: `_greedy_pack` fills each chunk with as many whole encoded "atoms" as fit, which is
  necessary because an encoding's output length per unit of input isn't always predictable ahead
  of time (a disguised-text encoding's word lengths, for instance).

Scope and open questions, worth a second look independently of this module:

- Header and ack reuse the same session symmetric key as the hyperslice data itself, distinguished
  only by using fresh random nonces each time. That's standard practice (AEAD security only needs
  nonces to never repeat under a given key) but it is a deliberate simplification — a
  domain-separated key per message class would be more conservative, at the cost of session-setup
  machinery this module doesn't own.
- The hyperchunk ID solves the two gaps flagged in the previous version of this module: an ack now
  names the hyperchunk it refers to, so `send_hyperchunk` can reject an ack meant for a different
  hyperchunk (stale or cross-session replay), and encrypting the header hides its content from
  anyone without the key. What's *not* solved: a verbatim replay of *this exact hyperchunk's own*
  previously-valid ciphertext is still possible for an adversary who can intercept and duplicate
  traffic — mostly harmless here, since replaying a genuine "success" only tells the sender what
  already happened, but worth keeping in mind if this protocol ever carries a message where that
  stops being true.
- If the header itself fails to decrypt (wrong key, corruption, truncation), there's no
  hyperchunk ID to acknowledge — `receive_hyperchunk` sends nothing back in that case, matching
  `send_hyperchunk`'s "no response" timeout path rather than inventing a placeholder ID.
"""

from secrets import token_bytes
from typing import Callable, Dict, List, Optional, Tuple

from sources.crypto import Symmetric
from sources.encodings import PLAIN, ChunkEncoding, encoding_by_identifier, register
from sources.markov import MARKOV_ENG
from sources.proto import hyperchunk_pb2

register(MARKOV_ENG)

DEFAULT_HYPERSLICE_SIZE = 1024
DEFAULT_CHUNK_SIZE = 120  # matches the raw-byte budget of a 160-character base64-encoded SMS.

MIN_CHUNK_ID_SIZE = 1
MAX_CHUNK_ID_SIZE = 8

DEFAULT_MAX_RETRIES = 3


class ChunkingError(Exception):
    pass


class ChunkSizeTooSmallError(ChunkingError):
    pass


class MessageTooLargeError(ChunkingError):
    pass


class IncompleteMessageError(ChunkingError):
    pass


class HyperchunkDeliveryError(ChunkingError):
    pass


def _chunk_id_size(chunk_count: int) -> int:
    """Minimum number of bytes needed to index `chunk_count` chunks (0-based), capped at 8."""

    max_index = max(chunk_count - 1, 0)
    size = MIN_CHUNK_ID_SIZE
    while max_index >= (1 << (size * 8)) and size < MAX_CHUNK_ID_SIZE:
        size += 1
    return size


def slice_hyperslices(plaintext: bytes, hyperslice_size: int = DEFAULT_HYPERSLICE_SIZE) -> List[bytes]:
    """Cut `plaintext` into `hyperslice_size`-byte pieces (the last one may be shorter)."""

    if hyperslice_size <= 0:
        raise ChunkingError(f"hyperslice_size must be positive, got {hyperslice_size}!")
    return [plaintext[i : i + hyperslice_size] for i in range(0, len(plaintext), hyperslice_size)] or [b""]


def _greedy_pack(encoding: ChunkEncoding, data: bytes, budget: int) -> List[bytes]:
    """
    Split `encoding.encode_atoms(data)`'s output into `budget`-bounded pieces, greedily: keep
    appending whole atoms to the piece under construction until the next one would overflow it,
    then start a new piece. Works regardless of how many output bytes a given atom represents in
    input-byte terms, which isn't fixed or predictable in advance for every encoding.
    """

    pieces: List[bytes] = []
    current = bytearray()
    for atom in encoding.encode_atoms(data):
        if len(atom) > budget:
            raise ChunkSizeTooSmallError(f"A single {type(encoding).__name__} atom is {len(atom)} bytes, which doesn't fit a budget of {budget}!")
        if current and len(current) + len(atom) > budget:
            pieces.append(bytes(current))
            current = bytearray()
        current.extend(atom)
    pieces.append(bytes(current))
    return pieces


def pack_hyperchunk(
    symmetric: Symmetric,
    hyperslice: bytes,
    hyperchunk_id: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    encoding: ChunkEncoding = PLAIN,
) -> List[bytes]:
    """Encrypt one hyperslice and split it into wire messages: `[header, chunk_0, chunk_1, ...]`."""

    nonce = token_bytes(Symmetric.nonce_size)
    encrypted = symmetric.encrypt(hyperslice, nonce=nonce)
    ciphertext, tag = encrypted[: -Symmetric.tag_size], encrypted[-Symmetric.tag_size :]

    chunk_id_size = MIN_CHUNK_ID_SIZE
    while True:
        usable_per_chunk = chunk_size - chunk_id_size
        if usable_per_chunk <= 0:
            raise ChunkSizeTooSmallError(f"chunk_size ({chunk_size}) leaves no room for payload once a {chunk_id_size}-byte chunk ID is subtracted!")
        pieces = _greedy_pack(encoding, ciphertext, usable_per_chunk)
        required_size = _chunk_id_size(len(pieces))
        if required_size <= chunk_id_size:
            break
        if chunk_id_size >= MAX_CHUNK_ID_SIZE:
            raise MessageTooLargeError(f"Hyperslice needs {len(pieces)} chunks, which doesn't fit even an {MAX_CHUNK_ID_SIZE}-byte chunk ID!")
        chunk_id_size = required_size

    header = hyperchunk_pb2.HyperchunkHeader(
        hyperchunk_id=hyperchunk_id,
        hyperchunk_length=len(ciphertext),
        nonce=nonce,
        chunk_count=len(pieces),
        tag=tag,
        chunk_id_size=chunk_id_size,
        encoding=encoding.identifier,
    )
    header_message = symmetric.encrypt(header.SerializeToString())
    if len(header_message) > chunk_size:
        raise ChunkSizeTooSmallError(f"Encrypted hyperchunk header is {len(header_message)} bytes, which doesn't fit chunk_size ({chunk_size})!")

    chunks = [index.to_bytes(chunk_id_size, "big") + piece for index, piece in enumerate(pieces)]
    return [header_message, *chunks]


def _decrypt_header(symmetric: Symmetric, header_message: bytes) -> hyperchunk_pb2.HyperchunkHeader:
    plaintext = symmetric.decrypt(header_message)
    header = hyperchunk_pb2.HyperchunkHeader()
    header.ParseFromString(plaintext)
    if not (MIN_CHUNK_ID_SIZE <= header.chunk_id_size <= MAX_CHUNK_ID_SIZE):
        raise ChunkingError(f"Hyperchunk header declares an invalid chunk ID width: {header.chunk_id_size}!")
    try:
        encoding_by_identifier(header.encoding)
    except ValueError as error:
        raise ChunkingError(str(error)) from error
    return header


def _reassemble(symmetric: Symmetric, header: hyperchunk_pb2.HyperchunkHeader, chunk_messages: List[bytes]) -> bytes:
    parsed: Dict[int, bytes] = {}
    for message in chunk_messages:
        if len(message) < header.chunk_id_size:
            raise ChunkingError(f"Chunk message ({len(message)} bytes) is shorter than the declared {header.chunk_id_size}-byte chunk ID!")
        index = int.from_bytes(message[: header.chunk_id_size], "big")
        parsed[index] = message[header.chunk_id_size :]

    missing = sorted(set(range(header.chunk_count)) - set(parsed))
    if missing:
        raise IncompleteMessageError(f"Missing chunk indices: {missing}!")

    encoded = b"".join(parsed[index] for index in range(header.chunk_count))
    try:
        ciphertext = encoding_by_identifier(header.encoding).decode(encoded, header.hyperchunk_length)
    except ValueError as error:
        raise ChunkingError(f"Failed to decode reassembled chunk payload: {error}!") from error

    if len(ciphertext) != header.hyperchunk_length:
        raise ChunkingError(f"Reassembled ciphertext is {len(ciphertext)} bytes, header declared {header.hyperchunk_length}!")

    return symmetric.decrypt(ciphertext + header.tag, nonce=header.nonce)


def unpack_hyperchunk(symmetric: Symmetric, messages: List[bytes]) -> Tuple[int, bytes]:
    """Inverse of `pack_hyperchunk`. Returns `(hyperchunk_id, plaintext)`."""

    if not messages:
        raise ChunkingError("No messages given!")
    header = _decrypt_header(symmetric, messages[0])
    plaintext = _reassemble(symmetric, header, messages[1:])
    return header.hyperchunk_id, plaintext


def encode_ack(symmetric: Symmetric, hyperchunk_id: int, success: bool) -> bytes:
    ack = hyperchunk_pb2.HyperchunkAck(hyperchunk_id=hyperchunk_id, success=success)
    return symmetric.encrypt(ack.SerializeToString())


def decode_ack(symmetric: Symmetric, message: bytes) -> Tuple[int, bool]:
    """Returns `(hyperchunk_id, success)`. Raises `ValueError` if `message` doesn't decrypt."""

    plaintext = symmetric.decrypt(message)
    ack = hyperchunk_pb2.HyperchunkAck()
    ack.ParseFromString(plaintext)
    return ack.hyperchunk_id, ack.success


def receive_hyperchunk(symmetric: Symmetric, messages: List[bytes]) -> Tuple[Optional[bytes], Optional[bytes]]:
    """
    Try to reassemble and decrypt one hyperslice from received wire messages.
    Returns `(plaintext_or_None, ack_to_send_or_None)`. The ack is `None` only when the header
    itself couldn't be decrypted — there's then no hyperchunk ID to acknowledge, so nothing is
    sent back and the sender is expected to time out and retry.
    """

    if not messages:
        return None, None

    try:
        header = _decrypt_header(symmetric, messages[0])
    except (ChunkingError, ValueError):
        return None, None

    try:
        plaintext = _reassemble(symmetric, header, messages[1:])
    except (ChunkingError, ValueError):
        return None, encode_ack(symmetric, header.hyperchunk_id, False)

    return plaintext, encode_ack(symmetric, header.hyperchunk_id, True)


def send_hyperchunk(
    symmetric: Symmetric,
    hyperslice: bytes,
    hyperchunk_id: int,
    send: Callable[[bytes], None],
    receive_ack: Callable[[], Optional[bytes]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_retries: int = DEFAULT_MAX_RETRIES,
    encoding: ChunkEncoding = PLAIN,
) -> None:
    """
    Send one hyperslice as hyperchunk `hyperchunk_id`, retrying the whole hyperchunk (header
    included) up to `max_retries` times unless `receive_ack` reports success *for this specific
    hyperchunk ID* — an ack for any other ID, a malformed/undecryptable ack, or `None` (timeout)
    are all treated as failure. Raises `HyperchunkDeliveryError` once retries are exhausted.
    """

    messages = pack_hyperchunk(symmetric, hyperslice, hyperchunk_id, chunk_size, encoding)

    attempt = 0
    while True:
        for message in messages:
            send(message)

        response = receive_ack()
        if response is not None:
            try:
                acked_id, success = decode_ack(symmetric, response)
                if acked_id == hyperchunk_id and success:
                    return
            except (ChunkingError, ValueError):
                pass  # an undecryptable/malformed acknowledgement counts as failure.

        attempt += 1
        if attempt > max_retries:
            raise HyperchunkDeliveryError(f"Hyperchunk {hyperchunk_id} delivery failed after {max_retries} retries!")
