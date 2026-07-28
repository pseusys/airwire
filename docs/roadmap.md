# Implementation Roadmap — *airwire* (product track)

> **Status:** draft plan (v0).
> **Scope:** the [airwire](../README.md) product track only. The separate audio/channel-agnostic
> research track, [airwave](./research-proposal.md), is out of scope for everything below — no
> voiceband/vocoder/acoustic encoding work belongs in this roadmap.

## Guiding principle: prove the hard parts before touching a platform

None of this needs to start as a mobile app. The parts of airwire that are genuinely hard to get
right — the crypto, the wire format, the size-budget math, the steganographic encoders — are pure
functions of bytes in, bytes out. They can be written, fuzzed, and round-trip tested in Python in
an afternoon-sized feedback loop, with no emulator, no device, and no mobile toolchain. Mobile
work should start only once that core is proven and frozen, so the Android/iOS code is "just" a
UI and OS-integration layer around an already-correct engine, not a place where crypto bugs get
discovered for the first time.

This also directly answers the earlier "testing is hard to impossible" concern: it isn't, for
this scope. Phase 0 needs nothing but `pytest`. Phase 1 (real SMS) needs nothing but the Android
emulator's built-in SMS injection (`adb emu sms send`) between two emulator instances, plus a pair
of $5–10 prepaid SIMs for real-device validation later. No radio hardware, no lab equipment — that
requirement belongs to airwave, not here.

## Ruled out — don't rebuild these

Checked against existing prior art before scoping the phases below:

| Space | Existing project | Verdict |
|---|---|---|
| Encrypted SMS/MMS on Android, no server | Silence (defunct, source gone) | Space is open, but only for airwire's *differentiators* — relay server, delivery status, web/SMS switching, steganographic disguise. A bare "encrypt and send SMS" clone would just be a worse, unmaintained Silence. |
| Bluetooth/WiFi mesh chat | Briar (audited, Android-only), Bitchat (Dorsey, cross-platform, mainstream), Bridgefy (cross-platform, but [broken crypto](https://eprint.iacr.org/2021/214.pdf)) | Don't build general mesh chat. Bridgefy is also the cautionary tale if we ever touch BLE: reuse proven crypto, don't roll mesh-routing security from scratch. |
| Off-grid radio messaging | Meshtastic (LoRa, mature, active) | Confirms radio needs dedicated hardware phones don't have. Not in scope; if ever wanted, interop with Meshtastic rather than reinvent. |
| Morse code *input* | Gboard's Morse keyboard (Android + iOS, built with accessibility advocate Tania Finlayson), iOS Switch Control native Morse | Don't build a custom Morse keyboard. Any standard text field, including airwire's compose box, already gets this for free. |

## Phase 0 — Core engine PoC (Python, no app)

**Status: in progress.** Crypto and chunking are implemented and tested in [`core/`](../core/);
steganographic encoders are not started yet. Every non-obvious technical choice made along the
way — and there have been several — is logged in
[`docs/design-decisions.md`](./design-decisions.md) as it happens, rather than only living in
code comments.

The deliverable is a small, well-tested Python package implementing the wire-level logic from the
[README](../README.md), independent of any platform:

- **Crypto primitives** — X25519 key exchange + XChaCha20-Poly1305 AEAD, via
  [`pynacl`](https://pynacl.readthedocs.io/) (libsodium bindings — audited reference
  implementation, not hand-rolled). Separate asymmetric path for service messages/headers vs.
  symmetric-only for data bodies, per the README's design.
- **Message framing** — the Protobuf schema (`id`, `sender`, `recipient`, `type`, `payload`);
  round-trip serialize/deserialize tests.
- **Chunking** — no longer tied to a fixed SMS byte budget. A message is cut into large,
  configurably-sized "hyperslices" (1KB by default), each encrypted as a single AEAD operation and
  split into wire-sized chunks carrying only a cheap sequence number — no per-chunk crypto
  overhead — preceded by an encrypted header and followed by a stop-and-wait
  acknowledgement/retry exchange. See
  [design decision #1](./design-decisions.md#1-minimizing-cryptography-overhead) for why, and the
  concrete overhead numbers versus the fixed-budget design it replaced.
- **Obfuscation encoders** — Markov-chain text disguise and image steganography, each as an
  independent encode/decode module (`Pillow` + `numpy` for image; a plain n-gram model, no ML
  dependency needed, for text).
- **Test strategy** — `pytest` round trips for: encrypt→chunk→reassemble→decrypt,
  encrypt→stego-encode→stego-decode→decrypt, and tamper detection (corrupted auth tag must fail
  closed). No device needed anywhere in this phase.
- **Bonus, low-cost extension:** this PoC becomes the source of *cross-implementation test
  vectors* — encrypt with Python, assert the future Kotlin/Swift client decrypts it correctly, and
  vice versa. Cheap insurance against the mobile port silently drifting from the proven design.
- Optional: a minimal Python relay-server stub (single process, in-memory) to de-risk the
  delivery-status/timeout/retry state machine the same way, before Phase 2.

**Exit criterion:** a stranger can `pip install` the package, run the test suite, and trust the
protocol is sound — before a single line of Kotlin exists.

## Phase 1 — Android-native client

Wraps the proven Phase 0 core in a real app: web mode, SMS mode, mode switching, local-only
message storage. This is where Silence-style background SMS send/receive lives — proven feasible
(`SmsManager`, manifest-registered `SMS_RECEIVED` receiver), just built on a stronger foundation
than Silence had.

**Testable via:** Android emulator SMS injection for the full dev loop; two prepaid SIMs for
carrier-reality validation before shipping.

## Phase 2 — Relay server + delivery status + MMS

The server side: relay-only (never persists content), Pending/Sent/Delivered status tracking with
timeouts/retries, Firebase push for web-mode receive, and the MMS premium tier (Markov text /
image steganography from Phase 0, now wired into a real send/receive path).

## Phase 3 — Resilience & interop

- **Graceful degradation** — detect a recipient who isn't running airwire (failed capability
  handshake) and fall back to plain, readable SMS instead of an unreadable blob.
- **Disguised serverless fallback** — when the relay is unreachable, fall back to direct
  phone-to-phone SMS using the *same* crypto/framing as everything else, carried through the
  Phase 0 steganographic encoders. (The transport mechanism here is admittedly what Silence
  proved out; the disguise layer carried over it is the part Silence never had.)
- **SIM-bank gateway economics** — decide whether the relay server's own SMS sending runs on a
  paid API (Twilio-style) or a small bank of prepaid-SIM Android phones. Pure ops decision, no
  app-side work, but it materially affects per-message cost at the population this targets.

## Phase 4 — Reach extension

- **BLE last-hop bridge** — *not* general mesh routing (see "ruled out" above). One hop only: a
  phone with no cell signal hands a message to a physically nearby phone that has signal, which
  sends it as a normal airwire SMS/MMS. Reuses the Phase 0 crypto stack as-is.
- **iOS client** — necessarily reduced, since iOS has no SMS send/receive API at all. Two
  non-exclusive paths: (a) manual compose via share sheet + Shortcuts personal automation for a
  best-effort receive trigger, or (b) treat iOS purely as a BLE leaf node bridged by an Android
  gateway from Phase 4's first bullet — iOS's Core Bluetooth background wake is real (if
  OS-throttled), unlike its SMS access, which is exactly how Bitchat ships on the App Store at
  all.

## Phase 5 — Accessibility: Morse *output*

Not input (Gboard/Switch Control already own that, see "ruled out"). This is narrower and
genuinely open: convert a received, already-decrypted message into a vibration and/or camera-flash
Morse playback, so it can be read without looking at or listening to the phone. Existing OS
flash/vibrate-for-notification features only signal that something arrived; this conveys the
content itself.

## Phase 6 — Community broadcast

One-to-many SMS for alerts/bulletins (evacuation routes, supply points, weather), reusing the
Phase 0/2 chunking and crypto with a shared group key. Directly serves the "people in need"
framing with no new transport work.

## Phase 7 — Push-notification transport (optional, opt-in, last)

A third transport mode (alongside Web and SMS), for restrictive/firewalled networks that block
general internet but can't block Apple/Google's push infrastructure without breaking every app on
the device — an active research area
([FOCI 2023](https://www.petsymposium.org/foci/2023/foci-2023-0009.pdf),
[CenPush, PETS 2025](https://petsymposium.org/popets/2025/popets-2025-0153.pdf)), already deployed
in the Tor Project's Orbot for bridge-line distribution. Deliberately last and explicitly optional
because of two real costs:

- **Privacy:** Apple/Google can see (and [governments have compelled disclosure of](https://techcrunch.com/2023/12/06/us-senator-warns-governments-spying-apple-google-smartphone-users-via-push-notifications/))
  push-token metadata — who's talking to whom, when. This is the one mode where a third party sits
  inside airwire's trust model; must be clearly labeled to the user as lower-privacy, never a
  silent fallback.
- **Platform risk:** using FCM as a generic message channel is also how real Android malware
  (DoNot's Firestarter, FireScam) operates. Needs a transparent, disclosed implementation to avoid
  tripping app-store malware heuristics.

Still not "serverless" despite appearances — FCM/APNs sending requires the relay server to hold
privileged credentials, so this is an additional transport fed by the Phase 2 server, not a way to
remove it.

## Non-goals (explicitly out of scope for this roadmap)

- Anything encoding data into audio/voice/DTMF — that's airwave, tracked separately.
- General-purpose Bluetooth/WiFi mesh routing — Briar and Bitchat already do this well.
- LoRa/ham-radio transport — Meshtastic already owns this; interop only, if ever.
- A custom Morse *input* method — Gboard and Switch Control already own this.
