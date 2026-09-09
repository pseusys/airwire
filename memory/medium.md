# Medium — the transport abstraction and which platforms implement it

*keywords:* Medium, transport, Odnoklassniki, OK.ru, VK ID, OAuth, PKCE, send, receive, maxMessageSize

A "medium" is a pluggable transport a conversation runs over — SMS, a web relay, or (implemented
first) an OAuth-delegated messaging platform.
The protocol's own confidentiality and disguise (see [`wire-protocol.md`](wire-protocol.md),
[`handshake.md`](handshake.md)) don't depend on anything about the medium's own privacy properties —
a medium only needs to move bytes reliably enough, at a workable size, between two identified users.

## The contract

`client/medium/lib/src/medium.dart` implements exactly this, required capabilities only:

```dart
abstract class Medium {
  String get myId;
  int get maxMessageSize;
  Future<void> send(String peerId, String text);
  Stream<(String peerId, String text)> receive();
  void dispose();
}
```

`receive()` is a general inbox across all known conversations, not scoped to one peer.
`dispose()` releases whatever `receive()` held open (poll timers, stream controllers) — callers that
use `receive()` must call it when done (e.g. on logout), or background polling keeps running against
a possibly-stale credential.

Optional capabilities a wrapper *may* additionally support, not required by the contract above:
attachments, presence/read receipts, contact discovery. None of these are implemented today; adding
one means extending this contract, which is a decision for whoever needs it, not a silent addition.

Out of scope for every medium, by design: voice calls, presence, read receipts — the protocol has no
concept of any of these.

## Providers

| Provider | Status | Notes |
| --- | --- | --- |
| Odnoklassniki (OK.ru) | **Implemented** — `client/medium/lib/src/odnoklassniki_medium.dart` | OAuth-delegated (`graph.user.messages`), real-user-scoped, richest attachment support of the platforms evaluated. VK ID OAuth 2.1+PKCE (`vk_id_oauth.dart`), Hive-backed token storage (`auth_store.dart`). |
| MAX (VK's current flagship) | Not implemented | Fast-growing, but bot registration requires a verified Russian legal entity (Sept 2025+) — a "who's allowed to develop" blocker independent of end-user onboarding. |
| VKontakte (vk.com) | Not implemented | Community tokens only for sending (`messages.send` locked to user tokens since 2019-03-01) — every bot-sent message is visibly from a community, never a person; also can't message a user first without prior contact. |
| Yandex Messenger | Rejected — see [`rejected-ideas.md`](rejected-ideas.md) | Bot API confined to Yandex 360 Business orgs, structurally cannot reach an arbitrary external user. |
| Telegram | Rejected — see [`rejected-ideas.md`](rejected-ideas.md) | Deprioritized on design grounds, not a technical blocker. |
| ICQ, TamTam | Not applicable | Both fully shut down (ICQ June 2024, TamTam February 2026); no API left to evaluate. |

Odnoklassniki was chosen because it's the only evaluated platform offering real OAuth-delegated,
real-user-scoped messaging without a Terms-of-Service conflict — see the "three different meanings
of acting as a real user" distinction in the rejected candidates for why that mattered more than raw
reach.

## Known gaps in the Odnoklassniki implementation

Three things remain unverified against the real API — all unit-testable-against-mocks work is done;
what's left needs a real registered VK ID app and a live login. See [`../TODO.md`](../TODO.md) C1.

- `client/app/lib/main.dart`'s `vkIdClientId` is a literal placeholder, not a registered app ID.
- The OAuth `scope` requested in `vk_id_oauth.dart`'s `buildAuthorizeUrl` (`'email'`) is not a real
  messaging permission — the correct scope name was never confirmed against VK ID's own scope list.
- Whether `graph.user.messages` requires the two accounts to already be OK.ru contacts before
  messaging cold is untested; `odnoklassniki_medium.dart` has no handling for this either way.
