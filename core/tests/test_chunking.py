from secrets import token_bytes
from typing import List, Optional

import pytest

from sources.chunking import (
    DEFAULT_HYPERSLICE_SIZE,
    DEFAULT_MMS_CHUNK_SIZE,
    HEADER_PLAINTEXT_SIZE,
    ChunkingError,
    ChunkSizeTooSmallError,
    HyperchunkDeliveryError,
    IncompleteMessageError,
    _chunk_id_size,
    _decrypt_header,
    _pad_header,
    _unpad_header,
    decode_ack,
    encode_ack,
    pack_hyperchunk,
    receive_hyperchunk,
    send_hyperchunk,
    slice_hyperslices,
    unpack_hyperchunk,
)
from sources.crypto import Symmetric
from sources.encodings import BASE64, PLAIN, ChunkEncoding
from sources.markov import MARKOV_ENG
from sources.synthesis import SYNTHESIS_VALUE_NOISE

ALL_ENCODINGS = [PLAIN, BASE64, MARKOV_ENG]


# _chunk_id_size:


@pytest.mark.parametrize(
    "chunk_count,expected_size",
    [(1, 1), (255, 1), (256, 1), (257, 2), (65536, 2), (65537, 3), (1 << 63, 8)],
)
def test_chunk_id_size_boundaries(chunk_count: int, expected_size: int) -> None:
    assert _chunk_id_size(chunk_count) == expected_size


# slice_hyperslices:


def test_slice_hyperslices_round_trip_via_concatenation() -> None:
    plaintext = token_bytes(2500)
    slices = slice_hyperslices(plaintext, hyperslice_size=1024)
    assert len(slices) == 3
    assert all(len(s) <= 1024 for s in slices)
    assert b"".join(slices) == plaintext


def test_slice_hyperslices_empty_plaintext() -> None:
    assert slice_hyperslices(b"") == [b""]


def test_slice_hyperslices_rejects_non_positive_size() -> None:
    with pytest.raises(ChunkingError):
        slice_hyperslices(b"data", hyperslice_size=0)


# pack_hyperchunk / unpack_hyperchunk:


@pytest.mark.parametrize("encoding", ALL_ENCODINGS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize(
    "hyperslice",
    [b"", b"hi", token_bytes(50), token_bytes(500), token_bytes(DEFAULT_HYPERSLICE_SIZE)],
)
def test_pack_unpack_round_trip_for_every_encoding(hyperslice: bytes, encoding: ChunkEncoding) -> None:
    """The same pack/unpack loop, run once per registered `ChunkEncoding` -- plain, base64, and
    the Markov-chain text disguise -- since none of chunking.py's logic is encoding-specific."""

    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, hyperslice, hyperchunk_id=7, encoding=encoding)
    # unpack_hyperchunk isn't told the encoding -- it reads it back out of the (encrypted) header.
    hyperchunk_id, plaintext = unpack_hyperchunk(symmetric, messages)
    assert hyperchunk_id == 7
    assert plaintext == hyperslice


def test_pack_hyperchunk_default_chunk_id_size_is_one_byte_for_small_messages() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, token_bytes(500), hyperchunk_id=0)
    header = _decrypt_header(symmetric, messages[0])
    assert header.chunk_id_size == 1


def test_pack_hyperchunk_widens_chunk_id_when_many_chunks_are_needed() -> None:
    symmetric = Symmetric()
    chunk_size = 150  # comfortably fits the encrypted header; usable payload = 149 bytes/chunk.
    hyperslice = token_bytes(45000)  # forces >256 chunks, over the 1-byte chunk ID ceiling.
    messages = pack_hyperchunk(symmetric, hyperslice, hyperchunk_id=1, chunk_size=chunk_size)
    header = _decrypt_header(symmetric, messages[0])
    assert header.chunk_id_size == 2
    hyperchunk_id, plaintext = unpack_hyperchunk(symmetric, messages)
    assert hyperchunk_id == 1
    assert plaintext == hyperslice


def test_pack_hyperchunk_rejects_chunk_size_too_small_for_header() -> None:
    with pytest.raises(ChunkSizeTooSmallError):
        pack_hyperchunk(Symmetric(), b"data", hyperchunk_id=0, chunk_size=10)


def test_unpack_hyperchunk_tolerates_out_of_order_chunks() -> None:
    symmetric = Symmetric()
    hyperslice = token_bytes(500)
    messages = pack_hyperchunk(symmetric, hyperslice, hyperchunk_id=0)
    header, chunks = messages[0], messages[1:]
    _, plaintext = unpack_hyperchunk(symmetric, [header, *reversed(chunks)])
    assert plaintext == hyperslice


def test_unpack_hyperchunk_raises_on_missing_chunk() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, token_bytes(500), hyperchunk_id=0)
    with pytest.raises(IncompleteMessageError):
        unpack_hyperchunk(symmetric, messages[:-1])


def test_unpack_hyperchunk_fails_closed_on_tampered_chunk_data() -> None:
    symmetric = Symmetric()
    # Tampering a data chunk changes the reassembled ciphertext, which must fail the header's
    # (untouched) tag on decrypt.
    messages = pack_hyperchunk(symmetric, token_bytes(500), hyperchunk_id=0)
    header, chunks = messages[0], messages[1:]
    tampered_first_chunk = bytearray(chunks[0])
    tampered_first_chunk[-1] ^= 0x01
    with pytest.raises(ValueError):
        unpack_hyperchunk(symmetric, [header, bytes(tampered_first_chunk), *chunks[1:]])


def test_unpack_hyperchunk_fails_closed_on_tampered_header() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, b"tamper me", hyperchunk_id=0)
    header = bytearray(messages[0])
    header[-1] ^= 0x01
    with pytest.raises(ValueError):
        unpack_hyperchunk(symmetric, [bytes(header), *messages[1:]])


def test_unpack_hyperchunk_fails_closed_on_wrong_key() -> None:
    messages = pack_hyperchunk(Symmetric(), b"secret stuff", hyperchunk_id=0)
    with pytest.raises(ValueError):
        unpack_hyperchunk(Symmetric(), messages)


def test_unpack_hyperchunk_rejects_empty_input() -> None:
    with pytest.raises(ChunkingError):
        unpack_hyperchunk(Symmetric(), [])


# pack_hyperchunk / unpack_hyperchunk with a non-default ChunkEncoding:


def test_pack_hyperchunk_records_the_chosen_encoding_in_the_header() -> None:
    symmetric = Symmetric()
    plain_messages = pack_hyperchunk(symmetric, b"data", hyperchunk_id=0)
    base64_messages = pack_hyperchunk(symmetric, b"data", hyperchunk_id=0, encoding=BASE64)
    markov_messages = pack_hyperchunk(symmetric, b"data", hyperchunk_id=0, encoding=MARKOV_ENG)
    assert _decrypt_header(symmetric, plain_messages[0]).encoding == PLAIN.identifier
    assert _decrypt_header(symmetric, base64_messages[0]).encoding == BASE64.identifier
    assert _decrypt_header(symmetric, markov_messages[0]).encoding == MARKOV_ENG.identifier


def test_pack_hyperchunk_base64_chunks_are_readable_ascii() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, token_bytes(200), hyperchunk_id=0, chunk_size=150, encoding=BASE64)
    for chunk in messages[1:]:
        payload = chunk[1:]  # 1-byte chunk ID prefix at this chunk_size/chunk_count.
        assert all(32 <= b < 127 for b in payload), "Base64-encoded chunk payload should be printable ASCII!"


def test_pack_hyperchunk_rejects_chunk_size_too_small_for_a_single_base64_atom() -> None:
    # A base64 atom is always 4 bytes; chunk_size=4 leaves usable_per_chunk=3 even at the minimum
    # 1-byte chunk ID, which can't fit even one atom.
    with pytest.raises(ChunkSizeTooSmallError):
        pack_hyperchunk(Symmetric(), b"data", hyperchunk_id=0, chunk_size=4, encoding=BASE64)


def test_send_hyperchunk_forwards_the_encoding_parameter() -> None:
    symmetric = Symmetric()
    sent: List[bytes] = []

    def send(message: bytes) -> None:
        sent.append(message)

    def receive_ack() -> Optional[bytes]:
        return encode_ack(symmetric, 4, True)

    send_hyperchunk(symmetric, b"secret text", hyperchunk_id=4, send=send, receive_ack=receive_ack, encoding=BASE64)

    assert _decrypt_header(symmetric, sent[0]).encoding == BASE64.identifier


# encode_ack / decode_ack:


@pytest.mark.parametrize("success", [True, False])
def test_ack_round_trip(success: bool) -> None:
    symmetric = Symmetric()
    ack = encode_ack(symmetric, hyperchunk_id=42, success=success)
    hyperchunk_id, decoded_success = decode_ack(symmetric, ack)
    assert hyperchunk_id == 42
    assert decoded_success == success


def test_decode_ack_fails_closed_on_wrong_key() -> None:
    ack = encode_ack(Symmetric(), hyperchunk_id=1, success=True)
    with pytest.raises(ValueError):
        decode_ack(Symmetric(), ack)


def test_decode_ack_rejects_malformed_message() -> None:
    with pytest.raises(ValueError):
        decode_ack(Symmetric(), b"not an ack")


# receive_hyperchunk:


def test_receive_hyperchunk_success() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, b"hello", hyperchunk_id=9)
    plaintext, ack = receive_hyperchunk(symmetric, messages)
    assert plaintext == b"hello"
    assert ack is not None
    assert decode_ack(symmetric, ack) == (9, True)


def test_receive_hyperchunk_reports_failure_ack_for_missing_chunk() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, token_bytes(500), hyperchunk_id=9)
    plaintext, ack = receive_hyperchunk(symmetric, messages[:-1])  # drop a chunk
    assert plaintext is None
    assert ack is not None
    assert decode_ack(symmetric, ack) == (9, False)


def test_receive_hyperchunk_sends_no_ack_when_header_undecryptable() -> None:
    messages = pack_hyperchunk(Symmetric(), b"hello", hyperchunk_id=9)
    plaintext, ack = receive_hyperchunk(Symmetric(), messages)  # wrong key
    assert plaintext is None
    assert ack is None


def test_receive_hyperchunk_on_empty_input() -> None:
    assert receive_hyperchunk(Symmetric(), []) == (None, None)


# send_hyperchunk (retry orchestration over a fake transport):


def test_send_hyperchunk_succeeds_on_first_try() -> None:
    symmetric = Symmetric()
    inbox: List[bytes] = []

    def send(message: bytes) -> None:
        inbox.append(message)

    def receive_ack() -> Optional[bytes]:
        _, ack = receive_hyperchunk(symmetric, inbox)
        return ack

    send_hyperchunk(symmetric, b"hello world", hyperchunk_id=1, send=send, receive_ack=receive_ack)

    plaintext, _ = receive_hyperchunk(symmetric, inbox)
    assert plaintext == b"hello world"


def test_send_hyperchunk_retries_then_succeeds() -> None:
    symmetric = Symmetric()
    responses = iter([None, encode_ack(symmetric, 3, False), encode_ack(symmetric, 3, True)])
    send_call_count = 0

    def send(message: bytes) -> None:
        nonlocal send_call_count
        send_call_count += 1

    def receive_ack() -> Optional[bytes]:
        return next(responses)

    send_hyperchunk(symmetric, b"data", hyperchunk_id=3, send=send, receive_ack=receive_ack, max_retries=5)

    messages_per_attempt = len(pack_hyperchunk(symmetric, b"data", hyperchunk_id=3))
    assert send_call_count == messages_per_attempt * 3  # 1 original attempt + 2 retries.


def test_send_hyperchunk_treats_ack_for_a_different_hyperchunk_id_as_failure() -> None:
    symmetric = Symmetric()
    responses = iter([encode_ack(symmetric, 999, True), encode_ack(symmetric, 5, True)])

    def send(message: bytes) -> None:
        pass

    def receive_ack() -> Optional[bytes]:
        return next(responses)

    send_hyperchunk(symmetric, b"data", hyperchunk_id=5, send=send, receive_ack=receive_ack, max_retries=1)


def test_send_hyperchunk_raises_after_exhausting_retries() -> None:
    def send(message: bytes) -> None:
        pass

    def receive_ack() -> Optional[bytes]:
        return None  # always times out.

    with pytest.raises(HyperchunkDeliveryError):
        send_hyperchunk(Symmetric(), b"data", hyperchunk_id=0, send=send, receive_ack=receive_ack, max_retries=2)


def test_send_and_receive_hyperchunk_over_a_lossy_channel() -> None:
    """End-to-end: the first delivery attempt drops a chunk, the second gets through cleanly."""

    symmetric = Symmetric()
    plaintext_to_send = b"important message"
    messages_per_attempt = len(pack_hyperchunk(symmetric, plaintext_to_send, hyperchunk_id=11))

    attempt = {"count": 0}
    delivered: List[bytes] = []
    received_plaintext: List[bytes] = []

    def send(message: bytes) -> None:
        delivered.append(message)

    def receive_ack() -> Optional[bytes]:
        attempt["count"] += 1
        inbox = delivered[-messages_per_attempt:]
        if attempt["count"] == 1:
            inbox = inbox[:-1]  # simulate the last chunk of the first attempt getting lost.
        plaintext, ack = receive_hyperchunk(symmetric, inbox)
        if plaintext is not None:
            received_plaintext.append(plaintext)
        return ack

    send_hyperchunk(symmetric, plaintext_to_send, hyperchunk_id=11, send=send, receive_ack=receive_ack, max_retries=1)
    assert received_plaintext == [plaintext_to_send]


# pack_hyperchunk / unpack_hyperchunk with an image ChunkEncoding:


def test_pack_unpack_round_trip_with_image_encoding() -> None:
    symmetric = Symmetric()
    plaintext = b"a hyperslice small enough to embed in one small texture image"
    messages = pack_hyperchunk(symmetric, plaintext, hyperchunk_id=7, chunk_size=DEFAULT_MMS_CHUNK_SIZE, encoding=SYNTHESIS_VALUE_NOISE)
    assert len(messages) == 2, "Image encoding should yield exactly one atom -- [header, one image chunk]."
    hyperchunk_id, recovered = unpack_hyperchunk(symmetric, messages)
    assert hyperchunk_id == 7
    assert recovered == plaintext


def test_image_encoding_chunk_is_a_valid_png() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, b"data", hyperchunk_id=0, chunk_size=DEFAULT_MMS_CHUNK_SIZE, encoding=SYNTHESIS_VALUE_NOISE)
    chunk_id_size = _decrypt_header(symmetric, messages[0]).chunk_id_size
    payload = messages[1][chunk_id_size:]
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"


def test_pack_hyperchunk_rejects_mms_payload_over_an_sms_chunk_size() -> None:
    with pytest.raises(ChunkSizeTooSmallError):
        pack_hyperchunk(Symmetric(), b"data", hyperchunk_id=0, encoding=SYNTHESIS_VALUE_NOISE)


# header_encoding (disguising the header itself):


def test_pad_unpad_header_round_trip() -> None:
    for raw in [b"", b"x", b"a" * (HEADER_PLAINTEXT_SIZE - 1)]:
        assert _unpad_header(_pad_header(raw)) == raw


def test_pad_header_rejects_oversized_input() -> None:
    with pytest.raises(ChunkingError):
        _pad_header(b"x" * HEADER_PLAINTEXT_SIZE)


@pytest.mark.parametrize("header_encoding", [MARKOV_ENG, SYNTHESIS_VALUE_NOISE], ids=lambda e: type(e).__name__)
def test_pack_unpack_round_trip_with_disguised_header(header_encoding: ChunkEncoding) -> None:
    symmetric = Symmetric()
    plaintext = b"a message whose header should not look like raw ciphertext"
    messages = pack_hyperchunk(symmetric, plaintext, hyperchunk_id=3, chunk_size=DEFAULT_MMS_CHUNK_SIZE, header_encoding=header_encoding)
    hyperchunk_id, recovered = unpack_hyperchunk(symmetric, messages, header_encoding=header_encoding)
    assert hyperchunk_id == 3
    assert recovered == plaintext


def test_disguised_header_is_not_raw_ciphertext() -> None:
    symmetric = Symmetric()
    plain_messages = pack_hyperchunk(symmetric, b"data", hyperchunk_id=0, chunk_size=DEFAULT_MMS_CHUNK_SIZE)
    disguised_messages = pack_hyperchunk(symmetric, b"data", hyperchunk_id=0, chunk_size=DEFAULT_MMS_CHUNK_SIZE, header_encoding=MARKOV_ENG)
    assert disguised_messages[0][:8] != plain_messages[0][:8]
    # A Markov-disguised header should decode as plausible UTF-8 text; raw ciphertext generally won't.
    disguised_messages[0].decode("utf-8")


def test_disguised_header_fails_to_decode_without_the_matching_header_encoding() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, b"data", hyperchunk_id=0, chunk_size=DEFAULT_MMS_CHUNK_SIZE, header_encoding=MARKOV_ENG)
    with pytest.raises((ChunkingError, ValueError)):
        unpack_hyperchunk(symmetric, messages)  # header_encoding=None, doesn't match how it was packed.


def test_receive_hyperchunk_works_with_disguised_header() -> None:
    symmetric = Symmetric()
    messages = pack_hyperchunk(symmetric, b"hello", hyperchunk_id=9, chunk_size=DEFAULT_MMS_CHUNK_SIZE, header_encoding=SYNTHESIS_VALUE_NOISE)
    plaintext, ack = receive_hyperchunk(symmetric, messages, header_encoding=SYNTHESIS_VALUE_NOISE)
    assert plaintext == b"hello"
    assert ack is not None


def test_send_hyperchunk_forwards_header_encoding() -> None:
    symmetric = Symmetric()
    sent: List[bytes] = []

    def send(message: bytes) -> None:
        sent.append(message)

    def receive_ack() -> Optional[bytes]:
        return encode_ack(symmetric, 4, True)

    send_hyperchunk(symmetric, b"secret text", hyperchunk_id=4, send=send, receive_ack=receive_ack, chunk_size=DEFAULT_MMS_CHUNK_SIZE, header_encoding=MARKOV_ENG)

    header = _decrypt_header(symmetric, sent[0], header_encoding=MARKOV_ENG)
    assert header.hyperchunk_id == 4
