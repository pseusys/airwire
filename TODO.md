# TODO — work queue, tiered by when it can happen

**Open work only.**
Settled decisions live in [`CHANGELOG.md`](CHANGELOG.md) for what was done, and in [`memory/rejected-ideas.md`](memory/rejected-ideas.md) for what was deliberately not done, both with the evidence.

Every item states **What / How / Why** so a future agent can act on it cold, without reconstructing the reasoning.
If you add an item and cannot fill in all three, it is not ready to be an item yet.

## The tiers

| Tier | Meaning |
| --- | --- |
| §A NOW | Actionable this session or in the next few days. |
| §B UPON \<EVENT\> | Held deliberately. `<EVENT>` is a major, infrequent effort; batching avoids doing it twice. |
| §C BLOCKED | Cannot progress by effort. Waiting on elapsed time, or on data nobody records yet. |
| §D LATER | Unblocked and understood, just not worth the cycles now. |
| §E PROJECT EVOLUTION | Direction changes, not tasks. Needs a decision before it becomes work. |

Started 2026-09-08 (migrated from `docs/roadmap.md` and `docs/design-decisions.md`'s open TODO list, plus this session's own findings).

There is no product deployment yet — no relay server, no mobile client shipped anywhere — so there
is no "in the repo but not deployed" section to maintain. `web-demo/` auto-deploys to GitHub Pages
on every push to `main`; it's a stateless demo, not the product.

---

## §A NOW

### Completed and drained (2026-09-09)

| Item | Outcome | Written up in |
| --- | --- | --- |
| A1. Run `client/`'s tests and lint in CI | Done — `.github/workflows/client.yml` added (lint + test jobs, both packages) | `CHANGELOG.md` |
| A2. Add a linter to `web-demo/` | Done — `angular-eslint@19` via `ng add`, wired into `.github/workflows/web-demo.yml`; 3 pre-existing violations auto-fixed | `CHANGELOG.md` |
| A4. Fix `core/` source comments pointing at deleted `docs/design-decisions.md` | Done — 8 files, 22 lines fixed (broader than originally scoped); also fixed a pre-existing mypy failure found along the way | `CHANGELOG.md` |
| A5. Web-demo unit test coverage gap | Done — 5 new spec files, 42 tests, all passing; 0 lint issues | `CHANGELOG.md` |
| A3. Full repo coding-guidelines review | Done — found and fixed 1 real violation (inline `import json`), documented 2 legitimate pre-existing exceptions, filed 1 finding needing a decision (E3) | `CHANGELOG.md` |
| A7. Audit `client/`'s READMEs | Done — real content for `client/app/README.md` (was Flutter-CLI boilerplate) and new `client/medium/README.md` (had none) | `CHANGELOG.md` |
| A6. Root `README.md`'s License placeholder | Done — owner chose proprietary/all-rights-reserved, stated explicitly | `CHANGELOG.md` |
| A8. Migrate `docs/superpowers/` into `memory/` | Done — 6 already-shipped files retired (content already covered, plus 3 new `rejected-ideas.md` entries); 1 draft spec and 3 unexecuted plans deliberately kept; found and fixed 2 more dangling doc-links in `core/sources/markov.py`; added a house rule for future specs/plans | `CHANGELOG.md` |
| D13. Whole-canvas-aware image generation | Done — gap-row patches now scored against the source texture's true content at that position (for 3 of 4 flavors); measured and confirmed a real visual improvement, not just the alignment bug fix | `CHANGELOG.md` |
| D3. Image texture synthesis visual quality on large-scale-structure textures | Closed, superseded — D13's mechanism addressed the same two flavors this named, via a different approach than either of this item's own untried directions | `CHANGELOG.md` |

---

## §B UPON \<EVENT\>

Nothing batched here yet — no expensive, infrequent event has been identified for this project.

---

## §C BLOCKED — waiting on time or data

### C1. VK ID app registration needed to confirm three open OAuth/API assumptions

**Unblock condition:** a real VK ID app is registered (`client_id` and redirect URI) and a live
login and `graph.user.messages` round trip is run between two real accounts.

Three things currently can't be validated without that: (1) `client_id` is a literal
`'PLACEHOLDER_APP_ID'` in `client/app/lib/main.dart:19`; (2) the OAuth `scope` string requested at
authorize-time (`client/medium/lib/src/vk_id_oauth.dart`'s `buildAuthorizeUrl`) is `'email'`, not a
real messaging permission — the correct scope name was never confirmed against VK ID's actual scope
list; (3) whether `graph.user.messages` requires the two accounts to already be OK.ru contacts before
messaging cold (a `group.isMessagesAllowed`-style gate exists elsewhere in the API, suggesting one
might apply here too) is untested — `client/medium/lib/src/odnoklassniki_medium.dart` has no handling
for this either way.
All three were flagged as open risks in the (now-retired) Odnoklassniki
prototype design spec; none are blocking further `client/` development, since everything else in
the medium wrapper is unit-tested against mocked HTTP.

---

## §D LATER

### D1. Overhead-reduction follow-ups on `core/sources/chunking.py`

**What.** Three related, not-yet-attempted changes, roughly in expected-payoff order:
inline small hyperslices (collapse header+single-chunk into one message when the whole ciphertext
fits alongside the header fields); selective retransmission (a failure ack names which chunk indices
are actually missing, instead of triggering a full hyperchunk resend); adaptive hyperslice size
(shrink on a lossy link, grow on a clean one).

**How.** Each is a self-contained change to `chunking.py`; selective retransmission needs the ack
schema question flagged in `memory/rejected-ideas.md`'s nonce-derivation entry resolved first (an
open-ended missing-chunk list doesn't fit the "derive the nonce from content" trick that was tried
and reverted there).

**Why.** None of these are blocking — the hyperslice model already measures well (see
`CHANGELOG.md`'s 2026-07-28 entry) — but each is a real, scoped efficiency win queued behind higher
priority: proving the disguise mechanisms end-to-end (done) and, since M2, the mobile port.

### D2. Derive `HyperchunkHeader.nonce` (the data nonce) instead of transmitting it

**What.** Unlike the header's own encryption nonce (impossible to derive, see
`memory/rejected-ideas.md`), the hyperslice *data* nonce could potentially be derived from
`hyperchunk_id`, since decryption of the data always happens strictly after the header is already
decrypted (the decoder already knows `hyperchunk_id` by then).

**How.** Needs its own check first: confirm "same `hyperchunk_id`, different hyperslice content" can
never legitimately happen (expected, given the same uniqueness invariant the hyperchunk ID already
relies on elsewhere) — don't assume it by analogy to the ack case, which turned out wrong twice
before landing on a safe derivation there.

**Why.** `sources/crypto.py`'s `derive_nonce` helper already exists for exactly this and currently has
no caller in the data path.
Flagged rather than attempted immediately specifically because the
analogous ack-nonce work needed two rejected attempts before finding a safe derivation — this deserves
its own scrutiny, not a quick copy of that reasoning.

### D4. Cross-implementation test vectors

**What.** Use `core/`'s Python implementation as the source of test vectors: encrypt with Python,
assert a future client-side implementation decrypts it correctly, and vice versa.

**How.** Not started.
Depends on a client-side protocol implementation existing to test against —
`client/`'s Dart port is drafted in `docs/superpowers/plans/` but not built yet.

**Why.** Cheap insurance against a future mobile/client port silently drifting from the proven Python
design — cited in `docs/roadmap.md`'s original Phase 0 scope as a low-cost bonus extension.

### D5. Minimal relay-server stub

**What.** A single-process, in-memory Python relay-server stub, to de-risk the
delivery-status/timeout/retry state machine before it's built for real in Phase 2.

**How.** Not started; scoped as intentionally minimal (in-memory, no persistence, no real deployment
target) purely to validate the state machine design.

**Why.** Same "prove it before building the real thing" principle Phase 0 already applied to the
crypto/wire-format/disguise work.

### D6. Android-native client (Phase 1)

**What.** Wrap the proven `core/` protocol in a real Android app: web mode, SMS mode, mode switching,
local-only message storage — Silence-style background SMS send/receive (`SmsManager`,
manifest-registered `SMS_RECEIVED` receiver).

**How.** Testable via Android emulator SMS injection (`adb emu sms send`) between two emulator
instances for the dev loop; two prepaid SIMs for carrier-reality validation before shipping.
Three
implementation plans for a pure-Dart `protocol/` package already exist, approved but unexecuted, in
`docs/superpowers/plans/2026-08-30-protocol-core-dart.md`, `2026-08-30-handshake-dart.md`, and
`2026-08-31-key-rotation-dart.md` — check these before drafting a new one; they target the
directional-key/rotation crypto scheme in `memory/handshake.md`'s "Target spec" section, not `core/`'s
current implementation, so confirm which one this phase actually wants first.

**Why.** The next phase once Phase 0's core is proven and frozen — deliberately sequenced after, so
Android/iOS code is "just" a UI/OS-integration layer around an already-correct engine, not where
crypto bugs get discovered for the first time.

### D7. Relay server, delivery status, and MMS (Phase 2)

**What.** The server side: relay-only (never persists content), Pending/Sent/Delivered status
tracking with timeouts/retries, Firebase push for web-mode receive, and the MMS premium tier wired
into a real send/receive path.

**How.** Not started; depends on D6 (Android client) existing to relay for.

**Why.** Completes the product's server-side half — everything up to this point is client-only.

### D8. Resilience and interop (Phase 3)

**What.** Graceful degradation to plain readable SMS when a recipient isn't running airwire
(failed capability handshake); a disguised serverless fallback (direct phone-to-phone SMS using the
same crypto/framing, when the relay is unreachable).

**How.** Not started; depends on D6/D7.

**Why.** Silence already proved the direct-SMS transport mechanism works; airwire's disguise layer
carried over it is the part Silence never had.
See also E1 for the one genuine open decision in this
phase (SIM-bank gateway economics).

### D9. Reach extension (Phase 4)

**What.** A one-hop BLE bridge (not general mesh routing — see
[`memory/rejected-ideas.md`](memory/rejected-ideas.md)): a phone with no cell signal hands a message
to a nearby phone that has signal, which sends it as a normal airwire SMS/MMS. An iOS client,
necessarily reduced (no SMS API at all) — either manual compose via share sheet + Shortcuts, or a
pure BLE leaf node bridged by an Android gateway.

**How.** Not started; reuses the Phase 0 crypto stack as-is. iOS's Core Bluetooth background wake is
real (if OS-throttled), the same mechanism Bitchat ships on the App Store with.

**Why.** Extends reach without rebuilding transport security — BLE routing security is reused, not
reinvented (see the Bridgefy caution in `memory/rejected-ideas.md`).

### D10. Morse output (Phase 5)

**What.** Convert a received, already-decrypted message into a vibration and/or camera-flash Morse
playback, so it can be read without looking at or listening to the phone.

**How.** Not started.
Distinct from Morse *input*, which Gboard/Switch Control already provide for
free (see [`memory/rejected-ideas.md`](memory/rejected-ideas.md)) — existing OS notification
flash/vibrate features only signal that something arrived, not the content itself.

**Why.** Genuinely open accessibility gap, not covered by any existing prior art evaluated so far.

### D12. Community broadcast (Phase 6)

**What.** One-to-many SMS for alerts/bulletins (evacuation routes, supply points, weather), reusing
the existing chunking/crypto with a shared group key.

**How.** Not started; depends on D6/D7.

**Why.** Directly serves the "people in need" framing with no new transport work — reuses everything
already built.

---

## §E PROJECT EVOLUTION

### E1. SIM-bank gateway economics (part of Phase 3)

The relay server's own SMS sending can run on a paid API (Twilio-style) or a small bank of
prepaid-SIM Android phones.
A pure ops decision, no app-side work either way, but it materially
affects per-message cost at the population this project targets.
Needs a decision, not effort, and
isn't blocking anything before Phase 3.

### E2. Push-notification transport (Phase 7) — optional, opt-in, deliberately last

A third transport mode (alongside Web and SMS) for restrictive/firewalled networks that block general
internet but can't block Apple/Google's push infrastructure.
Two real costs make this a decision, not
just a task: **privacy** (Apple/Google can see, and governments have compelled disclosure of,
push-token metadata — who's talking to whom, when; the one mode where a third party sits inside
airwire's trust model, must be clearly labeled as lower-privacy, never a silent fallback) and
**platform risk** (using FCM as a generic message channel is also how real Android malware operates —
needs a transparent, disclosed implementation to avoid tripping app-store malware heuristics).
Not
"serverless" despite appearances — needs the Phase 2 relay server's privileged credentials regardless.

### E3. Decide whether `core/`'s historical-narrative docstrings should move to `CHANGELOG.md`

Found during A3's coding-guidelines review.
Several `core/sources/*.py` module docstrings narrate
what changed and when, inline — `markov.py`'s "Known limitations" section has four "Resolved: X used
to Y, now Z" bullets; `chunking.py`'s "Scope and open questions" section similarly narrates the
ack-nonce-derivation attempt-and-revert inline, even though that same history now also lives in
[`memory/rejected-ideas.md`](memory/rejected-ideas.md).
This is a genuine, pervasive, clearly
*deliberate* style predating this session's `memory/coding-guidelines.md`, which says "Comments
describe the code, never how it came to be...
History goes in `CHANGELOG.md`, reasoning in
`memory/`.
" Not rewritten silently as part of A3 — the pattern is core/'s established documentation
voice across its most-explained modules, and unwinding it is a real editing task, not a mechanical
fix.
Needs a decision: (a) keep it as a working, intentional exception — arguably valuable context
sitting physically next to the code it explains, hasn't caused a real problem — and update
`memory/coding-guidelines.md`'s "Everywhere" rule to say so explicitly; or (b) actually migrate this
narrative out into `CHANGELOG.md`/`memory/`'s proper homes across every affected module.
