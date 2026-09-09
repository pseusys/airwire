# Knowledge base

*keywords:* memory, knowledge base, index, growing memory, new doc

Everything that would otherwise inflate `AGENTS.md`, `CHANGELOG.md` or a code docstring.
Start with [`../AGENTS.md`](../AGENTS.md) for orientation; come here for depth.

## Rules and routing

| File | What's in it |
| --- | --- |
| [`keywords.md`](keywords.md) | Which document to read when, keyed by the words that appear in a request. |
| [`dos-and-donts.md`](dos-and-donts.md) | House rules: workflow, doc conventions, evidence standards, what to re-run after a change. |
| [`coding-guidelines.md`](coding-guidelines.md) | How code is written here, per language, and the linter and config that enforce each set. |
| [`gotchas.md`](gotchas.md) | Platform and environment traps that have cost real debugging time. Empty so far. |

## The system

| File | What's in it |
| --- | --- |
| [`wire-protocol.md`](wire-protocol.md) | How a message is sliced into hyperslices, encrypted, disguised, chunked, sent and acknowledged — the lifecycle, data flow, and which file is the source of truth for current vs. target crypto behavior. |
| [`handshake.md`](handshake.md) | The session handshake and crypto scheme, both what's actually implemented (`core/sources/handshake.py`) and the not-yet-built target spec (directional keys, rotation), clearly separated. |
| [`medium.md`](medium.md) | The `Medium` transport contract, and which platforms implement, considered, or rejected it. |
| [`commands.md`](commands.md) | Every routine invocation, with the flags actually used, in pipeline order, per sub-project. |

## Tooling and operations

| File | What's in it |
| --- | --- |
| [`automation-scripts.md`](automation-scripts.md) | When to write a script instead of repeating a task, and the rules those scripts follow. |
| [`scripts/`](scripts/) | The scripts themselves. Start with `verify_memory.py`. |

## Decisions and history

| File | What's in it |
| --- | --- |
| [`rejected-ideas.md`](rejected-ideas.md) | Tested and rejected, with what would be needed to reopen. Check here before proposing. |
| [`changelog-archive/`](changelog-archive/) | Frozen `CHANGELOG-v*.md` from past releases. Grep here when a search of the live changelog turns up nothing. Empty so far — no release has happened yet. |

Step-by-step history for the current release is in [`../CHANGELOG.md`](../CHANGELOG.md).
Open work is in [`../TODO.md`](../TODO.md).

---

## Growing this knowledge base

The files above are the seed set.
Every project earns all of them, and none of them assumes anything about the domain.
**Everything else is created when it is needed, not before.**

There are no template files waiting to be filled in.
A stub still appears in this index and still gets opened, which teaches that the index is padding.

### When a fact earns a new file

A new file is justified when **all three** are true:

1. The fact is durable — it describes how things *are*, not what happened.
   What happened goes in `CHANGELOG.md`; what is open goes in `TODO.md`.
2. It has been re-derived twice, or cost more than an hour once.
3. It does not fit an existing file's scope.

Until all three hold, put it in the closest existing file — usually `gotchas.md` or `wire-protocol.md`.
Most projects run for months on the seed set alone.

### Files this project might grow into

Not a checklist: each row is a trigger that may never fire here.
When one does, create the file, answer the question in the third column, and add its rows to this index and to `keywords.md`.

| Create | When | The question it must answer |
| --- | --- | --- |
| `data-model.md` | Local message storage grows beyond what a paragraph can describe. | What is one record, in what units, and what does a rebuild invalidate? |
| `parameters.md` | The Tunables table in `wire-protocol.md` outgrows that file, or a live value differs from the repo default. | What is this set to right now, and where is that value read? |
| `dart-protocol.md` | `client/` gains its own protocol implementation (see `docs/superpowers/plans/` for the drafted design). | Does it match `core/`'s behavior, and if not, where and why? |
| `deployment.md` | A relay server or app store release actually ships. | What is the one deploy command, and what fails silently? |
| `external-apis.md` | A second medium provider (beyond Odnoklassniki) produces more than a couple of its own surprises. | What does this service do that its own documentation does not say? |
| `<subsystem>.md` | Explaining one component takes more than a paragraph **and** it can fail independently of the wire protocol. | What states does it have, and what does it do that nobody would infer from the code? |

The last row matters most: a decision rule written after seeing the result is the rule that result satisfies.

### Conventions every file here follows

- **A `*keywords:*` line** directly under the title, holding the symbols someone would grep.
  Same convention as `CHANGELOG.md`, so one search covers both.
- **Present tense only.**
  Dates and history belong in `CHANGELOG.md`.
- **Every rule carries its incident**, in a `*Because:*` clause.
- **Short.**
  One precise sentence beats three thorough ones.
  Give a rule its reason only where the reason changes what someone does; cut restatements, second examples and closing aphorisms.
  When a file grows, look for what to delete before what to add.
- **One sentence per line**, and the rest of the markdown conventions in [`dos-and-donts.md`](dos-and-donts.md).
- **Rows in this index and in `keywords.md`**, added in the same commit as the file.

### When to split a file

Split when two of its sections answer questions asked by different people at different times.
Length alone is a weak signal; two audiences is a strong one.
Past roughly 150 lines, look for the cut — or for the padding.

### When to delete a file

If a file has been empty, or unopened, for a month, delete it and its two index rows.
Git has the history, and the criteria above will tell you if it is earned again.
