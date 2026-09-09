# DOs and DON'Ts

*keywords:* coding standards, conventions, workflow, markdown, linting, evidence, pre-registration

House rules for working in this repo.
Most exist because breaking them has already cost something here.

---

## Code

These are the workflow rules — what to change and when.
How the code itself is written, per language, is in [`coding-guidelines.md`](coding-guidelines.md), along with the linter that enforces each set.

**DO prefer editing over adding.**
Extend an existing function rather than creating a new one, unless the abstraction is used in at least two places.

**DO delete code eagerly.**
Whenever a piece of code becomes obsolete, legacy, no longer used: it should be deleted.
Note, that deleting it does not mean removing it forever: the code will stay in git history and can be restored any time.

**DON'T abstract prematurely.**
Three similar lines beat a helper used once.

**DON'T add defensive padding.**
No error handling for scenarios that cannot happen.

**DON'T add comments to code you didn't touch.**
Add one only where the logic is genuinely non-obvious.

**DON'T leave backward-compatibility shims.**
Remove deleted code completely — no `# removed` markers, no re-exports, no `_old_` aliases.

**DO keep long narrative out of code.**
A docstring says what the thing does and points at `memory/` for why.
When you find yourself writing the third paragraph, it belongs in a doc file.

**DO run the cheap check after editing**, and the full suite before committing.
Both are in [`commands.md`](commands.md), along with the linter for each language.

**DO follow the development routine in [`../AGENTS.md`](../AGENTS.md)** for anything feature-sized: brainstorm the design, write the implementation plan, get it confirmed, then execute task by task — see AGENTS.md's Development routine for the actual sequence (this project uses the superpowers skill set, not an inline routine).

After every change, scan imports, function parameters and comments for staleness, and grep for symbols you deleted.

---

## Documentation

The docs are load-bearing, so they get linted like code.

**DO write one sentence per line.**
No hard wrapping at a column.
A changed sentence then produces a one-line diff instead of a reflowed paragraph.

**DO keep it short.**
One precise sentence beats three thorough ones.
Give a rule its reason only where the reason changes what someone does, and cut restatements, second examples and closing aphorisms.
When a doc grows, look for what to delete before what to add.

**DO keep the two indexes in sync with the files.**
Adding a `memory/` doc is three edits in one commit: the file, a row in [`README.md`](README.md), and a row in [`keywords.md`](keywords.md).
Deleting one is the same three in reverse.

**DO fold a shipped feature's `docs/superpowers/specs|plans/*.md` into `memory/`/`CHANGELOG.md` once it ships, and delete the original.**
The superpowers brainstorming/writing-plans skills are hardcoded to write new design specs and implementation plans there — that's fine as a staging area during design and implementation, but once a feature actually ships, its content belongs in `memory/` (current-state reasoning), `CHANGELOG.md` (what happened), and `rejected-ideas.md` (what was considered and rejected along the way), not left duplicated in a second, un-indexed location.
*Because:* this session found 6 already-shipped features' specs/plans still sitting in `docs/superpowers/` months after landing, alongside 3 genuinely-unexecuted Dart plans and one still-draft target-protocol spec — the first group needed retiring, the other two didn't, and nothing marked which was which.
Still-draft specs describing not-yet-implemented work (e.g. a target crypto scheme with no code behind it yet) are the one exception: absorbing them fully isn't earned until real implementation begins — keep them in place, and expand the relevant `memory/*.md` file only far enough to record the headline facts, not a full transcription (see `memory/handshake.md`'s "Target spec" section for the shape this takes).

**DO give every `memory/` doc a `*keywords:*` line** directly under its title, holding the symbols someone would grep.

**DO verify before committing a documentation change:**

```bash
python memory/scripts/verify_memory.py --strict
```

It checks links, both indexes, and the markdown rules below.
`--strict` matches what CI actually runs — a change that passes without it can still fail there.
`--fix` reflows any one-sentence-per-line violations in place before you check.
Structural problems fail the run; style problems warn unless you pass `--strict`.

The full rule set is in [`../.markdownlint.jsonc`](../.markdownlint.jsonc), for editors and for `markdownlint-cli2` if Node is available (it already is, for `web-demo/`).
It sets `default: true`, so a markdownlint upgrade can add a rule and fail a build that passed yesterday; that is intended, and the fix is to satisfy the new rule rather than to pin the old version.
`verify_memory.py` enforces the subset that matters with no dependencies at all.
The rules worth knowing without opening the config:

- ATX headings (`##`), never underlines
- table pipes padded with single spaces, delimiter rows written `| --- |`
- the `*keywords:*` label italic, the terms after it plain, so the line is not read as a heading
- fenced code blocks with backticks, always with a language tag
- dashes for bullets, two-space indent for nesting
- one blank line between blocks, never two
- no trailing whitespace, no tabs, newline at end of file
- no line-length limit, because sentences are the unit

---

## Evidence

**DO follow the internal rules in [`../AGENTS.md`](../AGENTS.md).**
They live there, next to the responding rules, so both are in the file every agent reads first.

**DO record rejections**, measured or on design grounds.
A tried-and-rejected idea goes in [`rejected-ideas.md`](rejected-ideas.md) with what was measured, so it is not re-argued six weeks later.

**DON'T report a change as working on the strength of the check you ran to build it.**
Name what would have failed if it were wrong, and run that.
This repo's own recent example: the seed-gating design for the Markov text disguise assumed decoding with the wrong seed could never raise an exception, only return corrupted bytes — reasoned from the code, not verified.
Running the actual test immediately falsified it (`candidate_ranges` can squeeze a real word out of its bit-range entirely at a narrow budget, and which word gets squeezed depends on candidate order).
Trust the test run, not the trace-through, for any claim about what a change makes possible or impossible.

This project measures some things quantitatively (round-trip byte efficiency, seam MSE for image
texture quality) but has no single headline metric — see `design-decisions.md`'s history in
[`CHANGELOG.md`](../CHANGELOG.md) for the shape a real measured comparison takes here (a control
value, an independent metric, more than one data point).
Don't invent a headline number where none has been chosen; state the specific thing that was
measured instead.

---

## Changing production behavior

**DO consider the blast radius.**
After any change, ask which of the three sub-projects it affects, and re-run only those:

1. `core/` — the real protocol implementation.
Changes here can affect `web-demo/`'s TypeScript port (see [`coding-guidelines.md`](coding-guidelines.md)'s mirrored-implementation rule) and, eventually, `client/`'s Dart port once one exists.
2. `web-demo/` — the standalone demo.
Changes here are isolated; nothing downstream depends on it.
3. `client/` — the Flutter app and its `medium` package.
Isolated from `core/` and `web-demo/` today; no shared code exists yet.

**DO check whether a config knob has a code reader** before relying on it.
None identified yet in this repo — no config knob here is currently known to be read by nothing.

There is no deployed product yet (see [`../TODO.md`](../TODO.md)'s status note) — only `web-demo/`
auto-deploys, to GitHub Pages, and it is a static demo with no persistent state to corrupt.
"Don't change production and measure at the same time" does not yet apply to anything in this repo.

---

## Working with the user

**DO chain long-running actions.**
Waiting on a permission prompt can cost hours.
Ask for the approved list to be extended when something you need is missing.

**DO write a script the second time you do a chore by hand.**
The rule and the conventions are in [`automation-scripts.md`](automation-scripts.md).

No secrets or environment-specific data exist in this repo yet — nothing here needs to be kept out
of a commit for that reason.
Revisit this section the first time one does.
