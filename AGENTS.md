# AGENTS.md — orientation for AI coding assistants

Read this first, then follow a pointer.
Depth lives in [`memory/`](memory/README.md), not here — this file is the map.

## Before you start

Reading everything every session is as wrong as reading nothing.
Read what this task makes relevant, before acting rather than after:

- **Scan the request against [`memory/keywords.md`](memory/keywords.md)** and open what it routes you to.
- **Before proposing an idea**, grep [`memory/rejected-ideas.md`](memory/rejected-ideas.md).
  One grep is cheaper than one investigation.
- **Before debugging anything environment-shaped** — encoding, paths, shell, a library that will not import — read [`memory/gotchas.md`](memory/gotchas.md) (empty so far — nothing has earned an entry yet).
- **Before running a command you are inventing**, check [`memory/commands.md`](memory/commands.md) for the one that exists.
- **Before calling a change done**, re-read the evidence rules in [`memory/dos-and-donts.md`](memory/dos-and-donts.md).

## Development routine

This project uses the **superpowers** skill set for feature-sized work, not an inline routine:
brainstorm the design (hard gate — no code until a design is presented and approved) → write an
implementation plan → execute it task by task → finish the branch (verify tests, then merge / PR /
keep-as-is, the owner's call).
Invoke those skills directly rather than improvising an equivalent
routine; keeping one routine in one place is the point.

Documentation is updated in the same step as the change, not after.

## What this is

1. A message is composed locally (no server-side storage anywhere in this protocol).
2. A session handshake establishes a symmetric key and a per-sender disguise choice, unilaterally derivable from public identifiers — no prior exchange needed (see [`memory/handshake.md`](memory/handshake.md)).
3. The message is encrypted, cut into hyperslices, and each hyperslice is re-rendered as either plausible text or a plausible image via a shared arithmetic-coding trick (see [`memory/wire-protocol.md`](memory/wire-protocol.md)).
4. It's sent over whichever `Medium` the conversation uses — currently Odnoklassniki, OAuth-delegated (see [`memory/medium.md`](memory/medium.md)) — with per-hyperchunk acknowledgement and retry.
5. The receiver reverses every step and decrypts locally; delivery status (Pending/Sent/Delivered) is tracked client-side only.

**Three independent sub-projects, no shared build step:**

- **`core/`** — the real Python protocol implementation.
Working directory: `core/`.
Runtime: Python 3.11+/3.12 via Poetry, local `.venv`.
No secrets.
- **`client/`** — a Dart pub workspace (`client/app`: Flutter Web; `client/medium`: pure Dart).
Working directory: `client/app/` or `client/medium/` respectively.
Runtime: Dart ≥3.6.0, Flutter pinned to a specific `stable` revision (`client/app/.metadata`).
No secrets currently — OAuth tokens are handled entirely client-side via Hive, nothing is committed.
- **`web-demo/`** — a standalone Angular 19 demo of the disguise mechanism only (no encryption, no chunking, no handshake).
Working directory: `web-demo/`.
Runtime: Node 22 + npm.

No secrets exist anywhere in this repo yet — nothing to bootstrap.

## Where to look next

| I need to… | Go to |
| --- | --- |
| Know which docs this task needs | [`memory/keywords.md`](memory/keywords.md) |
| Know the house rules before editing | [`memory/dos-and-donts.md`](memory/dos-and-donts.md) |
| Write code in one of this project's languages | [`memory/coding-guidelines.md`](memory/coding-guidelines.md) |
| Understand the wire protocol (hyperslices, chunking, disguise) | [`memory/wire-protocol.md`](memory/wire-protocol.md) |
| Understand the handshake or crypto scheme (**current vs. target — they differ**) | [`memory/handshake.md`](memory/handshake.md) |
| Understand the `Medium` transport contract or provider choices | [`memory/medium.md`](memory/medium.md) |
| Run something | [`memory/commands.md`](memory/commands.md) |
| Avoid a known platform or environment trap | [`memory/gotchas.md`](memory/gotchas.md) |
| Check whether an idea was already tried | [`memory/rejected-ideas.md`](memory/rejected-ideas.md) |
| Automate a task I am about to do by hand twice | [`memory/automation-scripts.md`](memory/automation-scripts.md) |
| Find when and why something changed | [`CHANGELOG.md`](CHANGELOG.md) (grep the `*keywords:*` lines) |
| Know what's open right now | [`TODO.md`](TODO.md) |

Full index: [`memory/README.md`](memory/README.md).

## Repository layout

```text
airwire/
├── AGENTS.md / CLAUDE.md / README.md / CHANGELOG.md / TODO.md
├── memory/                  ← the knowledge base (start at memory/README.md)
│
├── core/                    ← the real Python protocol implementation (Poetry)
│   ├── sources/             ← crypto, chunking, encodings, markov/arithmetic, synthesis/textures, handshake
│   ├── scripts/             ← protobuf codegen, Markov model training, demo CLI, codestyle.py (lint runner)
│   └── tests/               ← pytest, mirrors sources/
│
├── client/                  ← Dart pub workspace
│   ├── app/                 ← Flutter Web app (bloc-based auth/messaging, no protocol integration yet)
│   └── medium/              ← pure-Dart Medium contract + OdnoklassnikiMedium implementation
│
├── web-demo/                ← standalone Angular 19 demo of the disguise mechanism only
│   └── src/app/core/        ← TypeScript port of arithmetic/markov/synthesis/textures -- see coding-guidelines.md's mirrored-implementation rule
│
└── docs/                    ← research track (airwave, out of scope of this knowledge base) + the
                                superpowers skill's own design-spec/implementation-plan archive
                                (docs/superpowers/{specs,plans}/) -- referenced, not absorbed, see memory/README.md
```

## The rules that matter most

1. **Prefer editing over adding**; no premature abstraction, no defensive padding, no compatibility shims.
2. **Long narrative goes in `memory/`**, not in a docstring or in this file.
3. **`docs/crypto-summary.md`'s rotation/directional-key crypto scheme is a target spec, not what `core/` implements.** Read `core/sources/crypto.py`/`chunking.py`/`handshake.py` for current behavior; see [`memory/handshake.md`](memory/handshake.md) for both, clearly separated.
Treating the spec as deployed reality produces confidently wrong analysis.
4. **Run the test before trusting a claim about failure behavior**, especially "this can't happen" claims about something not yet implemented.
The seed-gating design for the Markov text disguise assumed decoding with the wrong seed could only ever return corrupted bytes, never raise — reasoned from the code, not verified.
Running the actual test immediately falsified it.
See `CHANGELOG.md`'s entry on it.

Full versions of these: [`memory/dos-and-donts.md`](memory/dos-and-donts.md).

## Responding rules — how to report back

pseusys reads every answer, alone — this is a solo project.
Long ones are expensive to read and bury the decision.
Rules 1-5 are hard; rule 6 is a preference — follow it by default, break it when there is a reason.

**1. Be precise, not verbose.**
Say the thing.
Cut the preamble, the recap of what you were asked, and the narration of what you are about to do.

**2. Use this shape, one paragraph per section, in this order.**
`Running` is one line, not a paragraph.
Anything less important goes *below* it, clearly marked as detail.

| section | content |
| --- | --- |
| **Done** | What you actually did. |
| **Results** | The numbers — **as a table or chart** wherever one fits. |
| **Needs attention** | What is wrong, risky, or awaiting a decision from the owner. Say plainly if there is nothing. |
| **Next** | What you suggest doing, and why that and not something else. |
| **Running** | **One line.** Every background job in flight at the moment of writing, with its progress. `none` if there are none. |

**3. Ask early rather than guessing** when an answer would change what you build.
Do not let that suppress your own proposals — suggest freely, and say which option you would pick.

**4. Keep the session's plan in `TODO.md` §A as you go**, not at the end.
An idea agreed to and not written down is an idea lost.
Add the item the moment it's agreed, with What / How / Why filled in.

**5. Update the docs in the same step as the change**, not later.
[`TODO.md`](TODO.md) and [`CHANGELOG.md`](CHANGELOG.md) always, plus whichever of `memory/` the change touches, plus [`memory/keywords.md`](memory/keywords.md) if you added or removed a doc.
A finding that is not written down did not happen.

**6. Prefer to drain `TODO.md` §A before wrapping up a session.** *(Preference, not a rule.)*
§A is the working queue: put work there as soon as it is agreed — **including work you could do now but do not strictly need now** — and try to finish or re-tier it before you stop.
Items legitimately stay in §A when they are owned by someone else, blocked on an answer, or simply still queued.
The point is that §A reflects reality at session end, not that it is empty.

## Internal rules — how to work

Separate from the responding rules above: these govern what you do, not what you say.
Each is earned by a specific failure in this repo — the cost is in the "because" clause, and it is not hypothetical.

**I1. Stage explicit paths, never `git add -A`.**
*Because:* other sessions may share this working tree, and `-A` sweeps a parallel session's uncommitted work into an unrelated commit.

**I2. Never truncate output you have not read.**
Redirect to a file, then read the file.
*Because:* a `tail -80` on a long run discards the headline results, which then have to be reconstructed from secondary output — if they can be at all.

**I3. Check `git status` at the start of a documentation or repo-structure task, and flag anything uncommitted before assuming the working tree matches the last commit.**
*Because:* four reference docs, a `design-decisions.md` rewrite recording two finished features, and the entire `docs/superpowers/` design/plan archive sat uncommitted across multiple sessions here, undetected until this exact reorganization task surfaced them.
