# airwire

A hybrid messaging application that seamlessly switches between web and SMS transport.
All messages are stored locally on the user's device — the server acts only as a relay, never persisting message content.

## Core Concepts

### Local-Only Storage

Messages are never stored on the server.
The server receives, relays, and discards.
All message history lives exclusively on the user's device.

### Delivery Statuses

Every message carries a delivery status:

| Status        | Meaning                                        |
|---------------|-------------------------------------------------|
| **Pending**   | Message is still being transmitted to the server |
| **Sent**      | Server has received the message                  |
| **Delivered** | Message was delivered to the recipient's device  |

### Timeouts and Retries

The server enforces timeouts with retries on every message:

- If a message is not fully **received** from the sender within the timeout, it becomes **unsent** and the sender is notified.
- If a message is not fully **delivered** to the recipient within the timeout, it becomes **undelivered** and the sender is notified.
- In both cases the message is discarded from the server.

**Exception:** notification messages (e.g. presence updates) are fire-and-forget — no retransmission, no timeout.

## Transport Modes

The server tracks each user's current transport mode and routes messages accordingly.

### Web Mode

- **Sending:** the client calls the server API directly; the server acknowledges.
- **Receiving:** the server sends a Firebase push notification, the client comes online, downloads the message, and acknowledges.

### SMS Mode

- **Sending:** the client splits the message into SMS-sized pieces and sends them; the server acknowledges via SMS.
- **Receiving:** the server does the same in reverse.

### Mode Switching

1. When a device comes online, it calls the API to declare **web mode** (unless the user has restricted the app to SMS-only).
2. When a device goes offline, it sends an SMS to declare **SMS mode** (if available, unless the user has restricted the app to web-only).

## Message Format

Every message is a Protobuf structure containing:

| Field       | Required | Description              |
|-------------|----------|--------------------------|
| `id`        | Yes      | Rolling 4-byte message ID |
| `sender`    | Yes      | Sender identifier (phone number) |
| `recipient` | Yes      | 16-byte receiver ID       |
| `type`      | Yes      | Message type              |
| `payload`   | No       | Optional message body     |

## Encryption

### Web Mode

Standard TLS.
The entire size-prefixed Protobuf message is sent over a TLS connection.

### SMS Mode

Fully asynchronous encryption using **X25519** key exchange and **XChaCha20-Poly1305** for symmetric encryption.

- **Service messages** (including data message headers) carry the full asymmetric overhead.
- **Data message bodies** are encrypted symmetrically only, to save space.

The message is split into header and body.
Each chunk is prefixed with the message ID and chunk number.
Header and body are encrypted separately.

### SMS Size Budget

SMS is limited to 160 ASCII characters (160 bytes). Per-chunk overhead:

| Component                | Size     |
|--------------------------|----------|
| Message ID (rolling)     | 4 bytes  |
| Receiver ID              | 16 bytes |
| Symmetric encryption tag | 16 bytes |
| Base64 encoding overhead | 12 bytes |
| **Total overhead**       | **48 bytes** |
| **Usable payload**       | **84 bytes** |

This constraint means voice notes are realistically transferable over MMS only.

## MMS Support (Premium)

Users can opt in to MMS transport.
The process follows the same chunked protocol as SMS, but with larger payloads.
To make MMS content appear benign, the app offers two encoding strategies:

1. **Markov-chain text** — the encrypted payload is processed and encoded into human-like natural language text.
2. **Image steganography** — the payload is embedded into a generated image (the image appears random/noisy).

> **Note:** MMS availability varies by country and carrier.

## Pricing

The core application (web mode + SMS mode) is free.
**MMS support is a premium feature.**

## License

TODO!
