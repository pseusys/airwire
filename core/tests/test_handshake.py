import pytest

from sources import handshake
from sources.encodings import ChunkEncoding


def test_obfuscation_for_sender_is_deterministic() -> None:
    assert handshake.obfuscation_for_sender("+15551234567") is handshake.obfuscation_for_sender("+15551234567")


def test_obfuscation_for_sender_picks_from_the_disguise_pool() -> None:
    encoding = handshake.obfuscation_for_sender("+15551234567")
    assert encoding in handshake.DISGUISE_POOL


def test_different_senders_can_get_different_obfuscation_modes() -> None:
    modes = {handshake.obfuscation_for_sender(f"+1555000{i:04d}") for i in range(20)}
    assert len(modes) > 1, "20 different sender IDs landing on exactly one mode would be a suspicious coincidence."


def test_certificate_round_trip() -> None:
    keypair = handshake.generate_ephemeral_keypair()
    message = handshake.send_certificate("+15551234567", keypair.public_key)
    recovered_public_key = handshake.receive_certificate("+15551234567", message)
    assert recovered_public_key == keypair.public_key


def test_certificate_fails_closed_with_the_wrong_sender_id() -> None:
    keypair = handshake.generate_ephemeral_keypair()
    message = handshake.send_certificate("+15551234567", keypair.public_key)
    # A different sender_id derives a different bootstrap key/disguise entirely, so this should
    # fail to decode, not just fail the sender-match check.
    with pytest.raises((handshake.HandshakeError, ValueError)):
        handshake.receive_certificate("+15559999999", message)


def test_certificate_rejects_oversized_sender_id() -> None:
    keypair = handshake.generate_ephemeral_keypair()
    with pytest.raises(handshake.HandshakeError):
        handshake.send_certificate("x" * handshake.CERTIFICATE_PLAINTEXT_SIZE, keypair.public_key)


def test_full_handshake_both_sides_derive_the_same_session_key() -> None:
    alice_id, bob_id = "+15551234567", "+15559876543"
    alice_keys = handshake.generate_ephemeral_keypair()
    bob_keys = handshake.generate_ephemeral_keypair()

    cert_from_alice = handshake.send_certificate(alice_id, alice_keys.public_key)
    cert_from_bob = handshake.send_certificate(bob_id, bob_keys.public_key)

    bobs_view_of_alice = handshake.receive_certificate(alice_id, cert_from_alice)
    alices_view_of_bob = handshake.receive_certificate(bob_id, cert_from_bob)

    alice_session = handshake.derive_session_key(alice_keys.private_key, alice_keys.public_key, alices_view_of_bob)
    bob_session = handshake.derive_session_key(bob_keys.private_key, bob_keys.public_key, bobs_view_of_alice)

    # Symmetric has no public equality; round-trip a message through one and decrypt with the
    # other as an indirect but conclusive check that both derived the identical key.
    message = alice_session.encrypt(b"same key on both sides")
    assert bob_session.decrypt(message) == b"same key on both sides"


def test_derive_session_key_is_order_independent() -> None:
    """Whichever side calls this with itself as "own" and the other as "peer", both must land on
    the same key -- this is what the public-key sort inside `derive_session_key` is for."""

    alice_keys = handshake.generate_ephemeral_keypair()
    bob_keys = handshake.generate_ephemeral_keypair()

    from_alice = handshake.derive_session_key(alice_keys.private_key, alice_keys.public_key, bob_keys.public_key)
    from_bob = handshake.derive_session_key(bob_keys.private_key, bob_keys.public_key, alice_keys.public_key)

    message = from_alice.encrypt(b"order independence check")
    assert from_bob.decrypt(message) == b"order independence check"


def test_disguise_pool_entries_are_all_chunk_encodings() -> None:
    assert all(isinstance(encoding, ChunkEncoding) for encoding in handshake.DISGUISE_POOL)


def test_disguise_pool_has_no_duplicate_identifiers() -> None:
    identifiers = [encoding.identifier for encoding in handshake.DISGUISE_POOL]
    assert len(identifiers) == len(set(identifiers))
