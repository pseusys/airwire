# Coding guidelines

*keywords:* style, lint, flake8, black, mypy, flutter_lints, eslint, prettier, imports, type hints, magic numbers, line length

How code is written here, per language.
Workflow rules — what to edit, when to abstract, what to re-run — are in [`dos-and-donts.md`](dos-and-donts.md); this file is about the code itself.

## Everywhere

- **Generate nothing that is not used.**
  No functions, constants, variables, types or traits that nothing calls.
- **Comments describe the code, never how it came to be.**
  No notes about the generation process, no "updated to handle X", no changelog in a docstring.
  History goes in [`../CHANGELOG.md`](../CHANGELOG.md), reasoning in `memory/`.
- **One documentation comment per file, per type, per function.**
  Not per line, and it points at `memory/` for the why.
- **No backward-compatibility or migration code**, unless it is explicitly asked for.
  Delete the old path in the same commit as the new one.
- **Named constants instead of magic numbers.**
  A literal that appears in a comparison, or twice anywhere, is a constant that has not been named yet.
- **Imports at the top of the file, never inline.**
  Import individual names rather than modules, and refer to them directly rather than by a fully-qualified path.
- **Prefer importing over invoking.**
  When one file in this project needs another, import it; do not shell out to it, re-exec it, or read its output.
- **Prefer long lines to broken ones**, wherever the linter does not specifically enforce otherwise.
  The exception is markdown, which is one sentence per line — see [`dos-and-donts.md`](dos-and-donts.md).
- **Test code lives in its own tree, mirroring the source tree — except `web-demo/`.**
  `core/tests/` mirrors `core/sources/`; `client/*/test/` mirrors `client/*/lib/`; test-only helpers never sit in the sources they exercise.
  `web-demo/`'s `*.spec.ts` files are the one deliberate exception, co-located next to the file they test (`arithmetic.ts`/`arithmetic.spec.ts`) — the idiomatic Angular CLI convention, already established before this rule was written down, not overridden here.
- **Do not embed generated content in code.**
  Configuration, environment files and fixtures live as separate template files, not as string literals inside a program.

## Two implementations that must be kept in sync

`core/sources/{arithmetic,markov,synthesis,textures}.py` (the real protocol) and
`web-demo/src/app/core/{arithmetic,markov,synthesis,textures}.ts` (the standalone demo port) mirror
each other's encode/decode walk.
Change one, change the other in the same commit.
The one deliberate exception: the demo's PRNG (`web-demo/src/app/core/prng.ts`) is *not* required to
be bit-exact with Python's `random`/`numpy.random` — each side only needs to round-trip with itself,
not produce identical output cross-language.
See [`wire-protocol.md`](wire-protocol.md) for why.

## Python

Real project code lives in `core/`; `memory/scripts/` is separate tooling with its own lint config (see below).

- **Concurrency is written with `async`, not threads**, unless the workload is genuinely CPU-bound.
- **Type hints wherever the language allows them.**
- **`from module import name`, not `import module`**, so call sites read as the name and not the path.
  Standard-library imports follow the same rule, and go at the top with everything else.
  The one deliberate exception: an optional, heavy dependency gated behind a `pyproject.toml` extra (`markovify` in `scripts/model.py`, `grpc_tools` in `scripts/process.py`, both `devel`-only) is imported inside the one function that needs it, so importing the module itself doesn't force that extra to be installed.
- **Constants at module level, in `UPPER_SNAKE_CASE`**, above the first function.
- **`pathlib.Path` for all filesystem access, never `os.path` or a bare `open()` on a string path.**
  A `Path` composes with `/` instead of nested `join()` calls, and its methods (`.exists()`, `.open()`, `.iterdir()`, `.read_text()`) read as an operation on the path rather than a free function that happens to take one as an argument.
  Already the house style throughout `core/`; enforced by ruff's `PTH` rules in `memory/scripts/`, advisory only in `core/` since `flake8` has no equivalent plugin installed.
- **Linted with `flake8` + `black` + `mypy --strict`**, all three run together by
  [`core/scripts/codestyle.py`](../core/scripts/codestyle.py) — not `ruff`.
  `flake8` selects `E`/`W`/`F` with `E24`, `W503`, `E203` ignored (`E203` conflicts with `black`);
  both `flake8` and `black` use a 200-character line length; `mypy` runs `--strict
  --ignore-missing-imports --explicit-package-bases`.
  Generated protobuf bindings (`*_pb2*`), dunder files, and anything under a dot-directory are
  excluded.

## Dart

- **`client/` is a pub workspace** (`client/pubspec.yaml`) with two member packages: `client/app`
  (Flutter Web) and `client/medium` (pure Dart, no Flutter dependency).
- **`client/app` is linted with `flutter_lints`** (`client/app/analysis_options.yaml`, default
  Flutter rule set, `build/**`/`web/**` excluded from analysis).
- **`client/medium` is linted with `lints/recommended`** (`client/medium/analysis_options.yaml`) —
  plain Dart rules, not Flutter-specific, since this package has no Flutter dependency.
- **Both packages' tests and lint run in CI** — [`../.github/workflows/client.yml`](../.github/workflows/client.yml),
  triggered on any push/PR touching `client/**`.

## TypeScript / Angular (`web-demo/`)

- **Linted with `angular-eslint`** (`web-demo/eslint.config.js`, pinned to the `@19` major to match this project's Angular 19 — `ng add`'s default installs `@22`, which warns/refuses to run against a v19 workspace).
- TypeScript compiler strictness (`strict: true`, `noImplicitOverride`, `noPropertyAccessFromIndexSignature`, `web-demo/tsconfig.json`) applies on top.
- **Karma + Jasmine** for tests (`ng test`), Angular CLI v19 for build/serve.

## Markdown

- **One sentence per line, no hard wrapping.**
- **Linted with `markdownlint` and `verify_memory.py`.**
  The full rule set and the reasoning behind it are in [`dos-and-donts.md`](dos-and-donts.md).

## GitHub Actions

Three workflows exist today: [`../.github/workflows/core.yml`](../.github/workflows/core.yml) (lint + test `core/` on a Python 3.11/3.12 matrix, trains the Markov corpus, runs example demo invocations), [`../.github/workflows/web-demo.yml`](../.github/workflows/web-demo.yml) (builds `web-demo/` against freshly-trained models, lints and runs its Karma suite, deploys to GitHub Pages on push to `main`), and [`../.github/workflows/client.yml`](../.github/workflows/client.yml) (lint + test both `client/` packages).

- **Scope with `paths`.**
  All three workflows already do this — a change that cannot affect a workflow's outcome should not trigger it.
- **`runs-on: ubuntu-latest`**, matching all three.

## Linters

| Language | Tool | Config | Command |
| --- | --- | --- | --- |
| Python (`core/`) | `flake8`, `black`, `mypy` | inline in [`../core/scripts/codestyle.py`](../core/scripts/codestyle.py) | `poetry poe lint` (from `core/`) |
| Python (`memory/scripts/`) | `ruff` | [`scripts/ruff.toml`](scripts/ruff.toml) | `ruff check --config memory/scripts/ruff.toml memory/scripts/` |
| Dart (`client/app`) | `flutter_lints` | `client/app/analysis_options.yaml` | `flutter analyze` (from `client/app`) |
| Dart (`client/medium`) | `lints/recommended` | `client/medium/analysis_options.yaml` | `dart analyze` (from `client/medium`) |
| TypeScript (`web-demo/`) | `angular-eslint@19` | `web-demo/eslint.config.js` | `npx ng lint` (from `web-demo/`) |
| Markdown | `markdownlint`, `verify_memory.py` | [`../.markdownlint.jsonc`](../.markdownlint.jsonc) | `python memory/scripts/verify_memory.py --strict` |

`core/`'s Python and `memory/scripts/`'s Python are deliberately linted by two different tools, not
merged into one config: `core/`'s `flake8`+`black`+`mypy --strict` pipeline predates this knowledge
base and is stricter than `memory/scripts/`'s tiny automation scripts need.

## Enforcing this — the worked example

[`memory/scripts/`](scripts/) is linted by the rules above, and is the demonstration that they hold
on real code rather than only in this document.

```bash
ruff check --config memory/scripts/ruff.toml memory/scripts/
```

[`scripts/ruff.toml`](scripts/ruff.toml) selects rules that map to the guidelines above rather than
a generic preset: `PLR2004` is "named constants", `PLC0415` is "imports at the top", `PTH` is
"pathlib over os.path", `ANN` is "type
hints", `I` is import ordering.
