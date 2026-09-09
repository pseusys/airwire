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
rotating on anything yet either. Revisit this section once a first release/tag exists, and rotate
this file's entries into `memory/changelog-archive/CHANGELOG-v<X>.md` at that point, per the
original template's rotation procedure (kept here for when it's needed): copy this header to the
archived file, leave this file with the header and no entries, and note the rotation as the first
entry of the new cycle.

---

## 2026-09-09 — `client/` and `web-demo/` both get CI-enforced lint, closing TODO A1/A2

*keywords: client.yml, angular-eslint, ng lint, flutter analyze, dart analyze, eslint.config.js*

**Every sub-project now runs its tests and its linter in CI — previously only `core/` did.**
`.github/workflows/client.yml` (new) runs `flutter test`+`flutter analyze` for `client/app` and
`dart test`+`dart analyze` for `client/medium` on every push/PR touching `client/`.
`.github/workflows/web-demo.yml` gained an `ng lint` step, using `angular-eslint@19` (matching the
project's Angular 19, not the `@22` `ng add` installs by default) added via `ng add angular-eslint@19`.

**What changed in the code.**
`web-demo/eslint.config.js` (new), `web-demo/angular.json` (new `lint` architect target),
`web-demo/package.json` (new `lint` script + devDependencies). Fixed the 3 pre-existing violations
`ng lint` immediately surfaced, all auto-fixable and behavior-preserving:
`arithmetic.ts`'s `candidateRanges` now takes `readonly Candidate<T>[]` instead of
`ReadonlyArray<Candidate<T>>` (style-only), and `textures.ts`'s `reactionDiffusion` declares its two
never-reassigned `Float64Array`s (`u`, `v`) with `const` instead of `let`.

**What it means, and what was decided.**
Both new CI jobs were verified locally before being trusted (`flutter analyze`/`dart analyze`/
`flutter test`/`dart test` all pass; `ng lint` reports zero issues after the fixes above) — not just
assumed to work from the workflow YAML alone. TODO items A1 and A2 are closed; see `TODO.md`'s
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
on which). Also fixed, found by re-running `poetry poe lint` after these edits: a pre-existing mypy
failure in `core/tests/test_markov.py::test_finish_sentence_raises_when_no_path_to_end_exists` — a
test-local `chain` dict inferred with fixed-arity `tuple[str, str]` keys, incompatible with
`_finish_sentence`'s `Dict[Tuple[str, ...], ...]` parameter type; fixed with explicit
`dict[tuple[str, ...], ...]` annotations on `chain`/`begin_state`/`state_a`/`state_b`.

**What it means, and what was decided.**
`poetry poe lint` and the full `pytest` suite (174 tests) both pass clean after these changes — run,
not assumed. TODO item A4 is closed; see `TODO.md`'s "Completed and drained" table. Source-code
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
(what's open, what happened). Two real tooling gaps surfaced during the migration and were filed
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
original data," and both are exercised in the test suite. No behavior change was needed to
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
Committed as routine maintenance. See `memory/commands.md`'s "Commands whose output is easy to
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
key via ECDH, per-sender disguise choice derived from `sender_id` alone. As a side effect, every
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
`client/app/`. It's the only evaluated platform offering OAuth-delegated, real-user-scoped messaging
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
needed to reassemble. A further iteration encrypted the header and ack as whole Protobuf messages
(`hyperchunk.proto`) rather than leaving them in cleartext, buying metadata confidentiality and
uniform tamper handling for one `hyperchunk_id`-tagged header.

**What it means, and what was decided.**
See `memory/wire-protocol.md` for the current lifecycle and `memory/rejected-ideas.md` for the
header/ack nonce-derivation idea that was tried on top of this and partially reverted. Header, ack,
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
extra in metadata confidentiality. See `memory/wire-protocol.md`'s Components section for how this
piece fits the rest of the pipeline.
