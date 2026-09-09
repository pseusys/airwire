# Rejected ideas — do not re-propose without new evidence

*keywords:* rejected, tried, did not work, negative result, reopen, settled, nonce derivation, OVERLAP, constriction, Telegram, Yandex Messenger

Decisions to NOT do something, recorded so they are not rediscovered and re-argued from scratch.
Open questions live in [`../TODO.md`](../TODO.md); this file is for settled ones.

Each entry states what was proposed, what was measured, and what new evidence would be needed to reopen it.
"Rejected" here means *tried and did not pay*, or *rejected by the owner on design grounds* — not "never tried".

## Derive the header/ack AEAD nonce instead of transmitting it (2026-09-08)

*keywords: derive_nonce, hyperchunk_id, HyperchunkHeader, HyperchunkAck, _ack_nonce, selective retransmission*

**Idea.**
`sources/chunking.py`'s header and ack each embed a fresh random 24-byte nonce. Since every
hyperchunk carries a stable `hyperchunk_id`, derive each message's nonce from `(hyperchunk_id,
"header"|"ack")` via BLAKE2b instead — 24 bytes off a 93-byte header (~26% smaller) and a much
larger fraction off a 44-byte ack, for free (AEAD only needs nonce uniqueness, not randomness).

**What was tried.**
The header case is impossible by construction: `hyperchunk_id` is a field *inside* the header, so a
receiver can't learn it without first decrypting the header — deriving the header's own decryption
nonce from it is circular. Not attempted; the header's nonce stays random and embedded.
The ack case has no such circularity (the decoder already knows which hyperchunk it's waiting for),
so it was actually built: folding the boolean `success` into the derivation
(`derive_key(hyperchunk_id, success)`) gave every distinct ack plaintext its own nonce, with decoding
recovering `success` by trying both possible derivations and taking whichever authenticated. Measured:
ack size dropped from 44 to 20 bytes (54.5%). Two alternatives were also explored and rejected before
landing on this: a transmitted random salt (any nonzero size is strictly worse on the metric this
decision is about, and a 2-byte salt — the size actually proposed — reaches ~1% collision risk after
just 36 acks under one key); and a never-transmitted `(hyperchunk_id, attempt_number)` counter (the
receiver has no signal to reconstruct the sender's local retry count, since `send_hyperchunk` resends
byte-identical cached bytes with no attempt number in them).

**Why rejected.**
It worked, but the trade-off was not worth it: the "derive from content, try all candidates on
decode" trick only works while the ack's content stays small and enumerable. The very next
overhead-reduction item on the list, selective retransmission, wants a failure ack to carry *which
chunk indices are missing* — an open-ended list, not a 2-way choice, and not practically enumerable
to trial-decrypt against. Shipping something already known to need ripping out for the next planned
change wasn't worth it; the ack reverted to a plain random embedded nonce (44 bytes, unchanged from
before this was tried). `sources/crypto.py`'s `derive_nonce` helper stayed in the codebase despite
its one caller being reverted — a generically useful primitive, not dead code.

**What would reopen it.**
Selective retransmission being decided against for good (unlikely, it's still an open TODO item), or
a different ack schema that keeps the derivable content small and enumerable even with a
missing-chunk list (e.g. a fixed-size bitmask instead of an open-ended list, if the maximum chunk
count is bounded tightly enough).

## Widen the image texture blend-cost comparison window (`OVERLAP` > 1) (2026-09-08)

*keywords: OVERLAP, _candidate_weights, seam MSE, Voronoi, reaction-diffusion, blend-cost*

**Idea.**
The patch-based image texture synthesis (`sources/synthesis.py`) only compares a single pixel-wide
edge between a candidate patch and its already-placed neighbor when scoring how well it blends. Wu &
Wang's own prior art (and Efros & Freeman's image-quilting overlap-region cost) both compare a wider
region. Widening the comparison — an `OVERLAP` parameter over the first/last `OVERLAP` rows or
columns instead of just row/column 0 — looked like the natural next fix for the fragmentation seen on
large-scale-structure textures (Voronoi, reaction-diffusion).

**What was tried.**
Implemented as described, measured against an independent metric (not the cost function's own
output): actual mean squared color difference at the visible seam between horizontally-adjacent
gap-row patches in the rendered canvas, fixed non-random input for a fair comparison across settings.

| `OVERLAP` | Voronoi seam MSE | Reaction-diffusion seam MSE |
| --- | --- | --- |
| 1 (baseline) | 4721.9 | 8032.3 |
| 2 | 4630.1 | 8386.6 |
| 3 | 4767.9 | 8670.8 |
| 4 | 4640.5 | 8722.8 |
| 5 | 4627.2 | 9069.6 |
| 6 | 4704.2 | 9095.3 |

**Why rejected.**
It did not hold up: reaction-diffusion gets monotonically *worse* as the window widens, and Voronoi
shows no clear trend at all (noise-level fluctuation around the baseline). Reverted;
`_candidate_weights` is back to the single-row comparison. Believed cause, not confirmed: Efros &
Freeman's overlap cost works because their algorithm is a hard minimizer (always places the single
best match, then cuts a seam). This module's coder turns costs into arithmetic-coder *weights* and
picks a randomly-selected-but-weighted candidate, by design (picking only the best match would carry
zero bits of information) — nothing established that widening the window reshapes the resulting
weight distribution in the direction that helps a weighted-random pick the way it reliably helps a
strict minimizer.

**What would reopen it.**
Directly measuring whether the weight distribution gets flatter or sharper as the window widens
(not done — this would confirm or kill the hypothesized mechanism above, independent of re-running
the seam-MSE table). Absent that, re-trying the same `OVERLAP` sweep is not expected to come out
differently.

## Build the Markov text disguise on `constriction` instead of a hand-rolled coder (2026-09-08)

*keywords: constriction, RangeEncoder, RangeDecoder, entropy coding, self-terminating decode*

**Idea.**
[`constriction`](https://pypi.org/project/constriction/) (MIT/Apache/BSL-1.0, prebuilt wheels,
documentation promising "exactly invertible fixed-point arithmetic") looked like the obvious
general-purpose entropy-coding library to build the Markov-chain disguise on, instead of writing an
arithmetic coder from scratch.

**What was tried.**
Built and tested hands-on before writing any project code against it. `constriction`'s public API is
shaped for compressing/decompressing an *already-known* number of symbols
(`decoder.decode(model, 9)` — the caller states the count up front). This module's actual question is
the reverse: how many words does it take to represent this many bytes, with the symbol count being
exactly what's unknown going in. Every way tried to coerce it into answering that — padding the input
and hoping the decoder tolerates reading past the real data, tracking `RangeEncoder.get_compressed()`'s
growth to guess when "enough" had been decoded — failed empirically: its `RangeDecoder` doesn't error
on the first out-of-bounds read, but decoding enough further symbols eventually corrupts its internal
state and raises an unrecoverable assertion. Confirmed directly with padding sizes from a few hundred
bytes to many kilobytes, both zero-filled and randomly-filled.

**Why rejected.**
It cannot be evaluated further with this library: its own `maybe_exhausted()` docs suggest appending
an explicit end-of-stream sentinel symbol, which fits compressing a message whose symbol content is
already fully known upfront — not this module's shape, where the symbols (words) are themselves the
output being discovered step by step. A small binary arithmetic coder was written from scratch
instead (`sources/arithmetic.py`, adapted from Hernan Moraldo's reference design), tracking "how many
source bits remain" as an explicit owned value rather than asking an external library to report it.

**What would reopen it.**
A `constriction` release exposing an open-ended, self-terminating decode API (explicitly tracking a
remaining-bits budget the way this module's own coder does) rather than a fixed-symbol-count one.

## Telegram as a medium (2026-08-30)

*keywords: Telegram, MTProto, Bot API, userbot, selfbot, Terms of Service*

**Idea.**
Telegram wasn't on the original candidate list but surfaced as a strong technical fit during medium
research: broadest global reach and best-documented API of any platform evaluated, plus a path
(MTProto as a personal account, a "userbot") to genuine real-user-profile appearance, matching the
"acting as a real user" preference the other candidates were being judged against.

**What was tried.**
Researched both available paths. The Bot API (open registration via @BotFather, no entity
requirement) gives only a labeled-bot identity — safe, but visibly not a person, undermining the
disguise. MTProto-as-a-personal-account gets the real-profile appearance, but automating a real
personal account this way is explicitly against Telegram's Terms of Service and actively enforced,
including documented bans that follow the phone number to a freshly registered replacement account.

**Why rejected.**
Rejected by the owner on design grounds, not a technical blocker: Telegram already offers reasonably
good opt-in end-to-end privacy of its own (Secret Chats), so there's less value in building this
project's disguise/encryption layer on top of it specifically. The platforms where that layer adds
the most (MAX, VK, Odnoklassniki — none offer any E2E option at all) are a better use of effort. This
also conveniently avoids the one candidate whose real-profile path carried real account-ban risk.

**What would reopen it.**
A specific need for Telegram's reach or attachment richness that outweighs the "already has E2E, so
this layer adds less" reasoning above — a value judgment, not something new measurement alone would
overturn.

## Yandex Messenger as a medium (2026-08-30)

*keywords: Yandex Messenger, Yandex 360, Bot API, organization-only*

**Idea.**
Yandex Messenger's consumer app supports personal, non-business 1:1 and group chat (up to 3000
people), making it a plausible medium candidate alongside MAX, VKontakte, and Odnoklassniki.

**What was tried.**
Researched the only documented programmatic surface: the Bot API, confined to Yandex 360 Business
organizations. Confirmed directly against Yandex's own docs: a bot can only message members of its
own organization, not an arbitrary external user
(`Бот не может отправлять личные сообщения пользователям за пределами своей организации`). No
OAuth-delegation equivalent to Odnoklassniki's `graph.user.messages` was found for personal-mode
accounts.

**Why rejected.**
It cannot satisfy the medium contract (`send`/`receive` between arbitrary users) with current
tooling: this is a harder blocker than MAX's developer-entity gate or VK's community-only
restriction — not about who's allowed to register, but that the API structurally cannot reach an
arbitrary external user at all. Registering a shared organization and adding every user as a fake
"employee" is a theoretical workaround, judged an awkward, likely ToS-straining hack, not a real fit.

**What would reopen it.**
A personal-account API surfacing that this research pass didn't find, or Yandex extending Bot API
messaging beyond one organization's own members.
