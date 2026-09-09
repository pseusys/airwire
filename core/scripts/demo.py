"""
Manual, human-readable walkthrough of the crypto + chunking + wire-encoding pipeline: encrypts a
message, packs it into wire-sized hyperchunk messages under a chosen `ChunkEncoding` -- including,
now, one whole synthesized image per hyperchunk for the `sources.synthesis` flavors, which go
through exactly the same `pack_hyperchunk`/`receive_hyperchunk` path as everything else (see
memory/wire-protocol.md) -- then receives and decrypts it back, printing what happens at each step.
Not a substitute for the test suite (`poetry poe test`) -- this is for eyeballing what actually goes
over the wire in each mode.

`poetry poe demo-handshake` (`run_handshake`, below) is a separate entry point demonstrating
`sources/handshake.py`'s session establishment end to end -- see memory/handshake.md.
"""

from typing import Dict, Optional

from sources.chunking import DEFAULT_CHUNK_SIZE, DEFAULT_MMS_CHUNK_SIZE, ChunkingError, _decrypt_header, decode_ack, pack_hyperchunk, receive_hyperchunk, unpack_hyperchunk
from sources.crypto import Symmetric
from sources.encodings import BASE64, PLAIN, ChunkEncoding
from sources.handshake import derive_session_key, generate_ephemeral_keypair, obfuscation_for_sender, receive_certificate, send_certificate
from sources.markov import MARKOV_ENG, MARKOV_RUS
from sources.synthesis import SYNTHESIS_ATTRACTOR, SYNTHESIS_REACTION_DIFFUSION, SYNTHESIS_VALUE_NOISE, SYNTHESIS_VORONOI
from sources.textures import TEXTURES

_MODES: Dict[str, ChunkEncoding] = {
    "plain": PLAIN,
    "base64": BASE64,
    "markov": MARKOV_ENG,
    "markov_rus": MARKOV_RUS,
    "value_noise": SYNTHESIS_VALUE_NOISE,
    "voronoi": SYNTHESIS_VORONOI,
    "reaction_diffusion": SYNTHESIS_REACTION_DIFFUSION,
    "attractor": SYNTHESIS_ATTRACTOR,
}

_IMAGE_MODES = set(TEXTURES)


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


def run(
    text: str = "Hello, airwire! This is a demo message.",
    mode: str = "plain",
    header_mode: Optional[str] = None,
    chunk_size: Optional[int] = None,
    image_path: str = "output.png",
) -> int:
    """
    Encrypt `text`, pack it as one hyperchunk using the `mode` wire encoding, print what actually
    goes out, then decrypt it back to confirm the round trip. `mode` is any registered
    `ChunkEncoding` name -- plain/base64/markov/markov_rus, or a texture flavor
    (value_noise/voronoi/reaction_diffusion/attractor), which yields exactly one wire chunk (the
    whole synthesized image, saved to `image_path`) instead of many small ones. `header_mode`, if
    given, additionally disguises the header message the same way -- see memory/handshake.md for
    where that choice is meant to come from in practice.
    :return: exit code integer -- 0 on a successful round trip, 1 otherwise.
    """

    if mode not in _MODES:
        print(f"Unknown mode {mode!r}; supported: {sorted(_MODES)}.")
        return 1
    if header_mode is not None and header_mode not in _MODES:
        print(f"Unknown header_mode {header_mode!r}; supported: {sorted(_MODES)}.")
        return 1

    encoding = _MODES[mode]
    header_encoding = _MODES[header_mode] if header_mode is not None else None
    is_image = mode in _IMAGE_MODES
    # Any disguised header inflates far past an SMS-scale budget (a Markov-disguised ~136-byte
    # ciphertext alone typically becomes several KB of "natural" text), not just an image one.
    needs_mms_budget = is_image or header_encoding is not None
    resolved_chunk_size = chunk_size if chunk_size is not None else (DEFAULT_MMS_CHUNK_SIZE if needs_mms_budget else DEFAULT_CHUNK_SIZE)
    plaintext = text.encode("utf-8")
    symmetric = Symmetric()  # stands in for an already-established session key.
    demo_hyperchunk_id = 0  # this demo only ever sends one hyperchunk.

    print(f"Mode: {mode}  (chunk_size={resolved_chunk_size}, header_mode={header_mode})")
    print(f"Plaintext ({len(plaintext)} bytes): {text!r}")

    try:
        messages = pack_hyperchunk(symmetric, plaintext, demo_hyperchunk_id, chunk_size=resolved_chunk_size, encoding=encoding, header_encoding=header_encoding)
    except ChunkingError as error:
        print(f"\nFailed to pack: {error}")
        return 1

    header, chunks = messages[0], messages[1:]
    wire_bytes = sum(len(message) for message in messages)
    chunk_id_size = _decrypt_header(symmetric, header, header_encoding).chunk_id_size

    print(f"\nPacked into {len(messages)} wire message(s) ({len(chunks)} data chunk(s) + 1 header), {wire_bytes} bytes total:")
    print(f"  header ({len(header)} bytes{', disguised' if header_encoding else ', encrypted'}): {_printable(header)}")
    if is_image:
        payload = chunks[0][chunk_id_size:]
        with open(image_path, "wb") as file:
            file.write(payload)
        print(f"  chunk 0: image payload ({len(payload)} bytes), saved to {image_path}")
    else:
        for index, chunk in enumerate(chunks):
            chunk_id, chunk_payload = chunk[:chunk_id_size], chunk[chunk_id_size:]
            print(f"  chunk {index}: id={chunk_id.hex()}, payload ({len(chunk_payload)} bytes): {_printable(chunk_payload)}")

    if wire_bytes:
        print(f"\nRaw-byte efficiency: {len(plaintext)}/{wire_bytes} = {len(plaintext) / wire_bytes * 100:.1f}%")

    recovered, ack = receive_hyperchunk(symmetric, messages, header_encoding=header_encoding)
    if ack is not None:
        acked_id, acked_success = decode_ack(symmetric, ack)
        print(f"\nAck ({len(ack)} bytes, encrypted): hyperchunk {acked_id}, success={acked_success}")

    success = recovered == plaintext
    print(f"Round trip: {'OK' if success else 'FAILED'}")
    if recovered is not None:
        print(f"Recovered ({len(recovered)} bytes): {recovered.decode('utf-8', errors='replace')!r}")

    return 0 if success else 1


def run_handshake(
    text: str = "Hello, this went through a real handshake!",
    alice_id: str = "+15551234567",
    bob_id: str = "+15559876543",
) -> int:
    """
    Demonstrates memory/handshake.md end to end -- certificate exchange, session key derivation,
    then one hyperchunk of real data sent through the result -- printing each phase's output.
    `alice_id`/`bob_id` are the platform-specific transport identifiers each side's own messages
    get their (independently-derived, no-negotiation-needed) obfuscation mode from.
    :return: exit code integer -- 0 on a successful round trip, 1 otherwise.
    """

    alice_mode = obfuscation_for_sender(alice_id)
    bob_mode = obfuscation_for_sender(bob_id)
    print("Phase 0: obfuscation modes derived from sender IDs alone, no exchange needed:")
    print(f"  {alice_id}: {type(alice_mode).__name__}")
    print(f"  {bob_id}: {type(bob_mode).__name__}")

    print("\nPhase 1: certificate exchange")
    alice_keys = generate_ephemeral_keypair()
    bob_keys = generate_ephemeral_keypair()
    cert_from_alice = send_certificate(alice_id, alice_keys.public_key)
    cert_from_bob = send_certificate(bob_id, bob_keys.public_key)
    print(f"  Alice's certificate: {len(cert_from_alice)} bytes, disguised as {type(alice_mode).__name__}")
    print(f"  Bob's certificate:   {len(cert_from_bob)} bytes, disguised as {type(bob_mode).__name__}")

    bobs_view_of_alice = receive_certificate(alice_id, cert_from_alice)
    alices_view_of_bob = receive_certificate(bob_id, cert_from_bob)
    if bobs_view_of_alice != alice_keys.public_key or alices_view_of_bob != bob_keys.public_key:
        print("\nCertificate exchange FAILED: recovered public keys don't match what was sent.")
        return 1
    print("  Both sides recovered the other's ephemeral public key correctly.")

    print("\nPhase 2: session key derivation (ECDH over the exchanged ephemeral keys)")
    alice_session = derive_session_key(alice_keys.private_key, alice_keys.public_key, alices_view_of_bob)
    bob_session = derive_session_key(bob_keys.private_key, bob_keys.public_key, bobs_view_of_alice)

    print("\nPhase 3: data transfer, using the session key and Alice's own obfuscation mode")
    plaintext = text.encode("utf-8")
    messages = pack_hyperchunk(alice_session, plaintext, hyperchunk_id=0, chunk_size=DEFAULT_MMS_CHUNK_SIZE, encoding=alice_mode, header_encoding=alice_mode)
    print(f"  Packed into {len(messages)} wire message(s), {sum(len(m) for m in messages)} bytes total.")
    _, recovered = unpack_hyperchunk(bob_session, messages, header_encoding=alice_mode)

    success = recovered == plaintext
    print(f"\nRound trip: {'OK' if success else 'FAILED'}")
    if recovered is not None:
        print(f"Recovered ({len(recovered)} bytes): {recovered.decode('utf-8', errors='replace')!r}")

    return 0 if success else 1
