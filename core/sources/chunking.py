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
  `ChunkEncoding`) -- raw bytes, base64, Markov-chain-disguised text, or (`sources/synthesis.py`)
  one whole synthesized image per hyperchunk. The chosen encoding is recorded in the (encrypted)
  header so the receiver can invert it without needing it configured out of band. Packing works
  the same way regardless of encoding: `_greedy_pack` fills each chunk with as many whole encoded
  "atoms" as fit, which is necessary because an encoding's output length per unit of input isn't
  always predictable ahead of time (a disguised-text encoding's word lengths, for instance) --
  the image encoding is the extreme case of this, yielding exactly one atom sized to hold the
  entire hyperslice, which is what makes "one hyperslice, one image" fall out of the same
  machinery as everything else rather than needing a second delivery path.
- **Disguising the header itself** (`header_encoding`, optional, `None` by default) is a *cosmetic*
  addition on top of the header's existing encryption, not a replacement for it: the serialized
  header is padded to a fixed `HEADER_PLAINTEXT_SIZE` (so its disguised length doesn't need to be
  self-describing, avoiding the same circularity that makes deriving the header's own nonce
  impossible -- see the TODO list entry below), encrypted exactly as always, and then that
  fixed-size ciphertext is additionally run through `header_encoding` the same way payload
  ciphertext is. This exists so a conversation's wire traffic never has one raw-binary-looking
  message sitting next to a stream of otherwise-disguised ones. See
  [memory/handshake.md](../../memory/handshake.md) for where `header_encoding` (and the payload
  `encoding`) are actually decided -- both are meant to be **session-scoped constants**, chosen
  once and held fixed for a conversation's lifetime, the same way the `symmetric` key object
  itself is expected to stay one consistent value across a session's calls. Nothing in this module
  enforces that (it would need session state this module deliberately doesn't have); it's a
  caller discipline, not a runtime check.

Scope and open questions, worth a second look independently of this module:

- Header and ack reuse the same session symmetric key as the hyperslice data itself, distinguished
  only by using fresh random nonces each time. That's standard practice (AEAD security only needs
  nonces to never repeat under a given key) but it is a deliberate simplification — a
  domain-separated key per message class would be more conservative, at the cost of session-setup
  machinery this module doesn't own. Deriving these nonces instead of transmitting them was tried
  (see [memory/rejected-ideas.md](../../memory/rejected-ideas.md)'s header/ack-nonce entry) and
  reverted; the header case is provably impossible (`hyperchunk_id` only becomes known *by
  decrypting the header*, so deriving its own nonce from it is circular), and the ack case, while it
  worked for today's two-field schema, doesn't survive the ack ever growing to carry open-ended data
  (e.g. a missing-chunk list for selective retransmission, tracked in
  [`../../TODO.md`](../../TODO.md) D1) — see that entry for the full story of why.
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
- `encode_ack`/`decode_ack` don't have a `header_encoding`-style disguise option yet, even though
  they have exactly the same "raw ciphertext sitting next to disguised messages" problem the
  header did before this option existed. Not addressed here since it wasn't asked for; the same
  fixed-size-padding approach would apply directly if it's needed later (an ack's plaintext is
  already tiny and fixed-shape, so it wouldn't even need the padding step, just the encode/decode
  wrapping).
"""

from secrets import token_bytes
from typing import Callable, Dict, List, Optional, Tuple

from sources.crypto import Symmetric, derive_key
from sources.encodings import PLAIN, ChunkEncoding, encoding_by_identifier, register
from sources.markov import MARKOV_ENG, MARKOV_RUS
from sources.proto import hyperchunk_pb2
from sources.synthesis import SYNTHESIS_ATTRACTOR, SYNTHESIS_REACTION_DIFFUSION, SYNTHESIS_VALUE_NOISE, SYNTHESIS_VORONOI

for _encoding in (MARKOV_ENG, MARKOV_RUS, SYNTHESIS_VALUE_NOISE, SYNTHESIS_VORONOI, SYNTHESIS_REACTION_DIFFUSION, SYNTHESIS_ATTRACTOR):
    register(_encoding)

DEFAULT_HYPERSLICE_SIZE = 1024
DEFAULT_CHUNK_SIZE = 120  # matches the raw-byte budget of a 160-character base64-encoded SMS.
DEFAULT_MMS_CHUNK_SIZE = 300_000  # generous MMS-scale budget; real carrier limits vary widely.

MIN_CHUNK_ID_SIZE = 1
MAX_CHUNK_ID_SIZE = 8

DEFAULT_MAX_RETRIES = 3

# Fixed plaintext size a header is padded to before disguising it (see `header_encoding` above) --
# so its disguised length never needs to be self-describing. 71 bytes is the measured worst case
# (every field at its maximum encodable value); 96 leaves headroom for small future header growth
# without an immediate bump.
HEADER_PLAINTEXT_SIZE = 96
_HEADER_CIPHERTEXT_SIZE = Symmetric.nonce_size + HEADER_PLAINTEXT_SIZE + Symmetric.tag_size

# Seeds the *cosmetic-only* choice of source texture when the header disguise happens to be an
# image encoding -- deliberately a fixed constant, not derived per-hyperchunk: unlike the payload
# image (memory/wire-protocol.md), there's no freshness requirement here (nothing about the header
# disguise needs to be unpredictable, only consistent), and a per-hyperchunk value would run into
# the same circularity the header's own nonce already can't escape (see TODO.md D1).
_HEADER_DISGUISE_SEED = derive_key(b"airwire-header-disguise-seed", size=Symmetric.nonce_size)


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


def _greedy_pack(encoding: ChunkEncoding, data: bytes, budget: int, nonce: bytes) -> List[bytes]:
    """
    Split `encoding.encode_atoms(data, nonce)`'s output into `budget`-bounded pieces, greedily:
    keep appending whole atoms to the piece under construction until the next one would overflow
    it, then start a new piece. Works regardless of how many output bytes a given atom represents
    in input-byte terms, which isn't fixed or predictable in advance for every encoding.
    """

    pieces: List[bytes] = []
    current = bytearray()
    for atom in encoding.encode_atoms(data, nonce):
        if len(atom) > budget:
            raise ChunkSizeTooSmallError(f"A single {type(encoding).__name__} atom is {len(atom)} bytes, which doesn't fit a budget of {budget}!")
        if current and len(current) + len(atom) > budget:
            pieces.append(bytes(current))
            current = bytearray()
        current.extend(atom)
    pieces.append(bytes(current))
    return pieces


def _pad_header(raw: bytes) -> bytes:
    """Pad a serialized header to exactly `HEADER_PLAINTEXT_SIZE` bytes: a 1-byte actual-length
    prefix, the raw bytes, zero-fill to size. Only needed when disguising the header (see
    `header_encoding`), since only then does its length need to be a protocol constant instead of
    self-describing."""

    if len(raw) > HEADER_PLAINTEXT_SIZE - 1:
        raise ChunkSizeTooSmallError(f"Serialized hyperchunk header is {len(raw)} bytes, which doesn't fit the {HEADER_PLAINTEXT_SIZE}-byte fixed size header disguising requires!")
    return bytes((len(raw),)) + raw + bytes(HEADER_PLAINTEXT_SIZE - 1 - len(raw))


def _unpad_header(padded: bytes) -> bytes:
    """Inverse of `_pad_header`."""

    length = padded[0]
    if length > len(padded) - 1:
        raise ChunkingError(f"Padded header declares a {length}-byte payload, longer than the {len(padded) - 1} bytes available!")
    return padded[1 : 1 + length]


def pack_hyperchunk(
    symmetric: Symmetric,
    hyperslice: bytes,
    hyperchunk_id: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    encoding: ChunkEncoding = PLAIN,
    header_encoding: Optional[ChunkEncoding] = None,
) -> List[bytes]:
    """Encrypt one hyperslice and split it into wire messages: `[header, chunk_0, chunk_1, ...]`.
    `header_encoding` optionally disguises the header message too (see module docstring); `None`
    (the default) keeps it a plain encrypted blob, unchanged from before this option existed."""

    nonce = token_bytes(Symmetric.nonce_size)
    encrypted = symmetric.encrypt(hyperslice, nonce=nonce)
    ciphertext, tag = encrypted[: -Symmetric.tag_size], encrypted[-Symmetric.tag_size :]

    chunk_id_size = MIN_CHUNK_ID_SIZE
    while True:
        usable_per_chunk = chunk_size - chunk_id_size
        if usable_per_chunk <= 0:
            raise ChunkSizeTooSmallError(f"chunk_size ({chunk_size}) leaves no room for payload once a {chunk_id_size}-byte chunk ID is subtracted!")
        pieces = _greedy_pack(encoding, ciphertext, usable_per_chunk, nonce)
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
    if header_encoding is None:
        header_message = symmetric.encrypt(header.SerializeToString())
    else:
        encrypted_header = symmetric.encrypt(_pad_header(header.SerializeToString()))
        header_message = b"".join(header_encoding.encode_atoms(encrypted_header, _HEADER_DISGUISE_SEED))
    if len(header_message) > chunk_size:
        raise ChunkSizeTooSmallError(f"Encrypted hyperchunk header is {len(header_message)} bytes, which doesn't fit chunk_size ({chunk_size})!")

    chunks = [index.to_bytes(chunk_id_size, "big") + piece for index, piece in enumerate(pieces)]
    return [header_message, *chunks]


def _decrypt_header(symmetric: Symmetric, header_message: bytes, header_encoding: Optional[ChunkEncoding] = None) -> hyperchunk_pb2.HyperchunkHeader:
    if header_encoding is None:
        plaintext = symmetric.decrypt(header_message)
    else:
        encrypted_header = header_encoding.decode(header_message, _HEADER_CIPHERTEXT_SIZE, _HEADER_DISGUISE_SEED)
        plaintext = _unpad_header(symmetric.decrypt(encrypted_header))
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
        ciphertext = encoding_by_identifier(header.encoding).decode(encoded, header.hyperchunk_length, header.nonce)
    except ValueError as error:
        raise ChunkingError(f"Failed to decode reassembled chunk payload: {error}!") from error

    if len(ciphertext) != header.hyperchunk_length:
        raise ChunkingError(f"Reassembled ciphertext is {len(ciphertext)} bytes, header declared {header.hyperchunk_length}!")

    return symmetric.decrypt(ciphertext + header.tag, nonce=header.nonce)


def unpack_hyperchunk(symmetric: Symmetric, messages: List[bytes], header_encoding: Optional[ChunkEncoding] = None) -> Tuple[int, bytes]:
    """Inverse of `pack_hyperchunk`. Returns `(hyperchunk_id, plaintext)`."""

    if not messages:
        raise ChunkingError("No messages given!")
    header = _decrypt_header(symmetric, messages[0], header_encoding)
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


def receive_hyperchunk(symmetric: Symmetric, messages: List[bytes], header_encoding: Optional[ChunkEncoding] = None) -> Tuple[Optional[bytes], Optional[bytes]]:
    """
    Try to reassemble and decrypt one hyperslice from received wire messages.
    Returns `(plaintext_or_None, ack_to_send_or_None)`. The ack is `None` only when the header
    itself couldn't be decrypted — there's then no hyperchunk ID to acknowledge, so nothing is
    sent back and the sender is expected to time out and retry.
    """

    if not messages:
        return None, None

    try:
        header = _decrypt_header(symmetric, messages[0], header_encoding)
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
    header_encoding: Optional[ChunkEncoding] = None,
) -> None:
    """
    Send one hyperslice as hyperchunk `hyperchunk_id`, retrying the whole hyperchunk (header
    included) up to `max_retries` times unless `receive_ack` reports success *for this specific
    hyperchunk ID* — an ack for any other ID, a malformed/undecryptable ack, or `None` (timeout)
    are all treated as failure. Raises `HyperchunkDeliveryError` once retries are exhausted.
    """

    messages = pack_hyperchunk(symmetric, hyperslice, hyperchunk_id, chunk_size, encoding, header_encoding)

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
