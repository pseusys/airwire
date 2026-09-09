# Commands

*keywords:* commands, invocation, flags, entrypoint, rebuild, test command, poetry, poe, npm, flutter, dart

Every routine invocation, with the flags actually used.
[`../README.md`](../README.md) carries the short list for humans; this is the full reference agents copy from.
Three independent stacks, no shared prelude between them.

## `core/` (Python, Poetry)

```bash
cd core
poetry install --all-extras     # first-time setup: pynacl, protobuf, numpy, pillow + devel/codestyle extras
poetry poe generate             # protobuf codegen (sources/proto/*_pb2*) -- run after editing hyperchunk.proto
poetry poe train-stego-model    # trains the frozen Markov models (sources/data/markov_*.json, gitignored)
```

```bash
poetry poe test                 # pytest tests -- or: .venv/bin/python -m pytest tests
poetry poe lint                 # flake8 + black --check + mypy --strict, see coding-guidelines.md
poetry poe format               # black, modifies files in place
poetry poe demo --mode <plain|base64|markov|markov_rus|voronoi|...>   # end-to-end encode/decode smoke test
poetry poe demo-handshake       # handshake certificate exchange smoke test
```

## `client/` (Dart pub workspace: `app` + `medium`)

```bash
cd client/app && flutter pub get      # or: cd client/medium && dart pub get
```

```bash
cd client/app && flutter test         # 5 test files, runs in CI
cd client/app && flutter analyze      # flutter_lints, runs in CI
cd client/medium && dart test         # 5 test files, runs in CI
cd client/medium && dart analyze      # lints/recommended, runs in CI
```

## `web-demo/` (Angular 19, npm)

```bash
npm install                     # from web-demo/
npm run sync-models             # copies core/sources/data/markov_*.json into public/models/ -- run after training models
```

```bash
npm start                       # sync-models, then ng serve
npm run build                   # sync-models, then ng build
npx ng test --watch=false --browsers=ChromeHeadless   # Karma/Jasmine, run in CI
npx ng lint                     # angular-eslint@19, run in CI
```

## Checks

```bash
python memory/scripts/verify_memory.py   # docs: links, indexes, markdown rules
python memory/scripts/verify_memory.py --strict   # same, plus style warnings
```

Full test suites (`poetry poe test`, `npx ng test --watch=false --browsers=ChromeHeadless`,
`flutter test`, `dart test`) run in CI on every push/PR that touches their paths
(`.github/workflows/core.yml`, `.github/workflows/web-demo.yml`, `.github/workflows/client.yml`).

## Linting

```bash
poetry poe lint                                                # from core/ -- flake8 + black + mypy --strict
ruff check --config memory/scripts/ruff.toml memory/scripts/   # this knowledge base's own automation scripts
python memory/scripts/verify_memory.py --strict                # markdown house rules
flutter analyze                                                # from client/app
dart analyze                                                   # from client/medium
npx ng lint                                                    # from web-demo/
```

## Commands whose output is easy to misread

- **`poetry poe test`'s example `poe demo`/`demo-handshake` invocations** (part of the CI `test`
  job) are smoke tests, not the test suite — a green run there proves the CLI entrypoint didn't
  crash on a handful of hand-picked inputs, not that `pytest` passed. Both run in the same CI job;
  check which one actually failed.
- **`flutter pub get`/`dart pub get` silently rewriting `pubspec.lock`** against whatever
  Flutter/Dart SDK is installed locally is expected, not a sign something is broken — see this
  repo's own recent example in `CHANGELOG.md`.

## Platform notes

Three independent toolchains, no cross-project environment variable or activation step needed:
Python via a per-`core/` `.venv` + Poetry, Dart/Flutter via whatever's on `$PATH` (pinned via
`client/app/.metadata` to a specific Flutter `stable` revision), Node/npm for `web-demo/` (CI uses
Node 22).
