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

### A3. Full repo review for the new documentation layout's coding standards and lint alignment

**What.** Go through `core/`, `client/`, and `web-demo/` and check each against
[`memory/coding-guidelines.md`](memory/coding-guidelines.md) as actually written — not just "does the
configured linter pass," but the bullets that have no linter behind them yet (named constants,
imports at the top, no backward-compatibility shims, doc-comment placement).

**How.** One pass per sub-project, cross-referencing the relevant `coding-guidelines.md` section;
file a follow-up item here for anything that needs a real code change rather than fixing silently
along the way.

**Why.** This documentation layout is new, and its coding-guidelines content was written from what
the *tooling* already enforces (flake8/black/mypy, flutter_lints, TypeScript strictness) — it hasn't
yet been checked against what the *code itself* actually does everywhere. Related to A1/A2, but
broader: those two are pure tooling gaps, this is "does the code match the rules now that they're
written down."

### A5. Web-demo unit test coverage gap: `arithmetic.ts`, `synthesis.ts`, `textures.ts`, `prng.ts`, `png.ts`

**What.** Only `markov.ts` has a dedicated spec file (`markov.spec.ts`); the other five modules under
`web-demo/src/app/core/` have no unit tests at all — only `app.component.spec.ts`'s
component-level smoke test exercises them indirectly.

**How.** Follow `markov.spec.ts`'s pattern (round-trip, determinism, seed-differs-across-runs) for
each module; `arithmetic.ts` and `synthesis.ts` are the highest-value targets, since they're the
shared coder and the image disguise's core logic, respectively.

**Why.** A regression in any of these five currently surfaces only as a component-level test
failure (if at all) or a manual browser check — there's no unit-level signal pointing at which
module actually broke.

### A6. Root `README.md`'s License section is an unresolved placeholder

**What.** `README.md`'s License section literally reads `TODO!` — no license has ever been chosen
for this repository.

**How.** Pick a license (or explicitly decide "proprietary, no license file") and replace the
placeholder.

**Why.** Visible, unresolved placeholder in the first document anyone reads — predates this
session's docs work but was not this session's to resolve unilaterally (a real decision, not a
docs-migration mechanical fix).

### A7. Audit `client/`'s READMEs and any other docs still worth migrating into `memory/`

**What.** `client/app/README.md` is still the unedited Flutter-CLI boilerplate ("A new Flutter
project... starting point"), and `client/medium/` has no `README.md` at all. Neither was in scope
for this session's `docs/` → `memory/` migration (that covered root-level product docs only), but
both are real gaps in the same spirit.

**How.** Give `client/app/README.md` real content (or replace it with a pointer to the root
`README.md`/`AGENTS.md`, matching how `core/README.md` and `web-demo/README.md` already work);
decide whether `client/medium/` needs its own `README.md` or is adequately covered by
[`memory/medium.md`](memory/medium.md). More generally: treat this as a standing reminder — any new
doc that describes *how something currently works* belongs in `memory/`, not scattered in a new
`docs/*.md` file, per this session's migration precedent.

**Why.** A generic, unedited boilerplate README next to two other sub-projects with real,
maintained ones is exactly the kind of inconsistency a stranger arriving cold would trip over.

### A8. Migrate `docs/superpowers/`'s design specs and implementation plans into `memory/`

**What.** Fold the content of `docs/superpowers/specs/*.md` and `docs/superpowers/plans/*.md` (10
files) into `memory/`, rather than leaving them in a separate, un-migrated archive. This session
deliberately left `docs/superpowers/` untouched (treated as a skill-owned archive, referenced not
absorbed) — that call is reversed: it belongs in `memory/` like everything else that describes how
things work or are planned to work.

**How.** Same three-way split this session already used for `docs/design-decisions.md` and
`docs/roadmap.md`: still-current reasoning into the relevant `memory/*.md` file, "what shipped and
when" into `CHANGELOG.md`, not-yet-executed work into `TODO.md`. Concretely, one pass per file:

- The design specs for already-shipped features (`2026-09-01-okru-prototype-design.md`,
  `2026-09-08-markov-boundary-and-filler-design.md`, `2026-09-08-markov-seed-broadening-design.md`,
  and their matching `plans/*.md`) are largely superseded by what's already in
  [`memory/wire-protocol.md`](memory/wire-protocol.md), [`memory/medium.md`](memory/medium.md), and
  `CHANGELOG.md` — check each for anything not yet captured before retiring the spec/plan itself.
- `2026-08-27-messaging-protocol-design.md` (still draft, describes the not-yet-implemented
  directional-key/rotation crypto scheme) belongs with
  [`memory/handshake.md`](memory/handshake.md)'s "Target spec" section, which already summarizes it
  but doesn't yet fully absorb it.
- The three unexecuted Dart plans (`2026-08-30-handshake-dart.md`, `2026-08-30-protocol-core-dart.md`,
  `2026-08-31-key-rotation-dart.md`) stay pointed at from `TODO.md` D6 until `client/`'s protocol
  port is actually built — at that point they either execute (and their content moves to a new
  `memory/dart-protocol.md`, per `memory/README.md`'s growth table) or get retired into
  `CHANGELOG.md`/`rejected-ideas.md`.
- Decide, in the same pass, where **future** specs/plans from the superpowers
  brainstorming/writing-plans skill workflow should land — those skills are hardcoded to write to
  `docs/superpowers/specs|plans/YYYY-MM-DD-*.md`, so this migration is not a one-time cleanup unless
  that destination is also addressed (e.g. a finishing-a-feature step that folds the spec/plan into
  `memory/`/`CHANGELOG.md` and deletes the original, every time).

**Why.** `docs/superpowers/` content genuinely describes current or planned system behavior — the
exact thing `memory/` exists for — and leaving it in a second, un-indexed location is the same
duplication-of-truth problem this session's migration was meant to eliminate everywhere else.

---

## §B UPON \<EVENT\>

Nothing batched here yet — no expensive, infrequent event has been identified for this project.

---

## §C BLOCKED — waiting on time or data

Nothing here — every open item below can be advanced by effort whenever it's picked up.

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
no caller in the data path. Flagged rather than attempted immediately specifically because the
analogous ack-nonce work needed two rejected attempts before finding a safe derivation — this deserves
its own scrutiny, not a quick copy of that reasoning.

### D3. Image texture synthesis visual quality on large-scale-structure textures

**What.** Voronoi and reaction-diffusion textures are still visibly more fragmented than their source
after seed rows measurably improved them; widening the blend-cost window did not help further (see
`memory/rejected-ideas.md`). Two untried directions remain: shrinking gap rows relative to seed rows,
or trying Wu & Wang's own irregular scatter-then-fill-gaps layout after all.

**How.** Either is a change to `core/sources/synthesis.py`'s row-placement logic; measure with the
same independent seam-MSE method the `OVERLAP` experiment used, against the same fixed input, so the
result is comparable to that entry.

**Why.** Locally-stationary textures (`value_noise`) are already fine; this only affects two of four
flavors, and round-trip correctness doesn't depend on visual quality — cosmetic, not blocking. See
also D13 for a more fundamental alternative to tuning this one's parameters.

### D4. Cross-implementation test vectors

**What.** Use `core/`'s Python implementation as the source of test vectors: encrypt with Python,
assert a future client-side implementation decrypts it correctly, and vice versa.

**How.** Not started. Depends on a client-side protocol implementation existing to test against —
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
instances for the dev loop; two prepaid SIMs for carrier-reality validation before shipping. Three
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
carried over it is the part Silence never had. See also E1 for the one genuine open decision in this
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

**How.** Not started. Distinct from Morse *input*, which Gboard/Switch Control already provide for
free (see [`memory/rejected-ideas.md`](memory/rejected-ideas.md)) — existing OS notification
flash/vibrate features only signal that something arrived, not the content itself.

**Why.** Genuinely open accessibility gap, not covered by any existing prior art evaluated so far.

### D11. Reflow markdown to one-sentence-per-line and full `markdownlint` compliance, then stop excluding `docs/superpowers/` and `docs/research-proposal.md` from CI

**What.** Two related gaps, both currently carved out rather than fixed: (1)
`python memory/scripts/verify_memory.py --strict` reports 296 "two sentences on one line" warnings
across pre-existing docs (`core/README.md`, `web-demo/README.md`, `docs/superpowers/**`,
`docs/research-proposal.md`) and this session's own new files (`AGENTS.md`, `CHANGELOG.md`,
`TODO.md`, `memory/*.md`); (2) `docs/superpowers/**` and `docs/research-proposal.md` fail full
`markdownlint-cli2` outright (MD032 blanks-around-lists, MD040 fenced-code-language, MD001
heading-increment, MD060 table style) and are excluded from `.github/workflows/lint.yaml`'s
markdown-lint step and `.markdownlintignore` rather than fixed.

**How.** Reflow each file's prose to one sentence per line (see
[`memory/dos-and-donts.md`](memory/dos-and-donts.md)'s Documentation section for why) and fix the
markdownlint findings, then remove the `docs/superpowers`/`docs/research-proposal.md` exclusions
from both `.markdownlintignore` and `lint.yaml`'s `globs`, and flip the verify step back to
`python memory/scripts/verify_memory.py --strict`, all in the same commit as the last file that
needed it.

**Why.** Both rules exist for real reasons (a changed sentence producing a one-line diff; consistent
rendering), but reflowing/fixing ~400 findings by hand across a frozen historical archive and a
separate research track risks introducing errors faster than it fixes style, and doesn't belong in
the same pass as reorganizing where the docs live. The exclusions are deliberate and documented in
`.markdownlintignore`'s own comment, not an oversight.

### D12. Community broadcast (Phase 6)

**What.** One-to-many SMS for alerts/bulletins (evacuation routes, supply points, weather), reusing
the existing chunking/crypto with a shared group key.

**How.** Not started; depends on D6/D7.

**Why.** Directly serves the "people in need" framing with no new transport work — reuses everything
already built.

### D13. Explore whole-canvas-aware image generation, for visual uniformity

**What.** Confirmed by direct visual inspection (obfuscated the same message under all four texture
flavors in a live browser session, then upscaled the actual PNG pixel data 6× with nearest-neighbor
so patch edges stay crisp): the image disguise's blocky, "concatenated from little squares" look is
the literal designed granularity of the technique — a fixed grid of 8×8-pixel patches
(`DEFAULT_PATCH_SIZE`), 16 patches wide (`DEFAULT_CANVAS_WIDTH`), alternating untouched seed rows
with synthesized gap rows chosen one patch at a time. D3's two untried directions (shrink gap rows,
try Wu & Wang's irregular scatter) are incremental tuning of that same grid. This item is a more
fundamental alternative: explore generating the *entire* canvas from the whole payload at once,
so the result reads as one uniform image rather than a patchwork of independently-chosen tiles.

**How.** Not scoped yet — an open research direction, not a concrete implementation plan. Starting
points worth considering: whether the arithmetic-coding walk can be restructured to choose a whole
row's (or the whole canvas's) patch assignment jointly instead of greedily one patch at a time,
while remaining exactly invertible; whether a different reversible-embedding technique entirely
(not patch-library synthesis) could avoid the seed/gap-row grid altogether; or a cosmetic
post-blending pass over the existing patch-based output that never touches which patch was chosen
(anything that does must stay bit-exact and invertible on decode, per
[`memory/wire-protocol.md`](memory/wire-protocol.md)'s arithmetic-coding contract).

**Why.** The current approach's regularity is a known, deliberate simplification (see
`memory/rejected-ideas.md`) that trades visual uniformity for implementation simplicity. D3's tuning
ideas address two of four flavors incrementally; this asks whether the underlying grid constraint
itself can be lifted, which would be a bigger win if it turns out feasible at all.

---

## §E PROJECT EVOLUTION

### E1. SIM-bank gateway economics (part of Phase 3)

The relay server's own SMS sending can run on a paid API (Twilio-style) or a small bank of
prepaid-SIM Android phones. A pure ops decision, no app-side work either way, but it materially
affects per-message cost at the population this project targets. Needs a decision, not effort, and
isn't blocking anything before Phase 3.

### E2. Push-notification transport (Phase 7) — optional, opt-in, deliberately last

A third transport mode (alongside Web and SMS) for restrictive/firewalled networks that block general
internet but can't block Apple/Google's push infrastructure. Two real costs make this a decision, not
just a task: **privacy** (Apple/Google can see, and governments have compelled disclosure of,
push-token metadata — who's talking to whom, when; the one mode where a third party sits inside
airwire's trust model, must be clearly labeled as lower-privacy, never a silent fallback) and
**platform risk** (using FCM as a generic message channel is also how real Android malware operates —
needs a transparent, disclosed implementation to avoid tripping app-store malware heuristics). Not
"serverless" despite appearances — needs the Phase 2 relay server's privileged credentials regardless.
