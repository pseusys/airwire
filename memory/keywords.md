# Keyword index — what to read, and when

*keywords:* keyword index, routing, triggers, when to read, what to read

A lookup from **the words that show up in a request** to **the documents that answer them**.

## How to use it

Scan the request for any trigger below, then read what it points to.
Match generously: triggers are stems and near-synonyms, not exact strings.
If two rows match, read both; if none do, read nothing extra and proceed.

## How to add a row

Every commit that adds, renames or deletes a `memory/` document updates this table in the same commit.
Three to six triggers per document; the words a user would say, including the failure phrasing and the synonyms you wouldn't have chosen yourself.

| Trigger words | Read |
| --- | --- |
| new idea, proposal, why don't we, have we tried, suggestion, improvement, medium, odnoklassniki, telegram, yandex, ok.ru | [`rejected-ideas.md`](rejected-ideas.md) |
| encoding, unicode, path, shell, venv, import error, works on my machine, crash on startup | [`gotchas.md`](gotchas.md) |
| how do I run, command, invocation, flags, rebuild, entrypoint, script to run, poe, npm, flutter, dart test | [`commands.md`](commands.md) |
| how does it work, why does it do that, hyperslice, hyperchunk, chunking, arithmetic coding, markov, texture synthesis, source of truth | [`wire-protocol.md`](wire-protocol.md) |
| handshake, TOFU, session key, rotation, directional key, bootstrap_key, obf_mode, X25519, post-quantum | [`handshake.md`](handshake.md) |
| medium, transport, send, receive, maxMessageSize, provider, which platform | [`medium.md`](medium.md) |
| workflow, commit, refactor, is this ok to change, review, evidence | [`dos-and-donts.md`](dos-and-donts.md) |
| style, lint, formatting, type hints, imports, naming, line length, flake8, black, mypy, flutter_lints, eslint | [`coding-guidelines.md`](coding-guidelines.md) |
| again, every time, repetitive, by hand, automate, script this | [`automation-scripts.md`](automation-scripts.md) |
| ci, workflow, github actions, pipeline, build failed, red build | [`coding-guidelines.md`](coding-guidelines.md) |
| when did this change, who changed, regression, it used to, history | [`../CHANGELOG.md`](../CHANGELOG.md) and [`changelog-archive/`](changelog-archive/) |
| what's next, roadmap, open work, what's left, backlog, not deployed | [`../TODO.md`](../TODO.md) |
