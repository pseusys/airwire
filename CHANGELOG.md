# Changelog

Step-by-step history of this repo: what changed, when, what was tested, what the result was, and the decision that came out of it.
Source files carry a short pointer here instead of the full history inline.
Explanations of how things *currently* work live in [`memory/`](memory/README.md), not here.

Organized by file, or by date for cross-cutting sessions, **newest first** within each section.
Entries for past releases are frozen in [`memory/changelog-archive/`](memory/changelog-archive/).

## How to navigate this file

Every entry carries a `*keywords:*` line right under its heading, holding the identifiers, flags and constants that distinguish that entry from the rest of the file.
That is the fast path:

```bash
grep -n "^\*keywords:.*<identifier>" CHANGELOG.md                        # entries touching it
grep -rn "^\*keywords:.*<identifier>" memory/changelog-archive/          # and in past releases
grep -n "^##.* <YYYY-MM>" CHANGELOG.md                                   # everything from a month
```

Topic index — grep the phrase in the right column to land on the entries:

| Looking for | Grep |
| --- | --- |
| Why the wire format looks the way it does | `hyperslice`, `hyperchunk`, `OVERLAP` |
| Why there's no off-the-shelf entropy coder | `constriction` |
| The image texture visual-quality tradeoff | `OVERLAP`, `seam MSE` |
| The handshake/session design | `TOFU`, `obf_mode`, `bootstrap_key` |
| This documentation layout itself | `AGENTS.md`, `memory/`, `agentic-layout-template` |

Decisions to *not* do something are in [`memory/rejected-ideas.md`](memory/rejected-ideas.md).
Open work is in [`TODO.md`](TODO.md).

## Rotation

This file covers the **current cycle only** — there have been no releases/tags yet, so it is not
rotating on anything yet either.
Revisit this section once a first release/tag exists, and rotate
this file's entries into `memory/changelog-archive/CHANGELOG-v<X>.md` at that point, per the
original template's rotation procedure (kept here for when it's needed): copy this header to the
archived file, leave this file with the header and no entries, and note the rotation as the first
entry of the new cycle.

---

## 2026-09-09 — Image disguise scores gap-row patches against the texture's true content, closing TODO D13 and superseding D3

*keywords: _guide_patch, position_guided, DEFAULT_TEXTURE_SIZE, seam MSE, toroidal Voronoi, periodic value_noise*

**Investigating D13 ("generate a whole, visually uniform image") surfaced a real alignment bug, not
just the already-known local-blend limitation: `DEFAULT_TEXTURE_SIZE=64` with `DEFAULT_CANVAS_WIDTH=16`
patches meant the source texture was only half as wide as the canvas, so every seed row silently
concatenated two unrelated texture rows side by side — confirmed visually as a sharp vertical seam
down the middle of every row, seed rows included.**

**What changed in the code.**
`DEFAULT_TEXTURE_SIZE` is now `DEFAULT_CANVAS_WIDTH * DEFAULT_PATCH_SIZE` (128, not 64).
`sources/synthesis.py`'s `_seed_index`/`_seed_patch` (flat, modulo-over-deduped-library indexing)
are gone, replaced by `_guide_patch`: every canvas row, seed or gap, maps onto a real row of the
source texture via `row % texture_height_in_patches`, wrapping so a canvas of any height stays
well-defined past one texture period.
That wrap needed the texture itself to tile seamlessly:
`reaction_diffusion` already did (its Laplacian is toroidal by construction); `voronoi` now computes
nearest-cell distance against all 9 periodic images of each cell point; `value_noise` now indexes
its coarse grid modulo its own size instead of padding it.
`_candidate_weights` gained a
`position_guided` flag: when true (`value_noise`, `voronoi`, `reaction_diffusion`), gap-row
candidates are scored against the *true* patch the texture holds at that exact position, not just
against neighboring seed-row edges; `attractor` (`position_guided=False`) keeps the original
edge-only scoring, since direct 2x2-tile testing showed it has no exploitable 2-D positional
structure to compare against (a sparse chaotic-orbit density histogram, not a spatially periodic
field).

**What was measured** (same seam-MSE method the `OVERLAP` experiment used, plus a new "guide
fidelity" metric — mean squared difference between what was actually placed and the texture's true
content at that position — fixed non-random ~280-byte input, seed 42):

| Flavor | Seam MSE (old) | Seam MSE (new) | Guide fidelity (new) |
| --- | --- | --- | --- |
| `value_noise` | 4976.9 | 5707.7 | 4104.0 |
| `voronoi` | 3962.1 | 4098.1 | 3982.5 |
| `reaction_diffusion` | 7945.4 | 6402.7 | 4847.0 |
| `attractor` | 3.9 | 18.5 | n/a (edge-only, unchanged mechanism) |

Seam MSE alone is a limited signal for this change (as `OVERLAP`'s own entry in
`memory/rejected-ideas.md` already found): it stayed flat or rose slightly for `value_noise`/`voronoi`
even though direct visual inspection (upscaled PNG, before/after, same method used earlier this
session) shows a dramatic improvement for both — `voronoi`'s large flat cells now survive
recognizably across many rows instead of fragmenting into a patchwork of small triangles, and
`reaction_diffusion`'s coral-like tubes now form real connected loops instead of maze-like noise.
`attractor`'s much-worse-looking relative seam MSE change (3.9 to 18.5) is both still negligible in
absolute terms and confirmed unrelated to this change: the same near-empty appearance at this
particular seed was already present in the pre-existing generator at the old texture size, verified
directly against the unmodified code.
Full round-trip correctness verified for all four flavors,
including payloads large enough to exercise the periodic wraparound past one texture period; full
`core/` suite (202 tests) and lint (flake8/black/mypy --strict) both pass.

**Ported to `web-demo/` the same day.**
`web-demo/src/app/core/synthesis.ts` and `textures.ts` mirror every change above line-for-line
(`guidePatch` replacing `seedIndex`/`seedPatch`, the `positionGuided` flag, toroidal `voronoi`/
`valueNoise`), and `app.component.ts` passes `flavor !== 'attractor'` at both the obfuscate and
reveal call sites.
7 new Karma tests cover per-flavor round-trips past one texture period and
tile-seam sanity for all three now-periodic generators; all 62 web-demo tests and `ng lint` pass.
Verified live in a real browser (built `dist/`, served statically, driven with Playwright against
system Chrome): the `reaction_diffusion` output shows the same real connected-loop structure the
Python side does, and reveal round-trips correctly for all four flavors.

**What it means, and what was decided.**
Kept, for `value_noise`/`voronoi`/`reaction_diffusion`/the alignment fix; `attractor` keeps its
original mechanism unchanged (by design, not a regression).
This substantially addresses D3's
original concern (the same two flavors it named) via a different, more fundamental mechanism than
either of D3's own untried directions, so D3 is closed as superseded rather than attempted
separately.
See `memory/wire-protocol.md` and `docs/superpowers/specs/2026-09-09-image-synthesis-redesign-design.md`
for the full design.

## 2026-09-09 — SMS/MMS transport reasoning moved out of `README.md` into a clearly-labeled idea in `memory/medium.md`

*keywords: Transport Modes, SMS Size Budget, MMS Support, Pricing, Future medium idea*

**Root `README.md` described web/SMS mode-switching, an SMS size budget, MMS-gated premium
disguise tiers, and a free/premium pricing split as if they were current, tested product
behavior — none of it is.** Testing right now happens entirely against a real messenger-backed
medium (Odnoklassniki); SMS/MMS remains the product's original transport concept, not a parallel
effort already in progress.

**What changed in the code.**
`README.md` lost its "Transport Modes," "SMS Size Budget," and "MMS Support (Premium)" sections and
its "Pricing" section, and its "Message Format"/"Encryption" sections dropped their SMS-specific
framing (`sender: phone number` → `sender: medium-specific — e.g. an OAuth-derived user ID`; the
"Web Mode"/"SMS Mode" encryption split collapsed into one medium-agnostic "Encryption" section,
since the crypto design itself — X25519, hyperslices, AEAD — never depended on which one).
`memory/medium.md` gained a new "Future medium idea: SMS/MMS transport" section carrying that
reasoning forward (mode switching, the 160-byte SMS budget that originally sized
`DEFAULT_CHUNK_SIZE`, the MMS-gated-disguise-tier product idea), plus a new `SMS/MMS` row in its
Providers table, both explicitly labeled as not built or tested. `memory/keywords.md` gained `SMS`,
`MMS` triggers routing to it.

**What it means, and what was decided.**
The two disguise mechanisms (Markov text, image steganography) themselves were never actually
MMS-specific — they're medium-agnostic `core/` features already documented in
`memory/wire-protocol.md` — only the *pricing tier* that used to gate them was SMS/MMS-specific,
and that gating doesn't exist in `core/` or `client/` today. `verify_memory.py` and
`markdownlint-cli2` both stay clean.

## 2026-09-09 — Full markdown reflow to one-sentence-per-line, `--strict` re-enabled in CI, closing TODO D11

*keywords: sentence_breaks, fix_sentence_breaks, --fix, MD032, MD040, MD001, MD060*

**234 "two sentences on one line" warnings across every markdown file in the repo, plus 55
`markdownlint-cli2` findings in the 4 files previously excluded from CI, are both gone —
`verify_memory.py --strict` and `markdownlint-cli2` are now both zero-issue, repo-wide.**

**What changed in the code.**
`memory/scripts/verify_memory.py` gained a `--fix` mode (`fix_sentence_breaks`): it reuses the
exact same `sentence_breaks` detection `check_style` warns with, so a reflowed file is guaranteed
to report zero violations afterward, rather than relying on a separately-written heuristic that
could disagree with the checker.
Ran it repo-wide (19 files touched), then
`npx markdownlint-cli2 --fix` for the remaining findings (auto-fixed 52 of 55: all MD032
blanks-around-lists, all MD060 table style), then fixed the last 3 by hand — one MD001
heading-increment (a subtitle styled as an `### H3` directly under an `# H1`, with no `##` between,
in `docs/research-proposal.md`; converted to a plain paragraph instead of a heading) and two MD040
bare code fences (tagged `text`, since neither was real source code). `.markdownlintignore` and
`.github/workflows/lint.yaml`'s `globs` no longer exclude `docs/superpowers/` or
`docs/research-proposal.md`; the verify step runs `--strict`, matching what a contributor should
run locally (`memory/dos-and-donts.md` updated to say so).

**What it means, and what was decided.**
Every file was spot-checked in the actual diff, not just trusted from a clean exit code — table
rows were confirmed untouched (the checker's own `TABLE_ROW` guard), and the largest single diff
(`docs/superpowers/specs/2026-08-27-messaging-protocol-design.md`, a 485-line technical spec) was
read in full post-reflow to confirm no numbered list, link, or code span was corrupted by the split.
`core/` (174 tests, lint), `client/app` (17 tests, analyze), `client/medium` (32 tests, analyze), and
`web-demo/` (55 tests, lint) all still pass.
TODO item D11 is closed.

## 2026-09-09 — `docs/superpowers/`'s shipped-feature specs and plans retired into `memory/`, closing TODO A8

*keywords: rejected-ideas.md, target spec, dart-protocol.md, C1, pair-specific bootstrap_key*

**6 of `docs/superpowers/`'s 10 design specs/plans described features that had already shipped —
retired now that their content is properly indexed elsewhere; the other 4 were kept, deliberately,
for two different reasons.** This session's earlier docs migration left `docs/superpowers/`
untouched entirely, treating it as a separate skill-owned archive; reversed here, since its content
genuinely describes current or planned system behavior, the exact thing `memory/` exists for.

**What changed in the code.**
Deleted: the okru-prototype, markov-boundary-and-filler, and markov-seed-broadening spec+plan pairs
(6 files) — verified each against `memory/wire-protocol.md`, `memory/medium.md`, and existing
`CHANGELOG.md` entries first, and added 3 new `memory/rejected-ideas.md` entries for design-stage
alternatives that weren't recorded anywhere yet (period-based Markov sentence-boundary
reconstruction, two rejected approaches to Markov seed-gating, and the target spec's rejected
certificate replay-detection). `memory/handshake.md`'s "Target spec" section gained the load-bearing
facts the messaging-protocol-design.md draft has that it didn't yet (pair-specific `bootstrap_key`,
key-selection-on-receive with no explicit message-type field).
Found and fixed two more dangling
`docs/superpowers/specs/...` links in `core/sources/markov.py`'s docstring (missed by the earlier
A4 pass — outside what `verify_memory.py` scans, since it only checks `.md` files) and one stale
comment in `web-demo/src/app/core/prng.ts`.
Also surfaced and filed: `TODO.md` C1 (three OAuth/API
assumptions from the now-deleted Odnoklassniki design spec that were never actually verified against
the real API — `client_id` is still a literal placeholder in `client/app/lib/main.dart`), now also
documented as known gaps in `memory/medium.md`.

**What it means, and what was decided.**
Kept in place, deliberately: `2026-08-27-messaging-protocol-design.md` (still draft, 485 lines,
describes the not-yet-implemented rotation crypto scheme — absorbing it fully isn't earned until
real implementation begins, per `memory/README.md`'s own growth criteria; only its headline facts
were pulled into `memory/handshake.md`) and the three unexecuted Dart protocol plans (referenced
from `TODO.md` D6, to execute or retire only once `client/`'s protocol port actually starts).
`memory/dos-and-donts.md` gained a new house rule: fold a shipped feature's spec/plan into
`memory/`/`CHANGELOG.md` and delete the original as part of shipping it, not months later — this
session found 6 that had waited that long. `core/` tests (174) and lint, and `web-demo/` tests (55)
and lint, all still pass.

## 2026-09-09 — Root `README.md`'s License section resolved, closing TODO A6

*keywords: license, proprietary, all rights reserved*

**`README.md`'s License section literally read `TODO!` — no license had ever been chosen.** Owner
decided: proprietary, all rights reserved, no license file — stated explicitly in `README.md`
rather than left as an unresolved placeholder.
TODO item A6 is closed.

## 2026-09-09 — `client/app` and `client/medium` both get real READMEs, closing TODO A7

*keywords: client/app/README.md, client/medium/README.md*

**`client/app/README.md` was still the unedited Flutter-CLI boilerplate, and `client/medium/` had no
README at all** — the odd one out next to `core/README.md` and `web-demo/README.md`, both real and
maintained.

**What changed in the code.**
`client/app/README.md` now describes what the app actually does (VK ID/Odnoklassniki login, a
conversation screen) and, explicitly, what it doesn't do yet (no encryption/chunking/disguise — the
real airwire protocol isn't wired in, tracked at `TODO.md` D6). `client/medium/README.md` (new)
documents the package's contents and points at `memory/medium.md` for the full `Medium` contract.
Both link to `../../memory/commands.md` and `../../.github/workflows/client.yml` for setup/CI.

**What it means, and what was decided.**
`flutter analyze`/`dart analyze` both still clean, `verify_memory.py` 0 errors, full-repo
`markdownlint-cli2` 0 issues (21 files, up from 20).
TODO item A7 is closed.

## 2026-09-09 — Full repo coding-guidelines review, closing TODO A3

*keywords: import json, _load_model, markovify, grpc_tools, historical-narrative docstrings*

**Auditing `core/`, `client/`, and `web-demo/` against `memory/coding-guidelines.md` as actually
written (not just "does the linter pass") found one real violation, two rules that didn't match
legitimate pre-existing practice, and one larger stylistic tension worth a decision rather than a
silent rewrite.**

**What changed in the code.**
`core/sources/markov.py`'s `_load_model` had a function-local `import json` — plain stdlib, no
justification for a lazy import — moved to the top of the file with the rest of the module's
imports.
Verified: `poetry poe lint` and `test_markov.py`'s 32 tests both still pass.

**What it means, and what was decided.**
Two other function-local imports found (`scripts/model.py`'s `markovify`, `scripts/process.py`'s
`grpc_tools`) turned out to be deliberate: both are optional, `devel`-extra-only dependencies,
lazily imported so importing the module itself doesn't force the extra to be installed —
`memory/coding-guidelines.md`'s Python section now documents this as an explicit exception rather
than leaving the rule to look violated.
Similarly, "test code lives in its own tree" didn't actually
describe `web-demo/`'s already-established, idiomatic-Angular co-located `*.spec.ts` convention —
documented as the one deliberate exception instead of being "fixed" by moving working test files.
The larger finding — `core/`'s most-explained modules (`markov.py`, `chunking.py`) narrate history
inline in their docstrings ("Resolved: X used to Y"), predating and at odds with this session's own
"comments describe the code, never how it came to be" rule — was filed as `TODO.md` E3 rather than
rewritten unilaterally: it's core/'s established documentation voice across several files, and
unwinding it is a real editing decision, not a mechanical fix.

## 2026-09-09 — `web-demo/src/app/core/`'s five untested modules get unit test coverage, closing TODO A5

*keywords: arithmetic.spec.ts, synthesis.spec.ts, textures.spec.ts, prng.spec.ts, png.spec.ts*

**Only `markov.ts` had a dedicated spec file; `arithmetic.ts`, `synthesis.ts`, `textures.ts`,
`prng.ts`, and `png.ts` had none at all** — a regression in any of them previously surfaced only as
a component-level test failure (if at all) or a manual browser check.
All five now have real unit
tests, 42 new tests total, following `markov.spec.ts`'s established pattern (round-trip,
determinism, seed/data-differs-across-runs).

**What changed in the code.**
`arithmetic.spec.ts` (19 tests: `ceilLog2Ratio`'s exact-power-of-two edge case the module's own
docstring flags as the reason it isn't a literal float-log2 port, `candidateRanges`' proportional
partitioning, `BitCursor`/`BitAccumulator` round-tripping arbitrary bytes). `synthesis.spec.ts`
(5 tests: encode/decode round trip across payload sizes including empty, canvas-dimension
invariants, determinism, decode failing closed against the wrong texture *and* against a tampered
patch — the image disguise's own version of Markov's tamper-detection tests).
`textures.spec.ts` (6 tests: determinism and seed-differs for all four flavors, `textureByName`
dispatch). `prng.spec.ts` (10 tests: `Prng`'s bounds and determinism, `chainSeed`'s determinism and
32-bit-unsigned output). `png.spec.ts` (2 tests: a real browser canvas round trip via
`imageToPngBlob`/`blobToImage`, confirming the bit-exactness the module's docstring claims — not
just assumed from "PNG is lossless" in the abstract).

**What it means, and what was decided.**
55/55 tests pass (13 pre-existing + 42 new), full suite runs in ~2 seconds; `ng lint` reports zero
issues on the new files.
TODO item A5 is closed; see `TODO.md`'s "Completed and drained" table.

## 2026-09-09 — `client/` and `web-demo/` both get CI-enforced lint, closing TODO A1/A2

*keywords: client.yml, angular-eslint, ng lint, flutter analyze, dart analyze, eslint.config.js*

**Every sub-project now runs its tests and its linter in CI — previously only `core/` did.**
`.github/workflows/client.yml` (new) runs `flutter test`+`flutter analyze` for `client/app` and
`dart test`+`dart analyze` for `client/medium` on every push/PR touching `client/`.
`.github/workflows/web-demo.yml` gained an `ng lint` step, using `angular-eslint@19` (matching the
project's Angular 19, not the `@22` `ng add` installs by default) added via `ng add angular-eslint@19`.

**What changed in the code.**
`web-demo/eslint.config.js` (new), `web-demo/angular.json` (new `lint` architect target),
`web-demo/package.json` (new `lint` script + devDependencies).
Fixed the 3 pre-existing violations
`ng lint` immediately surfaced, all auto-fixable and behavior-preserving:
`arithmetic.ts`'s `candidateRanges` now takes `readonly Candidate<T>[]` instead of
`ReadonlyArray<Candidate<T>>` (style-only), and `textures.ts`'s `reactionDiffusion` declares its two
never-reassigned `Float64Array`s (`u`, `v`) with `const` instead of `let`.

**What it means, and what was decided.**
Both new CI jobs were verified locally before being trusted (`flutter analyze`/`dart analyze`/
`flutter test`/`dart test` all pass; `ng lint` reports zero issues after the fixes above) — not just
assumed to work from the workflow YAML alone.
TODO items A1 and A2 are closed; see `TODO.md`'s
"Completed and drained" table.

## 2026-09-09 — `core/` source comments no longer point at the deleted `docs/design-decisions.md`

*keywords: derive_nonce, HyperchunkHeader, _HEADER_DISGUISE_SEED, hyperchunk.proto, handshake.proto*

**A grep for "design decision #" and "docs/design-decisions\|roadmap\|crypto-summary\|handshake\|medium-"
across all of `core/` found 22 stale lines across 8 files, not the 2 files TODO item A4 originally
scoped** — the prior session's docs migration had only checked markdown files' links
(`verify_memory.py` doesn't scan source code), not source comments/docstrings referencing the same
now-deleted docs by name.

**What changed in the code.**
Fixed in `core/sources/{crypto,chunking,markov,handshake,synthesis}.py`,
`core/sources/proto/{hyperchunk,handshake}.proto`, and `core/scripts/demo.py`: every
`docs/handshake.md` reference now points at `memory/handshake.md`; every `design decision #N`/
`docs/design-decisions.md` reference now points at the specific place that content actually lives
(`memory/wire-protocol.md`, `memory/rejected-ideas.md`'s relevant entry, or `TODO.md` D1/D2, depending
on which).
Also fixed, found by re-running `poetry poe lint` after these edits: a pre-existing mypy
failure in `core/tests/test_markov.py::test_finish_sentence_raises_when_no_path_to_end_exists` — a
test-local `chain` dict inferred with fixed-arity `tuple[str, str]` keys, incompatible with
`_finish_sentence`'s `Dict[Tuple[str, ...], ...]` parameter type; fixed with explicit
`dict[tuple[str, ...], ...]` annotations on `chain`/`begin_state`/`state_a`/`state_b`.

**What it means, and what was decided.**
`poetry poe lint` and the full `pytest` suite (174 tests) both pass clean after these changes — run,
not assumed.
TODO item A4 is closed; see `TODO.md`'s "Completed and drained" table.
Source-code
comments referencing `memory/`/`TODO.md` locations are exactly the kind of reference
`verify_memory.py` cannot check (it only scans `.md` files) — worth remembering next time a `memory/`
file gets renamed or retired.

## 2026-09-08 — Documentation layout adopted from `agentic-layout-template`

*keywords: AGENTS.md, memory/, wire-protocol.md, handshake.md, medium.md, rejected-ideas.md, verify_memory.py*

**This repo's documentation was reorganized around the `AGENTS.md`/`memory/`/`TODO.md`/`CHANGELOG.md`
layout from [pseusys/agentic-layout-template](https://github.com/pseusys/agentic-layout-template).**
Before this, `docs/` had grown seven loosely-related files (a decision log mixing current-state
reasoning with reverted experiments, a roadmap, crypto/handshake/medium reference docs) with no
routing between them and no single place recording what had been tried and rejected.

**What changed in the repo.**
`docs/design-decisions.md` and `docs/roadmap.md` are retired: their still-current reasoning moved
into `memory/wire-protocol.md` and `memory/handshake.md`, their settled rejections into
`memory/rejected-ideas.md`, their forward-looking items into `TODO.md`. `docs/crypto-summary.md` and
`docs/handshake.md` merged into `memory/handshake.md`, clearly separating what `core/` actually
implements from the not-yet-built rotation/directional-key target spec. `docs/medium-candidates.md`
and `docs/medium-interface.md` merged into `memory/medium.md`. `docs/superpowers/{specs,plans}/` and
`docs/research-proposal.md`/`docs/references.bib` (the separate airwave research track) were left
untouched — referenced from `AGENTS.md`, not absorbed.

**What it means, and what was decided.**
`docs/` now holds only the airwave research track and the superpowers skill's own design/plan
archive; everything else the previous `docs/` held is either in `memory/` (how things work now,
grown only as earned — see `memory/README.md`'s growth table) or in `TODO.md`/`CHANGELOG.md`
(what's open, what happened).
Two real tooling gaps surfaced during the migration and were filed
in `TODO.md` §A rather than fixed silently: `web-demo/` has no linter configured at all, and no CI
runs `client/`'s tests.

## 2026-09-08 — Decoding a Markov-disguised message with the wrong seed can raise `ValueError`, not just return corrupted bytes

*keywords: candidate_ranges, ValueError, seed-gating, permutation, squeeze-out*

**The seed-gating design for the Markov text disguise assumed decoding with the wrong seed would
always just recover corrupted bytes — running the new test immediately proved that wrong.** At a
narrow remaining bit budget, `core/sources/arithmetic.py`'s `candidate_ranges` can squeeze a real
candidate out of its assigned bit range entirely (`if end >= cursor` in its boundary-building loop);
which candidate gets squeezed depends on candidate order, so decoding with the wrong seed-derived
permutation can hit a word `candidate_ranges` no longer assigns any range to at all, raising the
existing `"... is not a valid continuation ..."` `ValueError` — an earlier, more explicit failure
than silent corruption, discovered only by running
`test_decode_with_wrong_nonce_does_not_recover_original_data` across several payload sizes, not by
reasoning through the code.

**What changed in the code.**
`core/sources/markov.py` and `web-demo/src/app/core/markov.ts` both shuffle every visited state's
candidate order by a nonce/seed-derived permutation before handing it to `candidate_ranges`, so the
whole encode/decode walk depends on the seed, matching how the image disguise's seed already gates
its whole texture (see `memory/wire-protocol.md`). `MarkovEncoding.decode`'s signature is unchanged
(it already took `nonce: bytes`); the web-demo's `decodeText` gained a `seed` parameter it never
needed before.

**What it means, and what was decided.**
The design doc's error-handling section was corrected in place rather than left wrong: both outcomes
(corrupted bytes, or this `ValueError`) are documented as acceptable evidence of "did not recover the
original data," and both are exercised in the test suite.
No behavior change was needed to
`MarkovModelError` or decode's existing tamper-detection `ValueError` cases — this is the same
exception, hit via a new path.

## 2026-09-08 — `client/pubspec.lock` refreshed against the installed Flutter/Dart toolchain

*keywords: pubspec.lock, analyzer, Dart SDK constraint, pub get*

**A `client/pubspec.lock` diff sitting uncommitted for some time (analyzer 7.7.1→13.3.0, Dart SDK
constraint `>=3.8.0-0`→`>=3.11.0`, `js` package dropped, several other transitive bumps) was
confirmed harmless before committing, not assumed harmless.** Local Flutter is 3.47.2 / Dart 3.13.2
— newer than whatever the old lockfile was resolved against — so the diff is routine `pub get`
drift, not a deliberate dependency change.

**What changed in the code.**
Nothing in `pubspec.yaml` (no manifest version constraints changed); only the resolved lockfile.
Verified by running the full suite on the refreshed lockfile: 17/17 `client/app` tests
(`flutter test`) and 32/32 `client/medium` tests (`dart test`) pass.

**What it means, and what was decided.**
Committed as routine maintenance.
See `memory/commands.md`'s "Commands whose output is easy to
misread" section — this exact diff shape (a large, unexplained lockfile jump with no
`pubspec.yaml` change) is expected the first time `pub get` runs against a newer locally-installed
SDK, not a sign something broke.

## 2026-09-08 — Image steganography and session handshake completed

*keywords: synthesis.py, textures.py, handshake.py, ImageEncoding, obf_mode, MARKOV_ENG, MARKOV_RUS*

**Both of Phase 0's remaining gaps — image steganography and the session handshake — are now
implemented and wired into the wire protocol**, closing out `docs/roadmap.md`'s Phase 0 status
("mostly done" → both original obfuscation encoders done, handshake designed and implemented).

**What changed in the code.**
`core/sources/synthesis.py`/`textures.py`: patch-based reversible texture synthesis, four flavors
(`SYNTHESIS_VALUE_NOISE`/`VORONOI`/`REACTION_DIFFUSION`/`ATTRACTOR`), each its own `ChunkEncoding`
yielding one PNG atom per hyperslice. `core/sources/handshake.py`: TOFU certificate exchange, session
key via ECDH, per-sender disguise choice derived from `sender_id` alone.
As a side effect, every
disguise variant (Markov language or texture flavor) now has its own wire identifier, resolving the
earlier limitation where only `MARKOV_ENG` was auto-detected by `unpack_hyperchunk` (`MARKOV_RUS`
packed-then-unpacked reliably failed before this).

**What it means, and what was decided.**
See `memory/wire-protocol.md` and `memory/handshake.md` for current behavior; see
`memory/rejected-ideas.md` for the `OVERLAP`-window experiment measured and reverted along the way.
Real MMS carrier transcoding (which could silently break the bit-exactness the image scheme depends
on) remains explicitly out of scope for Phase 0.

## 2026-09-01 — Odnoklassniki (OK.ru) chosen as the first `Medium` implementation

*keywords: OdnoklassnikiMedium, VkIdOAuth, PKCE, graph.user.messages, Medium*

**Odnoklassniki was chosen over MAX, VKontakte, Yandex Messenger, Telegram, ICQ and TamTam as the
first medium to implement**, and a working prototype now exists in `client/medium/` and
`client/app/`.
It's the only evaluated platform offering OAuth-delegated, real-user-scoped messaging
(`graph.user.messages`) without a Terms-of-Service conflict.

**What changed in the code.**
`client/medium/lib/src/medium.dart` (the `Medium` contract), `odnoklassniki_medium.dart`,
`vk_id_oauth.dart` (OAuth 2.1+PKCE), `auth_store.dart` (Hive-backed token storage);
`client/app/`'s auth/messaging blocs and login/conversation screens wire it into a Flutter Web shell.

**What it means, and what was decided.**
See `memory/medium.md` for the full contract and the other providers' status; see
`memory/rejected-ideas.md` for why Telegram and Yandex Messenger specifically were ruled out.

## 2026-07-28 — Hyperslice/hyperchunk model replaces per-chunk AEAD

*keywords: hyperslice, hyperchunk, HyperchunkHeader, HyperchunkAck, chunking.py, per-chunk AEAD*

**Paying the AEAD nonce/tag cost once per ~1KB hyperslice instead of once per ~83-byte chunk raised
raw-byte efficiency from 68.0% to 90.9%** for a 1024-byte message (13 messages/1505 raw bytes →
10 messages + 1 ack/1126 raw bytes), and added hyperchunk-level delivery acknowledgement and retry
that the original per-chunk design never had.

**What changed in the code.**
`core/sources/chunking.py`: `pack_hyperchunk`/`send_hyperchunk` now encrypt one hyperslice as a
single AEAD operation and split the ciphertext into low-overhead chunks (a plain sequence number, no
per-chunk crypto); one `HyperchunkHeader` message per hyperslice carries the nonce/tag/chunk-count
needed to reassemble.
A further iteration encrypted the header and ack as whole Protobuf messages
(`hyperchunk.proto`) rather than leaving them in cleartext, buying metadata confidentiality and
uniform tamper handling for one `hyperchunk_id`-tagged header.

**What it means, and what was decided.**
See `memory/wire-protocol.md` for the current lifecycle and `memory/rejected-ideas.md` for the
header/ack nonce-derivation idea that was tried on top of this and partially reverted.
Header, ack,
and data currently share one symmetric key, distinguished only by nonce — accepted as a
simplification, not revisited since (a domain-separated key per message class would need session
setup machinery this module doesn't own).

## 2026-07-28 — Pluggable `ChunkEncoding` payload encodings, and the Markov-chain text disguise built on a from-scratch arithmetic coder

*keywords: ChunkEncoding, encode_atoms, greedy_pack, Base64Encoding, constriction, sources/arithmetic.py, sources/markov.py*

**Chunk payload bytes are no longer always raw ciphertext** — `ChunkEncoding.encode_atoms` plus
`chunking._greedy_pack` decouple wire-chunk packing from a fixed input:output byte ratio, which the
original fixed-boundary packer assumed and a Markov-chain encoding's variable ratio breaks.
`Base64Encoding` shipped first (fixed but non-1:1 ratio) as a simpler exercise of the same machinery.
The Markov-chain text disguise itself needed a from-scratch binary arithmetic coder
(`sources/arithmetic.py`) after `constriction` (the obvious off-the-shelf entropy-coding library) was
tried and found structurally unable to support open-ended, self-terminating decode — see
`memory/rejected-ideas.md` for the full evaluation.

**What changed in the code.**
`core/sources/encodings.py` (`ChunkEncoding`, `PlainEncoding`, `Base64Encoding`),
`core/sources/arithmetic.py` (`BitCursor`, `BitAccumulator`, `candidate_ranges`, exact integer
arithmetic, no floating point anywhere in the encode/decode path), `core/sources/markov.py`
(frozen per-language Markov chains, `MARKOV_ENG`/`MARKOV_RUS`).

**What it means, and what was decided.**
`ChunkEncoding.encoding` is recorded in the (already-encrypted) `HyperchunkHeader`, costing nothing
extra in metadata confidentiality.
See `memory/wire-protocol.md`'s Components section for how this
piece fits the rest of the pipeline.
