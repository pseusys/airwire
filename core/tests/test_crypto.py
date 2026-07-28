import pytest

from sources.crypto import Asymmetric, Symmetric

SAMPLE_DATA = b"Sample data for encryption"
ADDITIONAL_DATA = b"Sample additional data"


def test_symmetric_round_trip() -> None:
    symmetric = Symmetric()
    ciphertext = symmetric.encrypt(SAMPLE_DATA, ADDITIONAL_DATA)
    assert symmetric.decrypt(ciphertext, ADDITIONAL_DATA) == SAMPLE_DATA


def test_symmetric_round_trip_without_additional_data() -> None:
    symmetric = Symmetric()
    ciphertext = symmetric.encrypt(SAMPLE_DATA)
    assert symmetric.decrypt(ciphertext) == SAMPLE_DATA


def test_symmetric_ciphertext_includes_random_nonce_by_default() -> None:
    symmetric = Symmetric()
    first = symmetric.encrypt(SAMPLE_DATA)
    second = symmetric.encrypt(SAMPLE_DATA)
    assert first != second, "Two encryptions of the same plaintext should not be identical!"
    assert len(first) == len(SAMPLE_DATA) + Symmetric.ciphertext_overhead


def test_symmetric_round_trip_with_explicit_nonce() -> None:
    symmetric = Symmetric()
    nonce = b"\x01" * Symmetric.nonce_size
    ciphertext = symmetric.encrypt(SAMPLE_DATA, ADDITIONAL_DATA, nonce=nonce)
    assert len(ciphertext) == len(SAMPLE_DATA) + Symmetric.tag_size, "Explicit nonce must not be embedded in the output!"
    assert symmetric.decrypt(ciphertext, ADDITIONAL_DATA, nonce=nonce) == SAMPLE_DATA


def test_symmetric_decrypt_fails_closed_on_tampered_ciphertext() -> None:
    symmetric = Symmetric()
    ciphertext = symmetric.encrypt(SAMPLE_DATA, ADDITIONAL_DATA)
    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0x01])
    with pytest.raises(ValueError):
        symmetric.decrypt(tampered, ADDITIONAL_DATA)


def test_symmetric_decrypt_fails_closed_on_wrong_additional_data() -> None:
    symmetric = Symmetric()
    ciphertext = symmetric.encrypt(SAMPLE_DATA, ADDITIONAL_DATA)
    with pytest.raises(ValueError):
        symmetric.decrypt(ciphertext, b"wrong additional data")


def test_symmetric_decrypt_fails_closed_on_wrong_key() -> None:
    ciphertext = Symmetric().encrypt(SAMPLE_DATA, ADDITIONAL_DATA)
    with pytest.raises(ValueError):
        Symmetric().decrypt(ciphertext, ADDITIONAL_DATA)


def test_asymmetric_round_trip() -> None:
    receiver = Asymmetric()
    receiver_public = Asymmetric(receiver.public_key, private=False)

    symmetric_key_sender, ciphertext = receiver_public.encrypt(SAMPLE_DATA)
    symmetric_key_receiver, plaintext = receiver.decrypt(ciphertext)

    assert plaintext == SAMPLE_DATA
    assert symmetric_key_sender == symmetric_key_receiver


def test_asymmetric_public_key_is_not_visible_on_the_wire() -> None:
    receiver = Asymmetric()
    receiver_public = Asymmetric(receiver.public_key, private=False)
    _, ciphertext = receiver_public.encrypt(SAMPLE_DATA)

    # The real ephemeral public key is XOR-masked; it must not appear as a readable substring.
    ephemeral_region = ciphertext[: Asymmetric._N_SIZE + Asymmetric._PUBLIC_KEY_SIZE]
    assert receiver.public_key[: Asymmetric._PUBLIC_KEY_SIZE] not in ephemeral_region


def test_asymmetric_decrypt_fails_closed_for_wrong_recipient() -> None:
    receiver = Asymmetric()
    receiver_public = Asymmetric(receiver.public_key, private=False)
    _, ciphertext = receiver_public.encrypt(SAMPLE_DATA)

    other_receiver = Asymmetric()
    with pytest.raises(ValueError):
        other_receiver.decrypt(ciphertext)
