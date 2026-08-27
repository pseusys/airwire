"""
Establishes a session before any data transfer: exchanges each side's fresh, conversation-scoped
X25519 public key (a "certificate," deliberately unsigned -- plain TOFU) and derives the symmetric
key `sources/chunking.py` uses from there on. Also derives, from nothing but each sender's own
public transport identifier, the one disguise choice (Markov language or texture flavor) that
sender's messages -- handshake certificate included -- are wrapped in for the entire conversation,
so nothing about a conversation's outward appearance changes between the first message and the
last. See docs/handshake.md for the full design and its security properties and limits; this
module is the direct implementation of that document, function for function.
"""

from secrets import token_bytes
from typing import NamedTuple, Tuple

from nacl.bindings import crypto_scalarmult, crypto_scalarmult_base

from sources.crypto import Symmetric, derive_key
from sources.encodings import ChunkEncoding
from sources.markov import MARKOV_ENG, MARKOV_RUS
from sources.proto import handshake_pb2
from sources.synthesis import SYNTHESIS_ATTRACTOR, SYNTHESIS_REACTION_DIFFUSION, SYNTHESIS_VALUE_NOISE, SYNTHESIS_VORONOI

# Order is part of the wire-compatible protocol -- append new entries, never insert or reorder, or
# every existing sender's derived obfuscation choice silently changes. See docs/handshake.md.
DISGUISE_POOL: Tuple[ChunkEncoding, ...] = (
    MARKOV_ENG,
    MARKOV_RUS,
    SYNTHESIS_VALUE_NOISE,
    SYNTHESIS_VORONOI,
    SYNTHESIS_REACTION_DIFFUSION,
    SYNTHESIS_ATTRACTOR,
)

_PUBLIC_KEY_SIZE = 32

# Fixed plaintext size a certificate is padded to before disguising -- same reasoning as
# `chunking.HEADER_PLAINTEXT_SIZE`: a disguised message's length can't be self-describing, since
# recovering it *is* the point of decoding. 64 bytes comfortably covers a phone number or a
# platform user ID plus the fixed 32-byte ephemeral public key.
CERTIFICATE_PLAINTEXT_SIZE = 64
_CERTIFICATE_CIPHERTEXT_SIZE = Symmetric.nonce_size + CERTIFICATE_PLAINTEXT_SIZE + Symmetric.tag_size

# Purely cosmetic (mirrors chunking._HEADER_DISGUISE_SEED): if a sender's derived obfuscation mode
# happens to be an image flavor, the certificate's own texture seed needs no freshness, only
# consistency -- nothing here is meant to be unpredictable.
_CERTIFICATE_DISGUISE_SEED = derive_key(b"airwire-certificate-disguise-seed", size=Symmetric.nonce_size)


class HandshakeError(Exception):
    pass


def obfuscation_for_sender(sender_id: str) -> ChunkEncoding:
    """
    The one disguise every message from `sender_id` -- handshake certificate and all data-phase
    traffic alike -- is wrapped in, for the life of a conversation. A pure function of a sender's
    already-public, transport-visible identifier (a phone number in SMS mode, the equivalent
    platform user ID in web mode): both ends can compute this independently, with no exchange, no
    negotiation, and no pre-shared secret, because there's nothing here that needs to stay secret
    -- see docs/handshake.md's security-properties table for why that's fine.
    """

    digest = derive_key(sender_id.encode("utf-8"), b"airwire-obfuscation-mode", size=8)
    index = int.from_bytes(digest, "big") % len(DISGUISE_POOL)
    return DISGUISE_POOL[index]


def _bootstrap_key(sender_id: str) -> Symmetric:
    """
    The key that encrypts `sender_id`'s own certificate message -- derivable by anyone who knows
    who the sender is, i.e. everyone, so this provides no confidentiality, only AEAD-shaped bytes
    for the disguise coder to run on. See docs/handshake.md.
    """

    return Symmetric(key=derive_key(sender_id.encode("utf-8"), b"airwire-handshake-bootstrap", size=32))


def _pad(raw: bytes) -> bytes:
    if len(raw) > CERTIFICATE_PLAINTEXT_SIZE - 1:
        raise HandshakeError(f"Serialized certificate is {len(raw)} bytes, which doesn't fit the {CERTIFICATE_PLAINTEXT_SIZE}-byte fixed size a certificate requires!")
    return bytes((len(raw),)) + raw + bytes(CERTIFICATE_PLAINTEXT_SIZE - 1 - len(raw))


def _unpad(padded: bytes) -> bytes:
    length = padded[0]
    if length > len(padded) - 1:
        raise HandshakeError(f"Padded certificate declares a {length}-byte payload, longer than the {len(padded) - 1} bytes available!")
    return padded[1 : 1 + length]


class EphemeralKeypair(NamedTuple):
    private_key: bytes
    public_key: bytes


def generate_ephemeral_keypair() -> EphemeralKeypair:
    """A fresh X25519 keypair, scoped to one conversation -- not a long-term identity (see
    docs/handshake.md's plain-TOFU security properties and their limits)."""

    private_key = token_bytes(_PUBLIC_KEY_SIZE)
    return EphemeralKeypair(private_key, crypto_scalarmult_base(private_key))


def send_certificate(sender_id: str, ephemeral_public_key: bytes) -> bytes:
    """Build and disguise this sender's certificate message -- the first thing either side of a
    new conversation sends."""

    certificate = handshake_pb2.Certificate(sender=sender_id, ephemeral_public_key=ephemeral_public_key)
    encrypted = _bootstrap_key(sender_id).encrypt(_pad(certificate.SerializeToString()))
    disguise = obfuscation_for_sender(sender_id)
    return b"".join(disguise.encode_atoms(encrypted, _CERTIFICATE_DISGUISE_SEED))


def receive_certificate(sender_id: str, message: bytes) -> bytes:
    """
    Recover the peer's ephemeral public key from a certificate message. `sender_id` is the
    *sender's* identifier -- already known from the transport before this is called, the same way
    it's always known who an SMS or web-mode message is from -- used to independently derive the
    same disguise and bootstrap key the sender used. Raises `HandshakeError`/`ValueError` if the
    message doesn't decode, or if it claims a different sender than expected (plain TOFU still
    checks the claim is internally consistent, even though nothing here can verify it's true --
    see docs/handshake.md's security-properties table for what this can and can't catch).
    """

    disguise = obfuscation_for_sender(sender_id)
    encrypted = disguise.decode(message, _CERTIFICATE_CIPHERTEXT_SIZE, _CERTIFICATE_DISGUISE_SEED)
    padded = _bootstrap_key(sender_id).decrypt(encrypted)
    certificate = handshake_pb2.Certificate()
    certificate.ParseFromString(_unpad(padded))
    if certificate.sender != sender_id:
        raise HandshakeError(f"Certificate claims sender {certificate.sender!r}, expected {sender_id!r}!")
    return bytes(certificate.ephemeral_public_key)


def derive_session_key(own_private_key: bytes, own_public_key: bytes, peer_public_key: bytes) -> Symmetric:
    """
    Standard X25519 ECDH between this conversation's two ephemeral keypairs, giving both sides an
    identical `Symmetric` session key for the data phase -- see docs/handshake.md's Phase 2. The
    two public keys are sorted before hashing so both sides land on the same derivation regardless
    of who's "self" and who's "peer" -- without that, each side would hash them in the opposite
    order and derive different keys.
    """

    shared_secret = crypto_scalarmult(own_private_key, peer_public_key)
    ordered = sorted((own_public_key, peer_public_key))
    return Symmetric(key=derive_key(shared_secret, *ordered, size=32))
