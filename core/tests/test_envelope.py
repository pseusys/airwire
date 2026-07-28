from sources.proto import envelope_pb2


def test_envelope_serialize_round_trip() -> None:
    original = envelope_pb2.Envelope(
        id=b"\x00\x01\x02\x03",
        sender="+15555550100",
        recipient=b"\x10" * 16,
        type=envelope_pb2.MESSAGE_TYPE_DATA,
        payload=b"hello",
    )

    parsed = envelope_pb2.Envelope()
    parsed.ParseFromString(original.SerializeToString())

    assert parsed.id == original.id
    assert parsed.sender == original.sender
    assert parsed.recipient == original.recipient
    assert parsed.type == original.type
    assert parsed.payload == original.payload


def test_envelope_payload_is_optional() -> None:
    envelope = envelope_pb2.Envelope(id=b"\x00\x00\x00\x00", sender="+15555550100", recipient=b"\x00" * 16, type=envelope_pb2.MESSAGE_TYPE_PRESENCE)
    parsed = envelope_pb2.Envelope()
    parsed.ParseFromString(envelope.SerializeToString())
    assert parsed.payload == b""
