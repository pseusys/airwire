"""
X25519 key exchange and XChaCha20-Poly1305 authenticated encryption, via PyNaCl (libsodium
bindings).

The public-key "hiding" trick (XOR the ephemeral public key against a keyed
BLAKE2b keystream, prefixed with a random nonce) is implemented as a starting point for
airwire's own obfuscation goals: a plain X25519 public key is a structurally obvious 32 bytes on
the wire, so a receiver without the shared seed key can't distinguish it from random bytes.
"""

from hashlib import blake2b
from secrets import token_bytes
from typing import Optional, Tuple

from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt, crypto_aead_xchacha20poly1305_ietf_encrypt, crypto_scalarmult, crypto_scalarmult_base
from nacl.exceptions import CryptoError


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _blake2b(*parts: bytes, size: int) -> bytes:
    digest = blake2b(digest_size=size)
    for part in parts:
        digest.update(part)
    return digest.digest()


class Symmetric:
    """XChaCha20-Poly1305 AEAD (24-byte extended nonce), combined ciphertext||tag encoding."""

    _CHACHA_KEY_LENGTH = 32

    nonce_size = 24
    tag_size = 16
    ciphertext_overhead = nonce_size + tag_size

    def __init__(self, key: Optional[bytes] = None):
        self._key = token_bytes(self._CHACHA_KEY_LENGTH) if key is None else key

    def encrypt(self, plaintext: bytes, additional_data: Optional[bytes] = None, nonce: Optional[bytes] = None) -> bytes:
        """
        Encrypt `plaintext`. If `nonce` isn't given, one is generated randomly and prepended to
        the output. If it is given, the caller is asserting it's unique for this key by
        construction (e.g. derived from a message ID + chunk index), and it is *not* included in
        the output — the caller is responsible for reconstructing it on decrypt.
        """

        if nonce is None:
            nonce = token_bytes(self.nonce_size)
            embed_nonce = True
        else:
            embed_nonce = False

        ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, additional_data, nonce, self._key)
        return (nonce + ciphertext) if embed_nonce else ciphertext

    def decrypt(self, ciphertext: bytes, additional_data: Optional[bytes] = None, nonce: Optional[bytes] = None) -> bytes:
        """Inverse of `encrypt`. Pass the same `nonce` that was passed to `encrypt`, if any."""

        if nonce is None:
            nonce, ciphertext = ciphertext[: self.nonce_size], ciphertext[self.nonce_size :]
        try:
            return bytes(crypto_aead_xchacha20poly1305_ietf_decrypt(ciphertext, additional_data, nonce, self._key))
        except CryptoError as error:
            raise ValueError("Decryption failed! Ciphertext, additional data, nonce or key is invalid.") from error


class Asymmetric:
    """X25519 key exchange with the ephemeral public key hidden behind a keyed XOR mask."""

    _SYMMETRIC_HASH_SIZE = 32
    _PUBLIC_KEY_SIZE = 32
    _SEED_SIZE = 8
    _N_SIZE = 2

    ciphertext_overhead = _PUBLIC_KEY_SIZE + _N_SIZE + Symmetric.ciphertext_overhead

    @property
    def public_key(self) -> bytes:
        return self._public_key + self._seed_key

    @property
    def private_key(self) -> bytes:
        if self._private_key is None:
            raise ValueError("This Asymmetric instance only holds a public key!")
        return self._private_key + self._seed_key

    def __init__(self, key: Optional[bytes] = None, private: bool = True) -> None:
        self._private_key: Optional[bytes]

        if key is None:
            self._private_key = token_bytes(self._PUBLIC_KEY_SIZE)
            self._public_key = crypto_scalarmult_base(self._private_key)
            self._seed_key = token_bytes(self._SEED_SIZE)
        elif private:
            self._private_key = key[: self._PUBLIC_KEY_SIZE]
            self._public_key = crypto_scalarmult_base(self._private_key)
            self._seed_key = key[self._PUBLIC_KEY_SIZE :]
        else:
            self._private_key = None
            self._public_key = key[: self._PUBLIC_KEY_SIZE]
            self._seed_key = key[self._PUBLIC_KEY_SIZE :]

    def _compute_symmetric_key(self, shared_secret: bytes, client_key: bytes, server_key: bytes) -> bytes:
        return _blake2b(shared_secret, client_key, server_key, size=self._SYMMETRIC_HASH_SIZE)

    def _hide_public_key(self, public_key: bytes) -> bytes:
        number_n = token_bytes(self._N_SIZE)
        mask = _blake2b(number_n, self._seed_key, size=self._SYMMETRIC_HASH_SIZE)
        return number_n + _xor_bytes(public_key, mask)

    def _reveal_public_key(self, public_bytes: bytes) -> bytes:
        number_n = public_bytes[: self._N_SIZE]
        mask = _blake2b(number_n, self._seed_key, size=self._SYMMETRIC_HASH_SIZE)
        return _xor_bytes(public_bytes[self._N_SIZE :], mask)

    def encrypt(self, plaintext: bytes) -> Tuple[bytes, bytes]:
        ephemeral_private_key = token_bytes(self._PUBLIC_KEY_SIZE)
        ephemeral_public_key = crypto_scalarmult_base(ephemeral_private_key)
        shared_secret = crypto_scalarmult(ephemeral_private_key, self._public_key)
        symmetric_key = self._compute_symmetric_key(shared_secret, ephemeral_public_key, self._public_key)
        hidden_public_key = self._hide_public_key(ephemeral_public_key)
        return symmetric_key, hidden_public_key + Symmetric(symmetric_key).encrypt(plaintext, ephemeral_public_key)

    def decrypt(self, ciphertext: bytes) -> Tuple[bytes, bytes]:
        if self._private_key is None:
            raise ValueError("This Asymmetric instance only holds a public key, it cannot decrypt!")
        hidden_public_key_len = self._N_SIZE + self._PUBLIC_KEY_SIZE
        hidden_public_key, ciphertext = ciphertext[:hidden_public_key_len], ciphertext[hidden_public_key_len:]
        ephemeral_public_key = self._reveal_public_key(hidden_public_key)
        shared_secret = crypto_scalarmult(self._private_key, ephemeral_public_key)
        symmetric_key = self._compute_symmetric_key(shared_secret, ephemeral_public_key, self._public_key)
        return symmetric_key, Symmetric(symmetric_key).decrypt(ciphertext, ephemeral_public_key)
