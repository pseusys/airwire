# Odnoklassniki prototype (Track 1) — design

> **Status:** approved design, ready for implementation planning.
> **Relationship to other docs:** implements the required section of
> [medium-interface.md](../../medium-interface.md) for Odnoklassniki, informed by the OAuth findings
> in [medium-candidates.md](../../medium-candidates.md). Deliberately **does not** depend on the
> protocol spec's crypto layer ([messaging-protocol-design.md](2026-08-27-messaging-protocol-design.md))
> or on the three approved-but-unexecuted `protocol/` Dart plans
> (`2026-08-30-protocol-core-dart.md`, `2026-08-30-handshake-dart.md`, `2026-08-31-key-rotation-dart.md`)
> — see Scope below.

## Purpose

Prove that airwire can really talk to Odnoklassniki from a Flutter Web app — real OAuth login, real
`graph.user.messages` send/receive between two accounts — before any encryption is layered on top.
This is the first hands-on test of the riskiest untested assumptions from `medium-candidates.md`:
that VK ID's OAuth 2.1+PKCE flow works from a pure-Dart client with no backend secret, and that
`graph.user.messages` actually permits sending/receiving as documented.

## Scope

**In scope (this plan, "Track 1"):**
- A Flutter Web app shell (BLoC state management) with a login screen and a single conversation screen.
- Odnoklassniki/VK ID login via OAuth 2.1 + PKCE, implemented natively in Dart (no JS SDK, no backend).
- A medium wrapper implementing the **required** section of `medium-interface.md` (`my_id`, `send`,
  `receive`, `max_message_size`) against the real Graph API, sending and receiving **plaintext**.
- A full send/receive test loop between two real accounts that are already contacts (see Risks).

**Explicitly out of scope, deferred to "Track 2" (a separate, later plan):**
- Everything in the protocol spec — envelope/fragmentation, disguise encodings, handshake, key
  rotation. The three already-approved Dart plans for this remain unexecuted; Track 2 will execute
  them and then wire the medium wrapper's raw byte transport through that layer.
- Mobile/desktop targets (Track 1 is web-only — VK ID redirect handling and token storage both use
  browser-specific APIs).
- Any optional `medium-interface.md` capability (attachments, discovery, hygiene/`deleteMessage`).
- Retry/backoff, multi-conversation UX, offline support — anything beyond proving the loop works once.

## Repo layout

One new top-level directory, `client/`, holding all Dart/Flutter code — parallel to the existing
`core/` (Python). Structured as a [Dart pub
workspace](https://dart.dev/tools/pub/workspaces) (Dart 3.6+): a root `pubspec.yaml` with
`resolution: workspace`, member packages each with their own `pubspec.yaml` and `resolution:
workspace`, resolved together from one `flutter pub get` at the root with a single shared lockfile.

```
client/
  pubspec.yaml          # workspace root, resolution: workspace
  medium/                # pure(ish) Dart package
    pubspec.yaml
    lib/
  app/                    # Flutter Web app
    pubspec.yaml
    lib/
  # protocol/ added later, by Track 2 — not created in this plan
```

`protocol/` is not created by this plan. Leaving it out (rather than stubbing it) keeps Track 1 honest
about not depending on it; Track 2 adds it as a sibling workspace member when that work starts.

## Architecture

### `medium/` package

Defines the abstract medium contract from `medium-interface.md`'s required section as a Dart abstract
class, plus a concrete `OdnoklassnikiMedium` implementing it:

- **Own identity** — the authenticated user's OK.ru user ID, read via `users.getCurrentUser` after login.
- **Send/receive text** — `graph.user.messages`, bearer-token authenticated (confirmed via direct API
  doc fetch to need only `access_token`, no MD5 signature — the older `sig`-based scheme doesn't apply
  to this endpoint).
- **Size budget** — `max_message_size`, a fixed constant from Graph API docs (exact figure confirmed
  during implementation, not assumed here).

Also owns the OAuth 2.1+PKCE login flow, since token acquisition is intrinsically medium-specific:
generates `code_verifier`/`code_challenge` (RFC 7636, S256), redirects the browser to VK ID's
authorize endpoint, reads the `code`/`state` back from `Uri.base` after VK ID's redirect, exchanges
the code for an `access_token` via a direct HTTPS POST (`package:http`) — no client secret anywhere in
the flow, consistent with the PKCE research from `medium-candidates.md`.

Web-only for now: the redirect (`window.location`) and persistence both use browser-specific APIs
(via Hive, which uses IndexedDB on web). A future mobile/desktop medium would need custom-URL-scheme
redirect handling and platform secure storage instead — not designed here, since it's not needed yet.

### `app/` package (Flutter Web shell)

- **`AuthBloc`** — states `unauthenticated → redirecting → authenticated(accessToken) → error`. Calls
  into `OdnoklassnikiMedium`'s login methods; on startup, checks Hive for a saved token before
  deciding whether to show the login screen or go straight to the conversation screen.
- **`MessagingBloc`** — wraps `OdnoklassnikiMedium.send()`/`.receive()` for a single hardcoded
  conversation partner (the peer's OK.ru ID entered manually — `resolvePeerId`/contact-picker UX is an
  optional capability, out of scope). States: message list + a sending/error flag.
- **UI** — two screens: login (a button that kicks off the redirect) and conversation (message list +
  text field + send button). No navigation polish beyond switching between these two based on
  `AuthBloc` state.

### Storage

A single Hive box (`auth`) holds the PKCE `code_verifier` and `state` across the redirect round trip
(a full-page redirect wipes Dart memory, so these can't just live in a variable), and afterward the
`access_token` (and `refresh_token`, if VK ID issues one) so a page reload during development doesn't
force re-login every time. One storage mechanism for everything, rather than mixing in raw
`sessionStorage` calls.

## Data flow

**Login:** button tap → generate `code_verifier`/`code_challenge`/`state`, save to Hive → redirect
browser to VK ID authorize URL → VK ID redirects back to `/callback?code=...&state=...` → app reads
`Uri.base` on startup, finds a pending flow in Hive, validates `state`, exchanges `code` +
`code_verifier` for `access_token` via POST → save token to Hive → `AuthBloc` → `authenticated` →
`users.getCurrentUser` for `my_id` → route to conversation screen.

**Send:** text field submit → `MessagingBloc` → `OdnoklassnikiMedium.send(peerId, text)` → POST to
`graph.user.messages` with bearer token → append to local message list on success, error state on
failure.

**Receive:** poll `graph.user.messages` (simple timer-based poll is enough for a prototype — no
push/webhook infrastructure) → new messages appended to the local list, deduplicated by message ID.

## Error handling

Minimal, prototype-appropriate:
- OAuth errors (user denies consent at VK ID, `state` mismatch, token exchange fails) → `AuthBloc`
  `error` state, shown inline on the login screen with a retry button (restarts the flow from
  scratch).
- API errors (expired/invalid token, network failure, rate limit) → `MessagingBloc` error flag, shown
  inline; an expired token clears Hive's saved token and routes back to login rather than attempting
  silent refresh (silent refresh is real-implementation polish, not needed to prove the loop).
- No retry/backoff logic.

## Testing

- **Unit tests:** PKCE `code_verifier`/`code_challenge` generation against RFC 7636 test vectors;
  `OdnoklassnikiMedium`'s request/response parsing against mocked HTTP (`http`'s `MockClient`) for
  both the token exchange and `graph.user.messages` calls; `AuthBloc`/`MessagingBloc` state
  transitions via `bloc_test`.
- **Manual verification (not automatable):** the actual browser redirect to VK ID and back, and a
  real send/receive round trip between two accounts. This needs a real `app_id` and a registered
  redirect URI, both supplied by the user later — everything else in the plan can be built and
  unit-tested now against a placeholder `app_id`, with this as the final gating task.

## Risks / open unknowns

- **Cold-messaging permission gate (unconfirmed):** `medium-candidates.md` flagged that
  `graph.user.messages` might require the two accounts to already be in contact, similar to
  `group.isMessagesAllowed`-style checks elsewhere in the API. The manual test plan sidesteps this by
  using two accounts that are already OK.ru contacts of each other — if cold-messaging turns out to
  matter for the real product, that's a separate, later investigation.
- **Exact OAuth scope name for messaging** is not yet confirmed (VK ID's scope list wasn't checked in
  detail against `graph.user.messages` specifically) — resolved during implementation, not blocking
  design.
- **`app_id`/redirect URI** don't exist yet; the user will register these later. Placeholder config
  value until then.
