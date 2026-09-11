# Rejected ideas — do not re-propose without new evidence

*keywords:* rejected, tried, did not work, negative result, reopen, settled, nonce derivation, OVERLAP, constriction, Telegram, Yandex Messenger

Decisions to NOT do something, recorded so they are not rediscovered and re-argued from scratch.
Open questions live in [`../TODO.md`](../TODO.md); this file is for settled ones.

Each entry states what was proposed, what was measured, and what new evidence would be needed to reopen it.
"Rejected" here means *tried and did not pay*, or *rejected by the owner on design grounds* — not "never tried".

## Reconstruct Markov sentence boundaries by scanning for periods (2026-09-08)

*keywords: `___END__`, period, sentence boundary, markov_eng.json, markov_rus.json, newline*

**Idea.**
The Markov text disguise renders sentence boundaries as a literal `___END__` token — an obvious
tell.
Since real sentences already end in a period most of the time, drop the explicit token
entirely and reinsert it at decode time by scanning for periods instead.

**What was tried.**
Checked directly against both frozen models before writing any code.
English: 33 Markov states end
in a real period (`Mr.`, `Mrs.`, `Dr.`, `Mt.`, `Ms.`) where `___END__` is never offered as a
continuation — always followed by a real word, never a sentence break; one state where `___END__`
*is* offered ends in `:`, not a period.
Russian: 195 states end in a literal period with `___END__`
not offered at all (dialogue attribution mid-sentence, e.g. `сказала мама.` continuing into more
text), plus 13 END-reachable states ending in `»`/`:`/`‽`.

**Why rejected.**
A period is neither necessary nor sufficient for "this is where `___END__` was chosen," in either
language's actual training data.
Guessing a boundary at an abbreviation would desync the decoder's
Markov walk from a state the encoder was never in — a hard decode failure, not a cosmetic
imperfection.
Replaced with rendering `___END__` as a plain `\n` instead (safe because no token in
either frozen model contains an embedded newline, checked structurally via how the training corpus
and tokenizer both work, not just empirically) — see `memory/wire-protocol.md`.

**What would reopen it.**
A retrained model verified to have zero period-ending non-`___END__`-eligible states in both
languages — unlikely to ever hold given how abbreviations work in natural language, and not worth
re-checking without a specific reason to believe the corpus changed fundamentally.

## Seed-derived rotation/offset, and XOR'd ciphertext, for gating Markov real-content decoding (2026-09-08)

*keywords: candidate_ranges, permutation, OVERLAP-style rotation, XOR keystream, seed-broadening*

**Idea.**
Two alternatives considered, alongside the chosen design, for making the Markov disguise's seed
gate real-content decoding (not just the cosmetic filler tail): (B) a seed-derived rotation/offset
of each state's candidate order, instead of a full shuffle; (C) XOR the input ciphertext bits with
a seed-derived keystream before arithmetic-coding them, instead of touching candidate order at all.

**What was tried.**
Neither was built — both rejected on design grounds before implementation, in favor of the
seed-derived full-permutation approach that shipped (see `memory/wire-protocol.md`).

**Why rejected.**
(B) is a much smaller permutation space per state than a full shuffle, and no clearer to reason
about — strictly dominated by the chosen approach, no scenario where it would be preferable.
(C) The input is already AEAD ciphertext, indistinguishable from random — XOR-ing it again adds no
real defense and just moves the seed-dependency into the wrong layer, conflating the disguise
encoding (which should only reshape bytes into atoms, never touch their meaning) with the crypto
layer that already owns this property.
The chosen approach keeps the seed-dependency a property of
the *encoding* itself, matching how the image disguise's seed is a property of its texture
generator, not of the plaintext.

**What would reopen it.**
Neither approach solves a problem the chosen one doesn't — nothing currently would revisit either
without a fundamentally different requirement (e.g. a candidate-order permutation being ruled out
for the image disguise for a reason that also applies to the Markov case).

## Replay-detection on the target-spec certificate's transmitted nonce (2026-08-27)

*keywords: certificate, bootstrap_key, header_nonce, replay, messaging-protocol-design*

**Idea.**
In the not-yet-implemented target protocol spec (see `memory/handshake.md`'s "Target spec"
section), the handshake certificate's nonce can't be counter-derived the way ordinary data
messages' nonces are, so it's transmitted once per certificate.
Rejecting a *repeated* nonce value
looked like a cheap extra safety net against replay.

**What was tried.**
Not built — rejected on design grounds during the spec's own design phase, before implementation.

**Why rejected.**
It doesn't add real protection: an adversary capable of forging a malicious certificate at all can
just generate a fresh keypair and a fresh nonce rather than replaying an old one, and
`bootstrap_key` being derivable by anyone who knows both parties' IDs means nothing stops that
regardless.
A repeated-nonce check would only ever catch an adversary who had no reason to vary
the nonce in the first place.

**What would reopen it.**
A scenario where forging a certificate is possible but generating a fresh nonce specifically is
not — no such scenario is known.

## Derive the header/ack AEAD nonce instead of transmitting it (2026-09-08)

*keywords: derive_nonce, hyperchunk_id, HyperchunkHeader, HyperchunkAck, _ack_nonce, selective retransmission*

**Idea.**
`sources/chunking.py`'s header and ack each embed a fresh random 24-byte nonce.
Since every
hyperchunk carries a stable `hyperchunk_id`, derive each message's nonce from `(hyperchunk_id,
"header"|"ack")` via BLAKE2b instead — 24 bytes off a 93-byte header (~26% smaller) and a much
larger fraction off a 44-byte ack, for free (AEAD only needs nonce uniqueness, not randomness).

**What was tried.**
The header case is impossible by construction: `hyperchunk_id` is a field *inside* the header, so a
receiver can't learn it without first decrypting the header — deriving the header's own decryption
nonce from it is circular.
Not attempted; the header's nonce stays random and embedded.
The ack case has no such circularity (the decoder already knows which hyperchunk it's waiting for),
so it was actually built: folding the boolean `success` into the derivation
(`derive_key(hyperchunk_id, success)`) gave every distinct ack plaintext its own nonce, with decoding
recovering `success` by trying both possible derivations and taking whichever authenticated.
Measured:
ack size dropped from 44 to 20 bytes (54.5%).
Two alternatives were also explored and rejected before
landing on this: a transmitted random salt (any nonzero size is strictly worse on the metric this
decision is about, and a 2-byte salt — the size actually proposed — reaches ~1% collision risk after
just 36 acks under one key); and a never-transmitted `(hyperchunk_id, attempt_number)` counter (the
receiver has no signal to reconstruct the sender's local retry count, since `send_hyperchunk` resends
byte-identical cached bytes with no attempt number in them).

**Why rejected.**
It worked, but the trade-off was not worth it: the "derive from content, try all candidates on
decode" trick only works while the ack's content stays small and enumerable.
The very next
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

## Graph-cut seam-finding and Poisson blending for image patch borders (2026-09-10)

*keywords: graph cut, Poisson image editing, Kwatra, GraphCut Textures, seam DP, SEAM_OVERLAP*

**Idea.**
To soften the hard edges between adjacent image-disguise patches, use the literature's
actual state of the art for this exact problem: find a minimum-cost irregular seam through the
overlap between two adjacent patches (Kwatra et al., "GraphCut Textures"), then gradient-domain
blend along it (Pérez, Gangnet, Blake, "Poisson Image Editing") -- both cited as this project's own
prior art already, via Efros & Freeman's image quilting.

**What was tried.**
Not implemented -- rejected on design grounds during scoping, before writing
any seam/Poisson code.
Re-measuring the widened-dedup minimum-distance guarantee specifically over
each candidate's *core* (patch content minus a border reserved for blending) showed the safety
margin is already thin for `voronoi` (~2.3 RMS) and `reaction_diffusion` (~1.6 RMS) at a 1-pixel
border, and collapses entirely by 2 pixels (`reaction_diffusion`'s core margin drops to ~0.2 RMS,
effectively zero) -- see the 2026-09-10 CHANGELOG.md entry.
A 1-pixel overlap band leaves a
seam-finding DP almost nothing to route around (only one pixel of "give" on each side of a
boundary), and gradient blending needs real width to actually blend a gradient across.

**Why rejected.**
Both techniques' real advantage over a plain linear blend comes specifically
from having a wide-enough overlap region to work with (8-16px is typical in the literature) --
something the safety margins here don't allow for two of the three flavors this applies to.
Building DP seam-finding and a gradient-domain solver for a border too thin to benefit from either
would add substantial implementation complexity for no expected improvement over simple feathering
at this scale.
Plain linear feathering was implemented instead (`_feather_canvas`), confirmed via
an isolated, apples-to-apples visual comparison to meaningfully soften `value_noise`/`voronoi`'s
edges; `reaction_diffusion`'s change is negligible, consistent with its much tighter margin forcing
an especially conservative blend.

**What would reopen it.**
A way to widen the core-region safety margin for `voronoi`/`reaction_diffusion`
specifically (e.g. a stricter, per-flavor `MIN_CANDIDATE_DISTANCE_SQ`) enough to support a wider
border -- untried, since it would shrink those flavors' already-reduced candidate libraries
further, a trade-off nobody has evaluated yet.

## Overlapping candidate patches for the scattered image layout (2026-09-09)

*keywords: DEFAULT_CANDIDATE_STRIDE, PatchLibrary stride, overlapping patches, Wu Wang*

**Idea.**
Wu & Wang's technique draws gap-fill candidates from overlapping, pixel-shifted crops of
the source texture, not just a small non-overlapping tile grid -- a much finer-grained palette
that should, in principle, let a gap cell match smoothly-varying content more closely than picking
from ~256 fixed tiles.
Implemented as `PatchLibrary`'s `stride` parameter (`stride=1` reproduces
the paper's "every possible offset" reading) alongside the same day's scattered-anchor layout
redesign.

**What was tried.**
Measured directly: build time, encode/decode wall-clock, the "guide fidelity"
metric (mean squared difference between what was actually placed and the texture's true content at
that position), and a generalized seam-MSE, at `stride` in `{1, 2, 4, 8}` (`8` = `patch_size`, the
original non-overlapping palette), fixed non-random input, three flavors.

| Flavor | stride | library size | encode (s) | guide fidelity |
| --- | --- | --- | --- | --- |
| `value_noise` | 1 | 16384 | 12.285 | 4513.7 |
| `value_noise` | 2 | 4096 | 2.205 | 4173.0 |
| `value_noise` | 4 | 1024 | 0.485 | 3998.5 (best) |
| `value_noise` | 8 | 256 | 0.139 | 4210.7 |
| `voronoi` | 1 | 16383 | 11.671 | 3893.9 (best) |
| `voronoi` | 8 | 256 | 0.171 | 4208.7 |
| `reaction_diffusion` | 1 | 6846 | 3.280 | 6516.6 |
| `reaction_diffusion` | 8 | 148 | 0.109 | 4720.6 (best) |

**Why rejected.**
No consistent winner: `voronoi` did best at `stride=1`, `reaction_diffusion` did
best at `stride=8` (the original, no-overlap palette), and `value_noise` did best at `stride=4` --
three different flavors, three different optima, none dramatically better than the others (all
within a fairly narrow band per flavor).
Direct visual comparison confirmed the numbers weren't
hiding a bigger effect either: `value_noise` at `stride=2` and `stride=8` looked comparably good,
both with the row-banding gone.
Meanwhile cost scales sharply with a smaller stride -- `stride=1`
costs roughly 90x `stride=8`'s wall-clock time, clearly impractical for real messages.
Same root
cause as the `OVERLAP` entry below: the arithmetic coder picks a *weighted-random* candidate, not
the best match, so a richer pool doesn't reliably help the way it would a strict minimizer -- a
bigger, more diverse candidate pool changes the weight distribution's shape in ways that don't
straightforwardly improve the realized (selected) outcome.
`DEFAULT_CANDIDATE_STRIDE` shipped as
`DEFAULT_PATCH_SIZE` (no overlap); the `stride` machinery and its vectorized cost computation
stayed in `PatchLibrary` regardless -- a generically useful, already-tested capability, not dead
code, the same reasoning `sources/crypto.py`'s `derive_nonce` helper was kept under.
The scattered
anchor placement itself (not the overlapping candidates) is what actually removed the row-banding
artifact this work started from -- see the 2026-09-09 CHANGELOG.md entry.

**What would reopen it.**
A non-linear cost-to-weight mapping that preserves a stronger preference
for low-cost candidates even as the pool grows (untried, and would need its own scrutiny against
the arithmetic coder's exact-invertibility requirement), or a per-flavor stride choice if a later
flavor is added where the trade-off clearly favors overlap -- nothing currently does.

## Widen the image texture blend-cost comparison window (`OVERLAP` > 1) (2026-09-08)

*keywords: OVERLAP, _candidate_weights, seam MSE, Voronoi, reaction-diffusion, blend-cost*

**Idea.**
The patch-based image texture synthesis (`sources/synthesis.py`) only compares a single pixel-wide
edge between a candidate patch and its already-placed neighbor when scoring how well it blends.
Wu &
Wang's own prior art (and Efros & Freeman's image-quilting overlap-region cost) both compare a wider
region.
Widening the comparison — an `OVERLAP` parameter over the first/last `OVERLAP` rows or
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
shows no clear trend at all (noise-level fluctuation around the baseline).
Reverted;
`_candidate_weights` is back to the single-row comparison.
Believed cause, not confirmed: Efros &
Freeman's overlap cost works because their algorithm is a hard minimizer (always places the single
best match, then cuts a seam).
This module's coder turns costs into arithmetic-coder *weights* and
picks a randomly-selected-but-weighted candidate, by design (picking only the best match would carry
zero bits of information) — nothing established that widening the window reshapes the resulting
weight distribution in the direction that helps a weighted-random pick the way it reliably helps a
strict minimizer.

**What would reopen it.**
Directly measuring whether the weight distribution gets flatter or sharper as the window widens
(not done — this would confirm or kill the hypothesized mechanism above, independent of re-running
the seam-MSE table).
Absent that, re-trying the same `OVERLAP` sweep is not expected to come out
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
(`decoder.decode(model, 9)` — the caller states the count up front).
This module's actual question is
the reverse: how many words does it take to represent this many bytes, with the symbol count being
exactly what's unknown going in.
Every way tried to coerce it into answering that — padding the input
and hoping the decoder tolerates reading past the real data, tracking `RangeEncoder.get_compressed()`'s
growth to guess when "enough" had been decoded — failed empirically: its `RangeDecoder` doesn't error
on the first out-of-bounds read, but decoding enough further symbols eventually corrupts its internal
state and raises an unrecoverable assertion.
Confirmed directly with padding sizes from a few hundred
bytes to many kilobytes, both zero-filled and randomly-filled.

**Why rejected.**
It cannot be evaluated further with this library: its own `maybe_exhausted()` docs suggest appending
an explicit end-of-stream sentinel symbol, which fits compressing a message whose symbol content is
already fully known upfront — not this module's shape, where the symbols (words) are themselves the
output being discovered step by step.
A small binary arithmetic coder was written from scratch
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
Researched both available paths.
The Bot API (open registration via @BotFather, no entity
requirement) gives only a labeled-bot identity — safe, but visibly not a person, undermining the
disguise.
MTProto-as-a-personal-account gets the real-profile appearance, but automating a real
personal account this way is explicitly against Telegram's Terms of Service and actively enforced,
including documented bans that follow the phone number to a freshly registered replacement account.

**Why rejected.**
Rejected by the owner on design grounds, not a technical blocker: Telegram already offers reasonably
good opt-in end-to-end privacy of its own (Secret Chats), so there's less value in building this
project's disguise/encryption layer on top of it specifically.
The platforms where that layer adds
the most (MAX, VK, Odnoklassniki — none offer any E2E option at all) are a better use of effort.
This
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
organizations.
Confirmed directly against Yandex's own docs: a bot can only message members of its
own organization, not an arbitrary external user
(`Бот не может отправлять личные сообщения пользователям за пределами своей организации`).
No
OAuth-delegation equivalent to Odnoklassniki's `graph.user.messages` was found for personal-mode
accounts.

**Why rejected.**
It cannot satisfy the medium contract (`send`/`receive` between arbitrary users) with current
tooling: this is a harder blocker than MAX's developer-entity gate or VK's community-only
restriction — not about who's allowed to register, but that the API structurally cannot reach an
arbitrary external user at all.
Registering a shared organization and adding every user as a fake
"employee" is a theoretical workaround, judged an awkward, likely ToS-straining hack, not a real fit.

**What would reopen it.**
A personal-account API surfacing that this research pass didn't find, or Yandex extending Bot API
messaging beyond one organization's own members.
