# airwire_app

Flutter Web prototype shell for airwire: VK ID / Odnoklassniki login, a conversation screen, and
the bloc wiring between them.
Not the finished product — see [`../../README.md`](../../README.md) for what airwire actually is,
and [`../../AGENTS.md`](../../AGENTS.md) for repo-wide orientation.

## What this is (and isn't) today

This app authenticates against Odnoklassniki via `airwire_medium` (the `../medium` package) and
sends/receives plain-text messages through it — real OAuth, real network calls, a real running
Flutter Web app. What it does **not** do yet: any of the actual airwire protocol.
Messages sent here are not encrypted, chunked, or disguised the way [`core/`](../../core/) already
implements — this shell wires up authentication and a chat UI first, ahead of that integration.
See [`../../TODO.md`](../../TODO.md) D6 for where that's tracked.

- `lib/auth/` — `AuthBloc`/`AuthEvent`/`AuthState`: VK ID OAuth login lifecycle.
- `lib/messaging/` — `MessagingBloc`/`MessagingEvent`/`MessagingState`: wraps `Medium.send`/`receive`.
- `lib/screens/` — `login_screen.dart`, `conversation_screen.dart`.
- `lib/app.dart`, `lib/main.dart` — app shell and entry point.

## Setup

```bash
flutter pub get   # resolves the whole client/ pub workspace (client/medium included)
```

## Commands

```bash
flutter test       # 5 test files
flutter analyze    # flutter_lints
flutter run -d chrome
```

Both run in CI — see [`../../.github/workflows/client.yml`](../../.github/workflows/client.yml).
Full reference: [`../../memory/commands.md`](../../memory/commands.md).

## Where to look next

- [`../../memory/medium.md`](../../memory/medium.md) — the `Medium` contract this app depends on,
  and why Odnoklassniki was chosen over the other platforms evaluated.
- [`../medium/README.md`](../medium/README.md) — the package that actually talks to Odnoklassniki.
