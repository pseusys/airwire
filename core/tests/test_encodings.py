from secrets import token_bytes

import pytest

from sources.encodings import BASE64, PLAIN, Base64Encoding, PlainEncoding, encoding_by_identifier

SAMPLES = [b"", b"a", b"ab", b"abc", b"abcd", b"Hello, world! This is a test." * 5]
NONCE = token_bytes(24)  # PLAIN/BASE64 ignore it; only encodings that need a seed (e.g. images) use it.


@pytest.mark.parametrize("data", SAMPLES)
def test_plain_round_trip(data: bytes) -> None:
    encoded = b"".join(PLAIN.encode_atoms(data, NONCE))
    assert encoded == data
    assert PLAIN.decode(encoded, len(data), NONCE) == data


@pytest.mark.parametrize("data", SAMPLES)
def test_base64_round_trip(data: bytes) -> None:
    encoded = b"".join(BASE64.encode_atoms(data, NONCE))
    assert BASE64.decode(encoded, len(data), NONCE) == data


def test_base64_atoms_are_all_four_bytes() -> None:
    for atom in BASE64.encode_atoms(b"Hello, world!", NONCE):
        assert len(atom) == 4


def test_base64_decode_rejects_malformed_input() -> None:
    with pytest.raises(ValueError):
        BASE64.decode(b"not valid base64!!", 10, NONCE)


def test_encoding_by_identifier_resolves_known_encodings() -> None:
    assert encoding_by_identifier(PLAIN.identifier) is PLAIN
    assert encoding_by_identifier(BASE64.identifier) is BASE64


def test_encoding_by_identifier_rejects_unknown_identifier() -> None:
    with pytest.raises(ValueError):
        encoding_by_identifier(99)


def test_plain_and_base64_are_distinct_identifiers() -> None:
    assert PlainEncoding.identifier != Base64Encoding.identifier
