# airwire_medium

Pure Dart (no Flutter dependency) implementation of airwire's `Medium` transport contract, plus
the first real provider: Odnoklassniki, via VK ID OAuth 2.1+PKCE.
See [`../../memory/medium.md`](../../memory/medium.md) for the full contract definition and why
Odnoklassniki was chosen over MAX, VKontakte, Yandex Messenger, Telegram, ICQ, and TamTam.

## Contents

- `lib/src/medium.dart` — the `Medium` abstract contract (`send`/`receive`/`myId`/
  `maxMessageSize`/`dispose`) every provider wrapper implements.
- `lib/src/odnoklassniki_medium.dart` — `OdnoklassnikiMedium`: `graph.user.messages` send, polling
  receive, dedup by message ID.
- `lib/src/vk_id_oauth.dart` — VK ID OAuth 2.1 + PKCE client (`VkIdOAuth`).
- `lib/src/pkce.dart` — PKCE code verifier/challenge generation.
- `lib/src/auth_store.dart` — Hive-backed token storage (`AuthStore`).

## Setup

```bash
dart pub get   # resolves the whole client/ pub workspace (client/app included)
```

## Commands

```bash
dart test       # 5 test files
dart analyze    # lints/recommended
```

Both run in CI — see [`../../.github/workflows/client.yml`](../../.github/workflows/client.yml).
Full reference: [`../../memory/commands.md`](../../memory/commands.md).

## Used by

[`../app/`](../app/README.md), the Flutter Web app shell that wires this package's `Medium` into a
real login screen and conversation UI.
