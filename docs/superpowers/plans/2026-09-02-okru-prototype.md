# Odnoklassniki Prototype (Track 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Flutter Web prototype that logs into Odnoklassniki via VK ID (OAuth 2.1 + PKCE, implemented natively in Dart, no client secret) and sends/receives real plaintext messages via `graph.user.messages` — proving the medium integration works before any encryption is layered on top.

**Architecture:** Two Dart packages under a new `client/` pub workspace: `medium/` (pure-ish Dart — the abstract `Medium` contract, PKCE, the VK ID OAuth client, and `OdnoklassnikiMedium`) and `app/` (Flutter Web — `AuthBloc` + `MessagingBloc`, a login screen, a conversation screen). `app/` depends on `medium/` via a path dependency; neither depends on the not-yet-built `protocol/` crypto package.

**Tech Stack:** Dart SDK `^3.6.0` (required for pub workspaces), Flutter `>=3.27.0`, `package:http`, `package:crypto`, `package:hive`, `package:flutter_bloc`, `package:bloc_test`. No code generation (no `build_runner`) — Hive boxes store plain `String`/`int` values under known keys, no custom `TypeAdapter`s needed.

## Global Constraints

- Dart SDK `^3.6.0` on every workspace member package (`client/pubspec.yaml` and each package's `pubspec.yaml`) — pub workspaces require this floor.
- No client secret anywhere in `medium/` or `app/` — VK ID's OAuth 2.1+PKCE flow is deliberately secret-free; if any step seems to need one, stop and reconsider rather than hardcoding one into client-side code.
- `medium/` has no Flutter dependency — it must build and test with plain `dart test`, matching the same constraint already established for the (separate, not-yet-built) `protocol/` package.
- Comments explain *why*, never *what* — omit the comment entirely if there's no non-obvious reason, constraint, or gotcha to record (repo comment style: WHY over WHAT, default to no comment). Most of this plan's classes are straightforward BLoC/UI boilerplate with nothing non-obvious to say; the doc comments that do appear in the task code below (on `AuthStore`, `OdnoklassnikiMedium`, etc.) mark the actual judgment calls and are the bar to match — don't add comments to simple classes just to have one.
- Dependency versions below are floors, not exact pins — if `pub get`/`flutter pub get` reports a resolution conflict (e.g. `bloc_test` vs `flutter_bloc`), loosen the newer package's constraint to match rather than downgrading the other.
- The following API facts were confirmed against live documentation/real SDKs during planning and can be trusted as-is: VK ID's authorize endpoint (`https://id.vk.ru/authorize`) and token endpoint (`https://id.vk.ru/oauth2/auth`) and their parameter names; the token response field names (`access_token`, `refresh_token`, `user_id`, `expires_in`); OK's Graph API send (`POST https://api.ok.ru/graph/me/messages`) and its request/response shape; OK's Graph API chat listing (`GET https://api.ok.ru/graph/me/chats`) and its response shape. Two facts were **not** confirmed and are called out at their point of use: the exact field name for identity in `GET https://api.ok.ru/graph/me`'s response, and whether `VALUABLE_ACCESS` alone is sufficient permission for messaging.

---

## Task 1: Workspace root + `medium/` package scaffolding

**Files:**
- Create: `client/pubspec.yaml`
- Create: `client/medium/pubspec.yaml`
- Create: `client/medium/analysis_options.yaml`
- Create: `client/medium/.gitignore`
- Create: `client/medium/lib/airwire_medium.dart`
- Test: `client/medium/test/airwire_medium_test.dart`

**Interfaces:**
- Produces: `mediumLibraryVersion` (a `String` constant), importable via `package:airwire_medium/airwire_medium.dart` — proves the workspace, the package, and `dart test` all work before any real logic is written.

- [ ] **Step 1: Write the failing test**

```dart
// client/medium/test/airwire_medium_test.dart
import 'package:airwire_medium/airwire_medium.dart';
import 'package:test/test.dart';

void main() {
  test('library exposes its version constant', () {
    expect(mediumLibraryVersion, equals('0.1.0'));
  });
}
```

- [ ] **Step 2: Create the workspace root manifest**

```yaml
# client/pubspec.yaml
name: _
publish_to: none
environment:
  sdk: ^3.6.0
workspace:
  - medium
```

- [ ] **Step 3: Create the `medium/` package manifest**

```yaml
# client/medium/pubspec.yaml
name: airwire_medium
description: Medium contract and Odnoklassniki wrapper for airwire.
version: 0.1.0
publish_to: none
environment:
  sdk: ^3.6.0
resolution: workspace

dependencies:
  http: ^1.2.0
  crypto: ^3.0.3
  hive: ^2.2.3

dev_dependencies:
  test: ^1.25.0
```

- [ ] **Step 4: Create `analysis_options.yaml` and `.gitignore`**

```yaml
# client/medium/analysis_options.yaml
include: package:lints/recommended.yaml
```

```gitignore
# client/medium/.gitignore
.dart_tool/
```

Note: `lints` isn't a declared dependency — add it if `dart analyze` complains it's missing; most Dart SDK installs bundle it transitively via `dart create` defaults, but declare `dev_dependencies: {lints: ^4.0.0}` explicitly if not.

- [ ] **Step 5: Create the library entrypoint**

```dart
// client/medium/lib/airwire_medium.dart
/// Current package version — bump alongside pubspec.yaml's `version:` field.
const mediumLibraryVersion = '0.1.0';
```

- [ ] **Step 6: Run `dart pub get` at the workspace root**

Run: `cd client && dart pub get`
Expected: resolves successfully, creates `client/pubspec.lock` and `client/.dart_tool/`.

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd client/medium && dart test`
Expected: PASS (1 test).

- [ ] **Step 8: Commit**

```bash
git add client/pubspec.yaml client/medium/
git commit -m "feat: scaffold client/ pub workspace and medium package"
```

---

## Task 2: PKCE code_verifier / code_challenge generation

**Files:**
- Create: `client/medium/lib/src/pkce.dart`
- Modify: `client/medium/lib/airwire_medium.dart` (export `src/pkce.dart`)
- Test: `client/medium/test/pkce_test.dart`

**Interfaces:**
- Produces: `String generateCodeVerifier()`, `String generateState()`, `String codeChallengeFor(String verifier)` — all pure functions, no I/O. Task 4 (VK ID OAuth client) calls these directly.

- [ ] **Step 1: Write the failing tests**

```dart
// client/medium/test/pkce_test.dart
import 'package:airwire_medium/airwire_medium.dart';
import 'package:test/test.dart';

void main() {
  group('codeChallengeFor', () {
    test('matches the RFC 7636 Appendix B test vector', () {
      // https://www.rfc-editor.org/rfc/rfc7636#appendix-B
      const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
      const expectedChallenge = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
      expect(codeChallengeFor(verifier), equals(expectedChallenge));
    });
  });

  group('generateCodeVerifier', () {
    test('produces a URL-safe string within RFC 7636 length bounds', () {
      final verifier = generateCodeVerifier();
      expect(verifier.length, inInclusiveRange(43, 128));
      expect(RegExp(r'^[A-Za-z0-9\-_]+$').hasMatch(verifier), isTrue);
    });

    test('produces a different value each call', () {
      expect(generateCodeVerifier(), isNot(equals(generateCodeVerifier())));
    });
  });

  group('generateState', () {
    test('produces a URL-safe, non-empty string', () {
      final state = generateState();
      expect(state, isNotEmpty);
      expect(RegExp(r'^[A-Za-z0-9\-_]+$').hasMatch(state), isTrue);
    });
  });
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd client/medium && dart test test/pkce_test.dart`
Expected: FAIL — `generateCodeVerifier`/`generateState`/`codeChallengeFor` undefined.

- [ ] **Step 3: Implement PKCE utilities**

```dart
// client/medium/lib/src/pkce.dart
import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';

/// A fresh 32-byte random token, base64url-encoded with padding stripped
/// (RFC 7636 requires the unpadded form). Shared by the verifier and state
/// generators since both just need an unguessable, URL-safe string.
String _randomUrlSafeToken() {
  final random = Random.secure();
  final bytes = List<int>.generate(32, (_) => random.nextInt(256));
  return base64Url.encode(bytes).replaceAll('=', '');
}

/// RFC 7636 `code_verifier`: generated fresh per login attempt, persisted
/// until the redirect comes back so it can be replayed in the token exchange.
String generateCodeVerifier() => _randomUrlSafeToken();

/// Anti-CSRF `state` value for the OAuth redirect round trip. Same shape as
/// the code verifier (any unguessable URL-safe string works) but kept as a
/// separate function since the two serve different purposes.
String generateState() => _randomUrlSafeToken();

/// RFC 7636 `code_challenge` (S256 method): base64url(SHA-256(verifier)),
/// padding stripped.
String codeChallengeFor(String verifier) {
  final digest = sha256.convert(ascii.encode(verifier));
  return base64Url.encode(digest.bytes).replaceAll('=', '');
}
```

- [ ] **Step 4: Export it from the package barrel**

```dart
// client/medium/lib/airwire_medium.dart
/// Current package version — bump alongside pubspec.yaml's `version:` field.
const mediumLibraryVersion = '0.1.0';

export 'src/pkce.dart';
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd client/medium && dart test test/pkce_test.dart`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add client/medium/lib/src/pkce.dart client/medium/lib/airwire_medium.dart client/medium/test/pkce_test.dart
git commit -m "feat: add PKCE code_verifier/code_challenge generation"
```

---

## Task 3: `AuthStore` — Hive-backed pending-flow and token storage

**Files:**
- Create: `client/medium/lib/src/auth_store.dart`
- Modify: `client/medium/lib/airwire_medium.dart` (export `src/auth_store.dart`)
- Test: `client/medium/test/auth_store_test.dart`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `class PendingFlow { String codeVerifier; String state; }`, `class VkTokens { String accessToken; String? refreshToken; String vkUserId; int expiresInSeconds; }`, `class AuthStore` with `static Future<AuthStore> open()`, `Future<void> savePendingFlow(PendingFlow)`, `PendingFlow? takePendingFlow()` (reads *and clears* — a flow is consumed exactly once), `Future<void> saveTokens(VkTokens)`, `VkTokens? loadTokens()`, `Future<void> clearTokens()`. Task 4 uses `PendingFlow`/`VkTokens`; Task 8 (`AuthBloc`) uses the rest.

- [ ] **Step 1: Write the failing tests**

```dart
// client/medium/test/auth_store_test.dart
import 'dart:io';

import 'package:airwire_medium/airwire_medium.dart';
import 'package:hive/hive.dart';
import 'package:test/test.dart';

void main() {
  late Directory tempDir;

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('airwire_auth_store_test');
    Hive.init(tempDir.path);
  });

  tearDown(() async {
    await Hive.deleteFromDisk();
    await tempDir.delete(recursive: true);
  });

  test('takePendingFlow returns null when nothing was saved', () async {
    final store = await AuthStore.open();
    expect(store.takePendingFlow(), isNull);
  });

  test('takePendingFlow returns and clears a saved flow', () async {
    final store = await AuthStore.open();
    await store.savePendingFlow(
      const PendingFlow(codeVerifier: 'verifier-1', state: 'state-1'),
    );

    final flow = store.takePendingFlow();
    expect(flow?.codeVerifier, equals('verifier-1'));
    expect(flow?.state, equals('state-1'));
    expect(store.takePendingFlow(), isNull);
  });

  test('loadTokens returns null when nothing was saved', () async {
    final store = await AuthStore.open();
    expect(store.loadTokens(), isNull);
  });

  test('saveTokens then loadTokens round-trips all fields', () async {
    final store = await AuthStore.open();
    await store.saveTokens(const VkTokens(
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      vkUserId: '12345',
      expiresInSeconds: 3600,
    ));

    final tokens = store.loadTokens();
    expect(tokens?.accessToken, equals('access-1'));
    expect(tokens?.refreshToken, equals('refresh-1'));
    expect(tokens?.vkUserId, equals('12345'));
    expect(tokens?.expiresInSeconds, equals(3600));
  });

  test('clearTokens removes saved tokens', () async {
    final store = await AuthStore.open();
    await store.saveTokens(const VkTokens(
      accessToken: 'access-1',
      refreshToken: null,
      vkUserId: '12345',
      expiresInSeconds: 3600,
    ));
    await store.clearTokens();
    expect(store.loadTokens(), isNull);
  });
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd client/medium && dart test test/auth_store_test.dart`
Expected: FAIL — `AuthStore`/`PendingFlow`/`VkTokens` undefined.

- [ ] **Step 3: Implement `AuthStore`**

```dart
// client/medium/lib/src/auth_store.dart
import 'package:hive/hive.dart';

/// PKCE state that must survive the full-page redirect to VK ID and back —
/// a page reload wipes Dart memory, so this has to live in storage between
/// the redirect-out and the callback.
class PendingFlow {
  const PendingFlow({required this.codeVerifier, required this.state});

  final String codeVerifier;
  final String state;
}

/// Tokens from a completed VK ID exchange. `vkUserId` is VK ID's own user
/// id (from the token response) — it is *not* assumed to equal OK's Graph
/// API identity; `OdnoklassnikiMedium.authenticate` resolves that separately
/// via `graph/me` rather than trusting this field for Graph API calls.
class VkTokens {
  const VkTokens({
    required this.accessToken,
    required this.refreshToken,
    required this.vkUserId,
    required this.expiresInSeconds,
  });

  final String accessToken;
  final String? refreshToken;
  final String vkUserId;
  final int expiresInSeconds;
}

/// Single Hive box holding both the in-flight PKCE state and, once login
/// completes, the access/refresh tokens — one storage mechanism for the
/// whole login lifecycle instead of mixing in raw browser storage calls.
class AuthStore {
  AuthStore._(this._box);

  final Box _box;

  static const _boxName = 'airwire_auth';

  static Future<AuthStore> open() async {
    final box = await Hive.openBox(_boxName);
    return AuthStore._(box);
  }

  Future<void> savePendingFlow(PendingFlow flow) async {
    await _box.put('pending_code_verifier', flow.codeVerifier);
    await _box.put('pending_state', flow.state);
  }

  /// Reads the pending flow and clears it — a flow is only ever replayed
  /// once, on the redirect immediately after it was saved.
  PendingFlow? takePendingFlow() {
    final verifier = _box.get('pending_code_verifier') as String?;
    final state = _box.get('pending_state') as String?;
    if (verifier == null || state == null) return null;
    _box.delete('pending_code_verifier');
    _box.delete('pending_state');
    return PendingFlow(codeVerifier: verifier, state: state);
  }

  Future<void> saveTokens(VkTokens tokens) async {
    await _box.put('access_token', tokens.accessToken);
    await _box.put('refresh_token', tokens.refreshToken);
    await _box.put('vk_user_id', tokens.vkUserId);
    await _box.put('expires_in_seconds', tokens.expiresInSeconds);
  }

  VkTokens? loadTokens() {
    final accessToken = _box.get('access_token') as String?;
    final vkUserId = _box.get('vk_user_id') as String?;
    if (accessToken == null || vkUserId == null) return null;
    return VkTokens(
      accessToken: accessToken,
      refreshToken: _box.get('refresh_token') as String?,
      vkUserId: vkUserId,
      expiresInSeconds: (_box.get('expires_in_seconds') as int?) ?? 0,
    );
  }

  Future<void> clearTokens() async {
    await _box.delete('access_token');
    await _box.delete('refresh_token');
    await _box.delete('vk_user_id');
    await _box.delete('expires_in_seconds');
  }
}
```

- [ ] **Step 4: Export it from the package barrel**

```dart
// client/medium/lib/airwire_medium.dart
export 'src/pkce.dart';
export 'src/auth_store.dart';

/// Current package version — bump alongside pubspec.yaml's `version:` field.
const mediumLibraryVersion = '0.1.0';
```

Note: `export` directives must appear before any other top-level declaration in a Dart file (a Dart syntax rule, not a style choice) — they go above `mediumLibraryVersion`, not below it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd client/medium && dart test test/auth_store_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add client/medium/lib/src/auth_store.dart client/medium/lib/airwire_medium.dart client/medium/test/auth_store_test.dart
git commit -m "feat: add Hive-backed AuthStore for PKCE state and tokens"
```

---

## Task 4: VK ID OAuth client — authorize URL, callback parsing, token exchange

**Files:**
- Create: `client/medium/lib/src/vk_id_oauth.dart`
- Modify: `client/medium/lib/airwire_medium.dart` (export `src/vk_id_oauth.dart`)
- Test: `client/medium/test/vk_id_oauth_test.dart`

**Interfaces:**
- Consumes: `VkTokens` from Task 3 (`auth_store.dart`).
- Produces: `class AuthorizeCallback { String code; String state; String deviceId; }`, `AuthorizeCallback? parseAuthorizeCallback(Uri uri)`, `class VkIdAuthException implements Exception { String message; }`, `class VkIdOAuth` with constructor `VkIdOAuth({required String clientId, required String redirectUri, http.Client? httpClient})`, `Uri buildAuthorizeUrl({required String codeChallenge, required String state})`, `Future<VkTokens> exchangeCode({required String code, required String deviceId, required String codeVerifier, required String state})`. Task 8 (`AuthBloc`) drives all of this.

**Confirmed API facts used here** (see Global Constraints): authorize at `https://id.vk.ru/authorize` (GET, query params `response_type=code`, `client_id`, `redirect_uri`, `code_challenge`, `code_challenge_method=S256`, `state`, `scope`); token exchange at `https://id.vk.ru/oauth2/auth` (POST, form-encoded, params `grant_type=authorization_code`, `client_id`, `code_verifier`, `state`, `code`, `device_id`, `redirect_uri`); the redirect callback carries `code`, `state`, and `device_id` as query params (VK ID assigns `device_id`, the client just has to capture and replay it — it does not generate one itself); the token response is JSON with fields `access_token`, `refresh_token`, `user_id`, `expires_in`.

- [ ] **Step 1: Write the failing tests**

```dart
// client/medium/test/vk_id_oauth_test.dart
import 'dart:convert';

import 'package:airwire_medium/airwire_medium.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  group('parseAuthorizeCallback', () {
    test('extracts code, state, and device_id when all present', () {
      final uri = Uri.parse(
        'https://app.example.com/callback?code=abc&state=xyz&device_id=dev-1',
      );
      final callback = parseAuthorizeCallback(uri);
      expect(callback?.code, equals('abc'));
      expect(callback?.state, equals('xyz'));
      expect(callback?.deviceId, equals('dev-1'));
    });

    test('returns null when a required param is missing', () {
      final uri = Uri.parse('https://app.example.com/callback?code=abc');
      expect(parseAuthorizeCallback(uri), isNull);
    });
  });

  group('VkIdOAuth.buildAuthorizeUrl', () {
    test('builds the exact expected authorize URL', () {
      final oauth = VkIdOAuth(
        clientId: 'test-client-id',
        redirectUri: 'https://app.example.com/callback',
      );
      final uri = oauth.buildAuthorizeUrl(
        codeChallenge: 'challenge-1',
        state: 'state-1',
      );

      expect(uri.scheme, equals('https'));
      expect(uri.host, equals('id.vk.ru'));
      expect(uri.path, equals('/authorize'));
      expect(uri.queryParameters['response_type'], equals('code'));
      expect(uri.queryParameters['client_id'], equals('test-client-id'));
      expect(
        uri.queryParameters['redirect_uri'],
        equals('https://app.example.com/callback'),
      );
      expect(uri.queryParameters['code_challenge'], equals('challenge-1'));
      expect(uri.queryParameters['code_challenge_method'], equals('S256'));
      expect(uri.queryParameters['state'], equals('state-1'));
    });
  });

  group('VkIdOAuth.exchangeCode', () {
    test('posts the correct body and parses a successful response', () async {
      late http.Request captured;
      final mockClient = MockClient((request) async {
        captured = request as http.Request;
        return http.Response(
          jsonEncode({
            'access_token': 'access-1',
            'refresh_token': 'refresh-1',
            'user_id': 12345,
            'expires_in': 3600,
          }),
          200,
        );
      });

      final oauth = VkIdOAuth(
        clientId: 'test-client-id',
        redirectUri: 'https://app.example.com/callback',
        httpClient: mockClient,
      );

      final tokens = await oauth.exchangeCode(
        code: 'auth-code-1',
        deviceId: 'dev-1',
        codeVerifier: 'verifier-1',
        state: 'state-1',
      );

      expect(captured.url.host, equals('id.vk.ru'));
      expect(captured.url.path, equals('/oauth2/auth'));
      expect(captured.method, equals('POST'));
      expect(captured.bodyFields['grant_type'], equals('authorization_code'));
      expect(captured.bodyFields['client_id'], equals('test-client-id'));
      expect(captured.bodyFields['code_verifier'], equals('verifier-1'));
      expect(captured.bodyFields['code'], equals('auth-code-1'));
      expect(captured.bodyFields['device_id'], equals('dev-1'));

      expect(tokens.accessToken, equals('access-1'));
      expect(tokens.refreshToken, equals('refresh-1'));
      expect(tokens.vkUserId, equals('12345'));
      expect(tokens.expiresInSeconds, equals(3600));
    });

    test('throws VkIdAuthException on a non-200 response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('server error', 500);
      });
      final oauth = VkIdOAuth(
        clientId: 'test-client-id',
        redirectUri: 'https://app.example.com/callback',
        httpClient: mockClient,
      );

      expect(
        () => oauth.exchangeCode(
          code: 'auth-code-1',
          deviceId: 'dev-1',
          codeVerifier: 'verifier-1',
          state: 'state-1',
        ),
        throwsA(isA<VkIdAuthException>()),
      );
    });

    test('throws VkIdAuthException when the response body has an error field', () async {
      final mockClient = MockClient((request) async {
        return http.Response(jsonEncode({'error': 'invalid_grant'}), 200);
      });
      final oauth = VkIdOAuth(
        clientId: 'test-client-id',
        redirectUri: 'https://app.example.com/callback',
        httpClient: mockClient,
      );

      expect(
        () => oauth.exchangeCode(
          code: 'auth-code-1',
          deviceId: 'dev-1',
          codeVerifier: 'verifier-1',
          state: 'state-1',
        ),
        throwsA(isA<VkIdAuthException>()),
      );
    });
  });
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd client/medium && dart test test/vk_id_oauth_test.dart`
Expected: FAIL — `VkIdOAuth`/`parseAuthorizeCallback`/`VkIdAuthException` undefined.

- [ ] **Step 3: Implement the VK ID OAuth client**

```dart
// client/medium/lib/src/vk_id_oauth.dart
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'auth_store.dart';

/// The three values VK ID appends to the redirect-back URL after a
/// successful login. `deviceId` is VK-assigned (not client-generated) and
/// must be replayed verbatim in the token exchange.
class AuthorizeCallback {
  const AuthorizeCallback({
    required this.code,
    required this.state,
    required this.deviceId,
  });

  final String code;
  final String state;
  final String deviceId;
}

/// Parses the `?code=...&state=...&device_id=...` query params VK ID adds
/// to the redirect URI. Takes a `Uri` rather than reading `Uri.base`
/// directly so this stays testable without a browser — the actual
/// `Uri.base` read happens at the call site in `app/`.
AuthorizeCallback? parseAuthorizeCallback(Uri uri) {
  final code = uri.queryParameters['code'];
  final state = uri.queryParameters['state'];
  final deviceId = uri.queryParameters['device_id'];
  if (code == null || state == null || deviceId == null) return null;
  return AuthorizeCallback(code: code, state: state, deviceId: deviceId);
}

class VkIdAuthException implements Exception {
  VkIdAuthException(this.message);

  final String message;

  @override
  String toString() => 'VkIdAuthException: $message';
}

/// OAuth 2.1 + PKCE client for VK ID (id.vk.ru), which OK/Odnoklassniki's
/// own OAuth has migrated under. No client secret is used anywhere — PKCE's
/// code_verifier is the only proof of possession, which is what makes this
/// safe to run entirely client-side.
class VkIdOAuth {
  VkIdOAuth({
    required this.clientId,
    required this.redirectUri,
    http.Client? httpClient,
  }) : _httpClient = httpClient ?? http.Client();

  final String clientId;
  final String redirectUri;
  final http.Client _httpClient;

  static const _host = 'id.vk.ru';

  Uri buildAuthorizeUrl({
    required String codeChallenge,
    required String state,
  }) {
    return Uri.https(_host, '/authorize', {
      'response_type': 'code',
      'client_id': clientId,
      'redirect_uri': redirectUri,
      'code_challenge': codeChallenge,
      'code_challenge_method': 'S256',
      'state': state,
      'scope': 'email',
    });
  }

  Future<VkTokens> exchangeCode({
    required String code,
    required String deviceId,
    required String codeVerifier,
    required String state,
  }) async {
    final response = await _httpClient.post(
      Uri.https(_host, '/oauth2/auth'),
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: {
        'grant_type': 'authorization_code',
        'client_id': clientId,
        'code_verifier': codeVerifier,
        'state': state,
        'code': code,
        'device_id': deviceId,
        'redirect_uri': redirectUri,
      },
    );

    if (response.statusCode != 200) {
      throw VkIdAuthException(
        'Token exchange failed with status ${response.statusCode}: ${response.body}',
      );
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    if (json.containsKey('error')) {
      throw VkIdAuthException('Token exchange rejected: ${json['error']}');
    }

    return VkTokens(
      accessToken: json['access_token'] as String,
      refreshToken: json['refresh_token'] as String?,
      vkUserId: (json['user_id'] as Object).toString(),
      expiresInSeconds: json['expires_in'] as int? ?? 0,
    );
  }
}
```

- [ ] **Step 4: Export it from the package barrel**

```dart
// client/medium/lib/airwire_medium.dart
export 'src/pkce.dart';
export 'src/auth_store.dart';
export 'src/vk_id_oauth.dart';

/// Current package version — bump alongside pubspec.yaml's `version:` field.
const mediumLibraryVersion = '0.1.0';
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd client/medium && dart test test/vk_id_oauth_test.dart`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add client/medium/lib/src/vk_id_oauth.dart client/medium/lib/airwire_medium.dart client/medium/test/vk_id_oauth_test.dart
git commit -m "feat: add VK ID OAuth 2.1+PKCE client"
```

---

## Task 5: `Medium` contract + `OdnoklassnikiMedium` identity and send

**Files:**
- Create: `client/medium/lib/src/medium.dart`
- Create: `client/medium/lib/src/odnoklassniki_medium.dart`
- Modify: `client/medium/lib/airwire_medium.dart` (export both)
- Test: `client/medium/test/odnoklassniki_medium_test.dart`

**Interfaces:**
- Consumes: nothing new from earlier tasks (constructed directly from an access token string — the app wires it to `AuthBloc`'s stored token in Task 8).
- Produces: `abstract class Medium { String get myId; int get maxMessageSize; Future<void> send(String peerId, String text); Stream<(String, String)> receive(); }`, `class OdnoklassnikiApiException implements Exception { String message; }`, `class OdnoklassnikiMedium implements Medium` with `static Future<OdnoklassnikiMedium> authenticate({required String accessToken, http.Client? httpClient})`, `String get myId`, `int get maxMessageSize`, `Future<void> send(String peerId, String text)`. `receive()` and `dispose()` are added in Task 6 — this task's `OdnoklassnikiMedium` is a valid, buildable, partial implementation with `receive()` deferred (documented, not stubbed with a placeholder — see Task 6).

**Confirmed API facts used here:** identity via `GET https://api.ok.ru/graph/me?access_token=...`; the exact response field name for the id was **not** confirmed by any source found during planning — the implementation below checks `uid`, then `id`, then `user_id` in that order, since `uid` is the field name the legacy REST API's `users.getCurrentUser` uses and Graph API fields have otherwise tracked REST field names closely. Send via `POST https://api.ok.ru/graph/me/messages?access_token=...` with JSON body `{"recipient": {"user_id": "user:<peerId>"}, "message": {"text": "..."}}`, response `{"success": [true], "chat_ids": [...]}`.

Because `OdnoklassnikiMedium` doesn't have a `receive()` method until Task 6, it isn't a complete `Medium` yet — declare it as `class OdnoklassnikiMedium` (not `implements Medium`) in this task, and switch to `implements Medium` in Task 6 once `receive()` exists. This keeps this task's code honest (nothing here pretends to satisfy an interface it doesn't yet fulfill) rather than stubbing `receive()` with a body that throws `UnimplementedError`.

- [ ] **Step 1: Write the failing tests**

```dart
// client/medium/test/odnoklassniki_medium_test.dart
import 'dart:convert';

import 'package:airwire_medium/airwire_medium.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  group('OdnoklassnikiMedium.authenticate', () {
    test('resolves myId from the uid field', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.host, equals('api.ok.ru'));
        expect(request.url.path, equals('/graph/me'));
        expect(request.url.queryParameters['access_token'], equals('token-1'));
        return http.Response(jsonEncode({'uid': '555000111'}), 200);
      });

      final medium = await OdnoklassnikiMedium.authenticate(
        accessToken: 'token-1',
        httpClient: mockClient,
      );

      expect(medium.myId, equals('555000111'));
    });

    test('falls back to id then user_id if uid is absent', () async {
      final mockClient = MockClient((request) async {
        return http.Response(jsonEncode({'user_id': 'user:555000111'}), 200);
      });

      final medium = await OdnoklassnikiMedium.authenticate(
        accessToken: 'token-1',
        httpClient: mockClient,
      );

      expect(medium.myId, equals('user:555000111'));
    });

    test('throws OdnoklassnikiApiException on a non-200 response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('forbidden', 403);
      });

      expect(
        () => OdnoklassnikiMedium.authenticate(
          accessToken: 'bad-token',
          httpClient: mockClient,
        ),
        throwsA(isA<OdnoklassnikiApiException>()),
      );
    });
  });

  group('OdnoklassnikiMedium.send', () {
    test('posts the correct request and succeeds on success:[true]', () async {
      late http.Request captured;
      final mockClient = MockClient((request) async {
        if (request.url.path == '/graph/me') {
          return http.Response(jsonEncode({'uid': 'me-1'}), 200);
        }
        captured = request as http.Request;
        return http.Response(
          jsonEncode({
            'success': [true],
            'chat_ids': ['chat:abc123'],
          }),
          200,
        );
      });

      final medium = await OdnoklassnikiMedium.authenticate(
        accessToken: 'token-1',
        httpClient: mockClient,
      );
      await medium.send('peer-1', 'hello there');

      expect(captured.url.host, equals('api.ok.ru'));
      expect(captured.url.path, equals('/graph/me/messages'));
      final body = jsonDecode(captured.body) as Map<String, dynamic>;
      expect(body['recipient']['user_id'], equals('user:peer-1'));
      expect(body['message']['text'], equals('hello there'));
    });

    test('throws OdnoklassnikiApiException when success is false', () async {
      final mockClient = MockClient((request) async {
        if (request.url.path == '/graph/me') {
          return http.Response(jsonEncode({'uid': 'me-1'}), 200);
        }
        return http.Response(
          jsonEncode({'success': [false]}),
          200,
        );
      });

      final medium = await OdnoklassnikiMedium.authenticate(
        accessToken: 'token-1',
        httpClient: mockClient,
      );

      expect(
        () => medium.send('peer-1', 'hello there'),
        throwsA(isA<OdnoklassnikiApiException>()),
      );
    });
  });

  test('maxMessageSize is a positive conservative default', () async {
    final mockClient = MockClient((request) async {
      return http.Response(jsonEncode({'uid': 'me-1'}), 200);
    });
    final medium = await OdnoklassnikiMedium.authenticate(
      accessToken: 'token-1',
      httpClient: mockClient,
    );
    expect(medium.maxMessageSize, equals(4096));
  });
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd client/medium && dart test test/odnoklassniki_medium_test.dart`
Expected: FAIL — `OdnoklassnikiMedium`/`OdnoklassnikiApiException` undefined.

- [ ] **Step 3: Implement the `Medium` contract**

```dart
// client/medium/lib/src/medium.dart
/// The required capability contract from docs/medium-interface.md — every
/// medium wrapper (Odnoklassniki first) implements this. `receive()` is a
/// general inbox across all known conversations, not scoped to one peer.
abstract class Medium {
  String get myId;
  int get maxMessageSize;
  Future<void> send(String peerId, String text);
  Stream<(String peerId, String text)> receive();
}
```

- [ ] **Step 4: Implement `OdnoklassnikiMedium` (identity + send)**

```dart
// client/medium/lib/src/odnoklassniki_medium.dart
import 'dart:convert';

import 'package:http/http.dart' as http;

class OdnoklassnikiApiException implements Exception {
  OdnoklassnikiApiException(this.message);

  final String message;

  @override
  String toString() => 'OdnoklassnikiApiException: $message';
}

/// Odnoklassniki's Graph API wrapper. Constructed via [authenticate] rather
/// than a plain constructor because resolving `myId` requires a network
/// call — there is no meaningful zero-argument instance.
///
/// `receive()` is added in Task 6; until then this class intentionally does
/// not `implements Medium`, since it doesn't yet satisfy that contract.
class OdnoklassnikiMedium {
  OdnoklassnikiMedium._({
    required String accessToken,
    required String myId,
    required http.Client httpClient,
  })  : _accessToken = accessToken,
        _myId = myId,
        _httpClient = httpClient;

  final String _accessToken;
  final String _myId;
  final http.Client _httpClient;

  static const _apiHost = 'api.ok.ru';

  /// Fetches the authenticated user's own OK-space id via `graph/me`. Does
  /// *not* reuse VK ID's own `user_id` from the token response — that's a
  /// VK-space id, and whether it matches OK's Graph API id space is
  /// unconfirmed, so this resolves the OK-native id directly instead.
  ///
  /// The exact response field name wasn't confirmed during planning (see
  /// this task's header note) — checks `uid`, then `id`, then `user_id`.
  static Future<OdnoklassnikiMedium> authenticate({
    required String accessToken,
    http.Client? httpClient,
  }) async {
    final client = httpClient ?? http.Client();
    final response = await client.get(
      Uri.https(_apiHost, '/graph/me', {'access_token': accessToken}),
    );
    if (response.statusCode != 200) {
      throw OdnoklassnikiApiException(
        'Failed to resolve own identity: ${response.statusCode} ${response.body}',
      );
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    final myId = (json['uid'] ?? json['id'] ?? json['user_id'])?.toString();
    if (myId == null) {
      throw OdnoklassnikiApiException(
        'graph/me response had no recognizable id field: ${response.body}',
      );
    }

    return OdnoklassnikiMedium._(
      accessToken: accessToken,
      myId: myId,
      httpClient: client,
    );
  }

  String get myId => _myId;

  /// OK's documented limits didn't specify a message text length during
  /// planning — this is a conservative default, tightened based on real
  /// API error responses during the manual-verification task if needed.
  int get maxMessageSize => 4096;

  Future<void> send(String peerId, String text) async {
    final response = await _httpClient.post(
      Uri.https(_apiHost, '/graph/me/messages', {'access_token': _accessToken}),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'recipient': {'user_id': 'user:$peerId'},
        'message': {'text': text},
      }),
    );

    if (response.statusCode != 200) {
      throw OdnoklassnikiApiException(
        'Send failed: ${response.statusCode} ${response.body}',
      );
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    final success = json['success'] as List?;
    if (success == null || success.isEmpty || success.first != true) {
      throw OdnoklassnikiApiException('Send rejected: ${response.body}');
    }
  }
}
```

- [ ] **Step 5: Export both from the package barrel**

```dart
// client/medium/lib/airwire_medium.dart
export 'src/pkce.dart';
export 'src/auth_store.dart';
export 'src/vk_id_oauth.dart';
export 'src/medium.dart';
export 'src/odnoklassniki_medium.dart';

/// Current package version — bump alongside pubspec.yaml's `version:` field.
const mediumLibraryVersion = '0.1.0';
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd client/medium && dart test test/odnoklassniki_medium_test.dart`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add client/medium/lib/src/medium.dart client/medium/lib/src/odnoklassniki_medium.dart client/medium/lib/airwire_medium.dart client/medium/test/odnoklassniki_medium_test.dart
git commit -m "feat: add Medium contract and OdnoklassnikiMedium identity/send"
```

---

## Task 6: `OdnoklassnikiMedium.receive()` — polling across all known chats

**Files:**
- Modify: `client/medium/lib/src/odnoklassniki_medium.dart`
- Modify: `client/medium/test/odnoklassniki_medium_test.dart`

**Interfaces:**
- Consumes: `OdnoklassnikiMedium` from Task 5.
- Produces: `Stream<(String peerId, String text)> receive()`, `Future<void> pollOnce()` (the polling logic, exposed as a public method so tests can trigger a poll deterministically instead of waiting on a real `Timer`), `void dispose()`. After this task, `OdnoklassnikiMedium implements Medium`.

**Design note:** rather than requiring the app to already know a `chat_id` per peer, this polls `GET graph/me/chats` on every tick to discover all active chats, then polls `GET graph/me/messages?chat_id=...` for each one — this works regardless of who sent the first message, as long as a chat already exists (which the manual test's "two already-connected accounts" setup guarantees; see the design spec's Risks section). This is a real capability confirmed during planning (`graph.user.chats`), not scope creep — it happens to be no more complex to implement than a single-hardcoded-chat version.

**Confirmed API facts used here:** `GET https://api.ok.ru/graph/me/chats?access_token=...` returns `{"chats": [{"chat_id": "chat:...", "participants": {"user:ID": timestamp, ...}, ...}], "marker": "..."}`. `GET https://api.ok.ru/graph/me/messages?chat_id=...&access_token=...&count=...` returns `{"messages": [{"sender": {"user_id": "user:...", "name": "..."}, "message": {"text": "...", "mid": "..."}, "timestamp": ...}]}`.

- [ ] **Step 1: Write the failing tests (append to the existing file)**

```dart
// client/medium/test/odnoklassniki_medium_test.dart
// Add this import at the top alongside the existing ones:
import 'dart:async';

// Add this group at the end of main():
group('OdnoklassnikiMedium.receive / pollOnce', () {
  test('yields a new message from a chat with an unseen entry', () async {
    final mockClient = MockClient((request) async {
      if (request.url.path == '/graph/me') {
        return http.Response(jsonEncode({'uid': 'me-1'}), 200);
      }
      if (request.url.path == '/graph/me/chats') {
        return http.Response(
          jsonEncode({
            'chats': [
              {
                'chat_id': 'chat:abc123',
                'participants': {'user:me-1': 1000, 'user:peer-1': 1000},
              },
            ],
          }),
          200,
        );
      }
      if (request.url.path == '/graph/me/messages') {
        expect(request.url.queryParameters['chat_id'], equals('chat:abc123'));
        return http.Response(
          jsonEncode({
            'messages': [
              {
                'sender': {'user_id': 'user:peer-1'},
                'message': {'text': 'hi from peer', 'mid': 'mid:1'},
                'timestamp': 5000,
              },
            ],
          }),
          200,
        );
      }
      return http.Response('not found', 404);
    });

    final medium = await OdnoklassnikiMedium.authenticate(
      accessToken: 'token-1',
      httpClient: mockClient,
    );

    final events = <(String, String)>[];
    final subscription = medium.receive().listen(events.add);
    await medium.pollOnce();
    await Future<void>.delayed(Duration.zero);

    expect(events, equals([('peer-1', 'hi from peer')]));

    await subscription.cancel();
    medium.dispose();
  });

  test('does not re-yield a message already seen in an earlier poll', () async {
    var messagesRequestCount = 0;
    final mockClient = MockClient((request) async {
      if (request.url.path == '/graph/me') {
        return http.Response(jsonEncode({'uid': 'me-1'}), 200);
      }
      if (request.url.path == '/graph/me/chats') {
        return http.Response(
          jsonEncode({
            'chats': [
              {
                'chat_id': 'chat:abc123',
                'participants': {'user:me-1': 1000, 'user:peer-1': 1000},
              },
            ],
          }),
          200,
        );
      }
      if (request.url.path == '/graph/me/messages') {
        messagesRequestCount++;
        return http.Response(
          jsonEncode({
            'messages': [
              {
                'sender': {'user_id': 'user:peer-1'},
                'message': {'text': 'hi from peer', 'mid': 'mid:1'},
                'timestamp': 5000,
              },
            ],
          }),
          200,
        );
      }
      return http.Response('not found', 404);
    });

    final medium = await OdnoklassnikiMedium.authenticate(
      accessToken: 'token-1',
      httpClient: mockClient,
    );

    final events = <(String, String)>[];
    final subscription = medium.receive().listen(events.add);
    await medium.pollOnce();
    await medium.pollOnce();
    await Future<void>.delayed(Duration.zero);

    expect(messagesRequestCount, equals(2));
    expect(events, equals([('peer-1', 'hi from peer')]));

    await subscription.cancel();
    medium.dispose();
  });

  test('ignores messages sent by myself', () async {
    final mockClient = MockClient((request) async {
      if (request.url.path == '/graph/me') {
        return http.Response(jsonEncode({'uid': 'me-1'}), 200);
      }
      if (request.url.path == '/graph/me/chats') {
        return http.Response(
          jsonEncode({
            'chats': [
              {
                'chat_id': 'chat:abc123',
                'participants': {'user:me-1': 1000, 'user:peer-1': 1000},
              },
            ],
          }),
          200,
        );
      }
      if (request.url.path == '/graph/me/messages') {
        return http.Response(
          jsonEncode({
            'messages': [
              {
                'sender': {'user_id': 'user:me-1'},
                'message': {'text': 'my own message', 'mid': 'mid:1'},
                'timestamp': 5000,
              },
            ],
          }),
          200,
        );
      }
      return http.Response('not found', 404);
    });

    final medium = await OdnoklassnikiMedium.authenticate(
      accessToken: 'token-1',
      httpClient: mockClient,
    );

    final events = <(String, String)>[];
    final subscription = medium.receive().listen(events.add);
    await medium.pollOnce();
    await Future<void>.delayed(Duration.zero);

    expect(events, isEmpty);

    await subscription.cancel();
    medium.dispose();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd client/medium && dart test test/odnoklassniki_medium_test.dart`
Expected: FAIL — `receive`/`pollOnce`/`dispose` undefined.

- [ ] **Step 3: Implement `receive()`/`pollOnce()`/`dispose()`**

```dart
// client/medium/lib/src/odnoklassniki_medium.dart
// Add these imports at the top:
import 'dart:async';

import 'medium.dart';

// Change the class declaration:
class OdnoklassnikiMedium implements Medium {
  // ... existing constructor/fields/authenticate/myId/maxMessageSize/send unchanged ...

  StreamController<(String, String)>? _receiveController;
  Timer? _pollTimer;
  final Map<String, int> _lastSeenTimestamp = {};

  @override
  Stream<(String, String)> receive() {
    _receiveController ??= StreamController<(String, String)>.broadcast();
    _pollTimer ??= Timer.periodic(const Duration(seconds: 5), (_) => pollOnce());
    return _receiveController!.stream;
  }

  /// Runs one poll cycle: list active chats, then fetch unseen messages in
  /// each. Public (not private) so tests can trigger a deterministic poll
  /// instead of waiting on the real Timer.
  Future<void> pollOnce() async {
    final chatsResponse = await _httpClient.get(
      Uri.https(_apiHost, '/graph/me/chats', {'access_token': _accessToken}),
    );
    if (chatsResponse.statusCode != 200) return;

    final chatsJson = jsonDecode(chatsResponse.body) as Map<String, dynamic>;
    final chats = (chatsJson['chats'] as List?) ?? const [];

    for (final chat in chats.cast<Map<String, dynamic>>()) {
      final chatId = chat['chat_id'] as String?;
      final participants =
          (chat['participants'] as Map?)?.cast<String, dynamic>() ?? const {};
      final otherPeerId = participants.keys
          .map((k) => k.startsWith('user:') ? k.substring(5) : k)
          .firstWhere((id) => id != _myId, orElse: () => '');
      if (chatId == null || otherPeerId.isEmpty) continue;
      await _pollMessages(chatId, otherPeerId);
    }
  }

  Future<void> _pollMessages(String chatId, String peerId) async {
    final since = _lastSeenTimestamp[chatId] ?? 0;
    final response = await _httpClient.get(
      Uri.https(_apiHost, '/graph/me/messages', {
        'chat_id': chatId,
        'access_token': _accessToken,
        'count': '50',
      }),
    );
    if (response.statusCode != 200) return;

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    final messages = (json['messages'] as List?) ?? const [];
    var latest = since;

    for (final entry in messages.cast<Map<String, dynamic>>()) {
      final timestamp = (entry['timestamp'] as num?)?.toInt() ?? 0;
      if (timestamp <= since) continue;

      final senderId = ((entry['sender'] as Map?)?['user_id'] as String?)
          ?.replaceFirst('user:', '');
      final text = (entry['message'] as Map?)?['text'] as String?;
      if (senderId == null || senderId == _myId || text == null) continue;

      _receiveController?.add((peerId, text));
      if (timestamp > latest) latest = timestamp;
    }

    _lastSeenTimestamp[chatId] = latest;
  }

  void dispose() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _receiveController?.close();
    _receiveController = null;
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd client/medium && dart test test/odnoklassniki_medium_test.dart`
Expected: PASS (9 tests).

- [ ] **Step 5: Run the full `medium/` test suite**

Run: `cd client/medium && dart test`
Expected: PASS (all tests across all files in this package so far).

- [ ] **Step 6: Commit**

```bash
git add client/medium/lib/src/odnoklassniki_medium.dart client/medium/test/odnoklassniki_medium_test.dart
git commit -m "feat: add OdnoklassnikiMedium.receive() polling across known chats"
```

---

## Task 7: Flutter Web app scaffolding

**Files:**
- Create: `client/app/` (via `flutter create`)
- Modify: `client/app/pubspec.yaml`
- Modify: `client/pubspec.yaml` (add `app` to the workspace list)
- Create: `client/app/lib/main.dart`
- Test: `client/app/test/main_smoke_test.dart`

**Interfaces:**
- Consumes: `airwire_medium` package from Tasks 1-6, via a path dependency.
- Produces: a running Flutter Web app shell with a placeholder home screen. Tasks 8-11 replace the placeholder with real `AuthBloc`/`MessagingBloc`-driven screens.

- [ ] **Step 1: Scaffold the Flutter project**

Run (from the repo root):
```bash
cd client && flutter create --platforms web --org com.airwire --project-name airwire_app app
```
Expected: creates `client/app/` with the standard Flutter project layout (`lib/main.dart`, `web/`, `pubspec.yaml`, `analysis_options.yaml`, etc). This overwrites the default `lib/main.dart` — that's fine, it gets replaced in Step 4 below.

- [ ] **Step 2: Add `app` to the workspace root**

```yaml
# client/pubspec.yaml
name: _
publish_to: none
environment:
  sdk: ^3.6.0
workspace:
  - medium
  - app
```

- [ ] **Step 3: Edit the generated `pubspec.yaml`**

`flutter create` writes an `environment:` block without `resolution: workspace` and without the `medium`/`bloc` dependencies — add them:

```yaml
# client/app/pubspec.yaml
name: airwire_app
description: Airwire Flutter Web prototype shell.
version: 0.1.0
publish_to: none

environment:
  sdk: ^3.6.0
resolution: workspace

dependencies:
  flutter:
    sdk: flutter
  flutter_bloc: ^8.1.0
  airwire_medium:
    path: ../medium

dev_dependencies:
  flutter_test:
    sdk: flutter
  bloc_test: ^9.1.0
  flutter_lints: ^4.0.0

flutter:
  uses-material-design: true
```

(Keep whatever `flutter:`/asset entries `flutter create` already generated beyond `uses-material-design: true` — merge rather than overwrite if it added more.)

- [ ] **Step 4: Replace `lib/main.dart` with a placeholder shell**

```dart
// client/app/lib/main.dart
import 'package:flutter/material.dart';

void main() {
  runApp(const AirwireApp());
}

class AirwireApp extends StatelessWidget {
  const AirwireApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Airwire',
      home: Scaffold(
        appBar: AppBar(title: const Text('Airwire')),
        body: const Center(child: Text('Airwire prototype — coming online')),
      ),
    );
  }
}
```

- [ ] **Step 5: Write a smoke test**

```dart
// client/app/test/main_smoke_test.dart
import 'package:airwire_app/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('app shows the placeholder home screen', (tester) async {
    await tester.pumpWidget(const AirwireApp());
    expect(find.text('Airwire prototype — coming online'), findsOneWidget);
  });
}
```

Note: this import (`package:airwire_app/main.dart`) requires `lib/main.dart` to be reachable as a library — if `flutter create` didn't add a `library` name, Dart still allows importing `lib/main.dart` by its package path directly, so no extra step is needed.

- [ ] **Step 6: Run `flutter pub get` at the workspace root**

Run: `cd client && flutter pub get`
Expected: resolves both `medium` and `app` together; updates the shared `client/pubspec.lock`.

- [ ] **Step 7: Run the smoke test**

Run: `cd client/app && flutter test test/main_smoke_test.dart`
Expected: PASS (1 test).

- [ ] **Step 8: Commit**

```bash
git add client/pubspec.yaml client/app/
git commit -m "feat: scaffold Flutter Web app shell"
```

---

## Task 8: `AuthBloc`

**Files:**
- Create: `client/app/lib/auth/auth_event.dart`
- Create: `client/app/lib/auth/auth_state.dart`
- Create: `client/app/lib/auth/auth_bloc.dart`
- Test: `client/app/test/auth/auth_bloc_test.dart`

**Interfaces:**
- Consumes: `AuthStore`, `PendingFlow`, `VkTokens`, `VkIdOAuth`, `AuthorizeCallback`, `parseAuthorizeCallback`, `generateCodeVerifier`, `generateState`, `codeChallengeFor` from `medium/` (Tasks 2-4); `OdnoklassnikiMedium.authenticate` from Task 5.
- Produces: `class AuthBloc extends Bloc<AuthEvent, AuthState>` with events `AuthStarted`, `LoginRequested`, `AuthCallbackReceived(Uri uri)`, `LogoutRequested`; states `AuthInitial`, `AuthUnauthenticated`, `AuthRedirecting`, `AuthAuthenticated(OdnoklassnikiMedium medium)`, `AuthError(String message)`. Task 9 (login screen) dispatches `LoginRequested`/`AuthCallbackReceived` and watches these states; Task 10 (`MessagingBloc`) is constructed with the `OdnoklassnikiMedium` from `AuthAuthenticated`.

The redirect itself (`window.location.href = ...`) is the one piece of genuinely untestable browser glue — `AuthBloc` takes it as an injected `void Function(Uri) redirect` callback rather than calling `dart:html` directly, so the bloc's decision logic (which state to move to, what to persist) is fully unit-testable, and only a one-line function at the `main.dart` call site is untested (covered instead by Task 12's manual verification).

- [ ] **Step 1: Write the failing tests**

```dart
// client/app/test/auth/auth_bloc_test.dart
import 'package:airwire_app/auth/auth_bloc.dart';
import 'package:airwire_app/auth/auth_event.dart';
import 'package:airwire_app/auth/auth_state.dart';
import 'package:airwire_medium/airwire_medium.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hive/hive.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'dart:convert';
import 'dart:io';

void main() {
  late Directory tempDir;
  late AuthStore authStore;

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('auth_bloc_test');
    Hive.init(tempDir.path);
    authStore = await AuthStore.open();
  });

  tearDown(() async {
    await Hive.deleteFromDisk();
    await tempDir.delete(recursive: true);
  });

  MockClient successfulApiClient() => MockClient((request) async {
        if (request.url.path == '/oauth2/auth') {
          return http.Response(
            jsonEncode({
              'access_token': 'access-1',
              'refresh_token': 'refresh-1',
              'user_id': 999,
              'expires_in': 3600,
            }),
            200,
          );
        }
        if (request.url.path == '/graph/me') {
          return http.Response(jsonEncode({'uid': 'ok-user-1'}), 200);
        }
        return http.Response('not found', 404);
      });

  blocTest<AuthBloc, AuthState>(
    'emits Unauthenticated on AuthStarted when no tokens are stored',
    build: () => AuthBloc(
      authStore: authStore,
      oauth: VkIdOAuth(
        clientId: 'client-1',
        redirectUri: 'https://app.example.com/callback',
        httpClient: successfulApiClient(),
      ),
      httpClient: successfulApiClient(),
      redirect: (_) {},
    ),
    act: (bloc) => bloc.add(const AuthStarted()),
    expect: () => [isA<AuthUnauthenticated>()],
  );

  blocTest<AuthBloc, AuthState>(
    'LoginRequested saves a pending flow and emits Redirecting',
    build: () => AuthBloc(
      authStore: authStore,
      oauth: VkIdOAuth(
        clientId: 'client-1',
        redirectUri: 'https://app.example.com/callback',
        httpClient: successfulApiClient(),
      ),
      httpClient: successfulApiClient(),
      redirect: (_) {},
    ),
    act: (bloc) async {
      bloc.add(const LoginRequested());
      await bloc.stream.firstWhere((state) => state is AuthRedirecting);
    },
    expect: () => [isA<AuthRedirecting>()],
    verify: (_) {
      expect(authStore.takePendingFlow(), isNotNull);
    },
  );

  blocTest<AuthBloc, AuthState>(
    'AuthCallbackReceived with a valid callback exchanges the code and emits Authenticated',
    build: () => AuthBloc(
      authStore: authStore,
      oauth: VkIdOAuth(
        clientId: 'client-1',
        redirectUri: 'https://app.example.com/callback',
        httpClient: successfulApiClient(),
      ),
      httpClient: successfulApiClient(),
      redirect: (_) {},
    ),
    seed: () => const AuthRedirecting(),
    setUp: () async {
      // Must be awaited: Hive's real VM storage backend does genuine
      // multi-turn disk I/O, and bloc_test's setUp only waits for the
      // synchronous prefix of an un-awaited async closure — an un-awaited
      // savePendingFlow() here races the bloc's later takePendingFlow()
      // read and intermittently loses.
      await authStore.savePendingFlow(
        const PendingFlow(codeVerifier: 'verifier-1', state: 'state-1'),
      );
    },
    act: (bloc) async {
      bloc.add(
        AuthCallbackReceived(
          Uri.parse(
            'https://app.example.com/callback?code=abc&state=state-1&device_id=dev-1',
          ),
        ),
      );
      // bloc_test's default post-act wait is a single zero-duration tick,
      // too short for a handler that awaits several real Hive disk writes
      // before its only emit — wait for the actual terminal state instead.
      await bloc.stream.firstWhere((state) => state is AuthAuthenticated);
    },
    expect: () => [isA<AuthAuthenticated>()],
  );

  blocTest<AuthBloc, AuthState>(
    'AuthCallbackReceived with a mismatched state emits Error',
    build: () => AuthBloc(
      authStore: authStore,
      oauth: VkIdOAuth(
        clientId: 'client-1',
        redirectUri: 'https://app.example.com/callback',
        httpClient: successfulApiClient(),
      ),
      httpClient: successfulApiClient(),
      redirect: (_) {},
    ),
    seed: () => const AuthRedirecting(),
    setUp: () async {
      // See the note on the previous test — must be awaited for the same
      // real-disk-I/O reason, even though this test's two possible code
      // paths both end in AuthError, which happened to mask the race here.
      await authStore.savePendingFlow(
        const PendingFlow(codeVerifier: 'verifier-1', state: 'state-1'),
      );
    },
    act: (bloc) => bloc.add(
      AuthCallbackReceived(
        Uri.parse(
          'https://app.example.com/callback?code=abc&state=WRONG&device_id=dev-1',
        ),
      ),
    ),
    expect: () => [isA<AuthError>()],
  );

  blocTest<AuthBloc, AuthState>(
    'LogoutRequested clears tokens and emits Unauthenticated',
    build: () => AuthBloc(
      authStore: authStore,
      oauth: VkIdOAuth(
        clientId: 'client-1',
        redirectUri: 'https://app.example.com/callback',
        httpClient: successfulApiClient(),
      ),
      httpClient: successfulApiClient(),
      redirect: (_) {},
    ),
    // Seeded as AuthInitial, not AuthUnauthenticated: package:bloc's
    // Bloc.emit() silently no-ops when the emitted state equals the
    // current state, so seeding the same value the handler emits would
    // make this test pass or fail independent of whether logout actually
    // ran — AuthInitial guarantees the emit is a genuinely new value.
    seed: () => const AuthInitial(),
    setUp: () async {
      await authStore.saveTokens(const VkTokens(
        accessToken: 'access-1',
        refreshToken: 'refresh-1',
        vkUserId: '999',
        expiresInSeconds: 3600,
      ));
    },
    act: (bloc) async {
      bloc.add(const LogoutRequested());
      await bloc.stream.firstWhere((state) => state is AuthUnauthenticated);
    },
    expect: () => [isA<AuthUnauthenticated>()],
    verify: (_) {
      expect(authStore.loadTokens(), isNull);
    },
  );
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd client/app && flutter test test/auth/auth_bloc_test.dart`
Expected: FAIL — `AuthBloc` and friends undefined.

- [ ] **Step 3: Implement `AuthEvent`**

```dart
// client/app/lib/auth/auth_event.dart
import 'package:equatable/equatable.dart';

sealed class AuthEvent extends Equatable {
  const AuthEvent();

  @override
  List<Object?> get props => [];
}

class AuthStarted extends AuthEvent {
  const AuthStarted();
}

class LoginRequested extends AuthEvent {
  const LoginRequested();
}

class AuthCallbackReceived extends AuthEvent {
  const AuthCallbackReceived(this.uri);

  final Uri uri;

  @override
  List<Object?> get props => [uri];
}

class LogoutRequested extends AuthEvent {
  const LogoutRequested();
}
```

Note: this uses `package:equatable` for value-equality on events/states (needed for `blocTest`'s `expect` list to compare states meaningfully). Add it to `client/app/pubspec.yaml`'s `dependencies`: `equatable: ^2.0.5`. Re-run `flutter pub get` after adding it.

- [ ] **Step 4: Implement `AuthState`**

```dart
// client/app/lib/auth/auth_state.dart
import 'package:airwire_medium/airwire_medium.dart';
import 'package:equatable/equatable.dart';

sealed class AuthState extends Equatable {
  const AuthState();

  @override
  List<Object?> get props => [];
}

class AuthInitial extends AuthState {
  const AuthInitial();
}

class AuthUnauthenticated extends AuthState {
  const AuthUnauthenticated();
}

class AuthRedirecting extends AuthState {
  const AuthRedirecting();
}

class AuthAuthenticated extends AuthState {
  const AuthAuthenticated(this.medium);

  final OdnoklassnikiMedium medium;

  @override
  List<Object?> get props => [medium];
}

class AuthError extends AuthState {
  const AuthError(this.message);

  final String message;

  @override
  List<Object?> get props => [message];
}
```

- [ ] **Step 5: Implement `AuthBloc`**

```dart
// client/app/lib/auth/auth_bloc.dart
import 'package:airwire_medium/airwire_medium.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:http/http.dart' as http;

import 'auth_event.dart';
import 'auth_state.dart';

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  AuthBloc({
    required AuthStore authStore,
    required VkIdOAuth oauth,
    required http.Client httpClient,
    required void Function(Uri) redirect,
  })  : _authStore = authStore,
        _oauth = oauth,
        _httpClient = httpClient,
        _redirect = redirect,
        super(const AuthInitial()) {
    on<AuthStarted>(_onStarted);
    on<LoginRequested>(_onLoginRequested);
    on<AuthCallbackReceived>(_onCallbackReceived);
    on<LogoutRequested>(_onLogoutRequested);
  }

  final AuthStore _authStore;
  final VkIdOAuth _oauth;
  final http.Client _httpClient;
  final void Function(Uri) _redirect;

  Future<void> _onStarted(AuthStarted event, Emitter<AuthState> emit) async {
    final tokens = _authStore.loadTokens();
    if (tokens == null) {
      emit(const AuthUnauthenticated());
      return;
    }
    try {
      final medium = await OdnoklassnikiMedium.authenticate(
        accessToken: tokens.accessToken,
        httpClient: _httpClient,
      );
      emit(AuthAuthenticated(medium));
    } catch (_) {
      await _authStore.clearTokens();
      emit(const AuthUnauthenticated());
    }
  }

  Future<void> _onLoginRequested(
    LoginRequested event,
    Emitter<AuthState> emit,
  ) async {
    final verifier = generateCodeVerifier();
    final state = generateState();
    await _authStore.savePendingFlow(
      PendingFlow(codeVerifier: verifier, state: state),
    );
    final url = _oauth.buildAuthorizeUrl(
      codeChallenge: codeChallengeFor(verifier),
      state: state,
    );
    emit(const AuthRedirecting());
    _redirect(url);
  }

  Future<void> _onCallbackReceived(
    AuthCallbackReceived event,
    Emitter<AuthState> emit,
  ) async {
    final callback = parseAuthorizeCallback(event.uri);
    if (callback == null) {
      emit(const AuthError('Login callback was missing required parameters.'));
      return;
    }

    final pending = _authStore.takePendingFlow();
    if (pending == null) {
      emit(const AuthError('No login attempt was in progress.'));
      return;
    }
    if (pending.state != callback.state) {
      emit(const AuthError('Login state mismatch — possible CSRF, please retry.'));
      return;
    }

    try {
      final tokens = await _oauth.exchangeCode(
        code: callback.code,
        deviceId: callback.deviceId,
        codeVerifier: pending.codeVerifier,
        state: callback.state,
      );
      await _authStore.saveTokens(tokens);
      final medium = await OdnoklassnikiMedium.authenticate(
        accessToken: tokens.accessToken,
        httpClient: _httpClient,
      );
      emit(AuthAuthenticated(medium));
    } catch (error) {
      emit(AuthError('Login failed: $error'));
    }
  }

  Future<void> _onLogoutRequested(
    LogoutRequested event,
    Emitter<AuthState> emit,
  ) async {
    await _authStore.clearTokens();
    emit(const AuthUnauthenticated());
  }
}
```

- [ ] **Step 6: Add `equatable` and `hive`, then run the tests**

Add `equatable: ^2.0.5` to `client/app/pubspec.yaml`'s `dependencies`. Also add `hive: ^2.2.3` to `dev_dependencies` — production code in `app/` only ever touches Hive indirectly through `AuthStore`, but this test file calls `Hive.init()` directly to point Hive at a temp directory, which requires `hive` to be a direct (not just transitive-via-`medium/`) dependency of `app/`.

Run: `cd client && flutter pub get && cd app && flutter test test/auth/auth_bloc_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add client/app/pubspec.yaml client/app/lib/auth/ client/app/test/auth/
git commit -m "feat: add AuthBloc for VK ID login lifecycle"
```

---

## Task 9: Login screen

**Files:**
- Create: `client/app/lib/screens/login_screen.dart`
- Create: `client/app/lib/app.dart` (holds `AirwireApp` — see Step 5's note on why this can't live in `main.dart`)
- Modify: `client/app/lib/main.dart`
- Modify: `client/app/pubspec.yaml` (add `http` as a direct dependency, and `mocktail` for the test)
- Test: `client/app/test/screens/login_screen_test.dart`
- Test: `client/app/test/main_smoke_test.dart` (updated for `app.dart`)

**Interfaces:**
- Consumes: `AuthBloc`, `AuthEvent`, `AuthState` (and subtypes) from Task 8.
- Produces: `class LoginScreen extends StatelessWidget`; `class AirwireApp extends StatelessWidget` (in `client/app/lib/app.dart` — this is where Task 11 finds it, not `main.dart`). Wired so `LoginScreen` shows whenever `AuthBloc`'s state is `AuthUnauthenticated`, `AuthRedirecting`, or `AuthError`; `AuthAuthenticated` routes to the conversation screen (Task 11).

- [ ] **Step 1: Write the failing test**

```dart
// client/app/test/screens/login_screen_test.dart
import 'package:airwire_app/auth/auth_bloc.dart';
import 'package:airwire_app/auth/auth_event.dart';
import 'package:airwire_app/auth/auth_state.dart';
import 'package:airwire_app/screens/login_screen.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockAuthBloc extends MockBloc<AuthEvent, AuthState> implements AuthBloc {}

void main() {
  late MockAuthBloc authBloc;

  setUp(() {
    authBloc = MockAuthBloc();
  });

  Widget wrap(Widget child) => MaterialApp(
        home: BlocProvider<AuthBloc>.value(value: authBloc, child: child),
      );

  testWidgets('shows a login button when unauthenticated', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthUnauthenticated());
    await tester.pumpWidget(wrap(const LoginScreen()));

    expect(find.text('Log in with VK ID'), findsOneWidget);
  });

  testWidgets('tapping the login button dispatches LoginRequested', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthUnauthenticated());
    await tester.pumpWidget(wrap(const LoginScreen()));

    await tester.tap(find.text('Log in with VK ID'));
    verify(() => authBloc.add(const LoginRequested())).called(1);
  });

  testWidgets('shows a progress indicator while redirecting', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthRedirecting());
    await tester.pumpWidget(wrap(const LoginScreen()));

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('shows the error message when login failed', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthError('something broke'));
    await tester.pumpWidget(wrap(const LoginScreen()));

    expect(find.text('something broke'), findsOneWidget);
  });
}
```

Note: this needs `package:mocktail` for `MockAuthBloc`/`when`/`verify` (bloc_test's own `MockBloc` base class comes from `package:bloc_test`, but stubbing/verifying calls needs mocktail underneath).

- [ ] **Step 2: Add `mocktail` and run the test to verify it fails**

Add `mocktail: ^1.0.4` to `client/app/pubspec.yaml`'s `dev_dependencies`, then `cd client && flutter pub get`.

Run: `cd client/app && flutter test test/screens/login_screen_test.dart`
Expected: FAIL — `LoginScreen` undefined.

- [ ] **Step 3: Implement `LoginScreen`**

```dart
// client/app/lib/screens/login_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../auth/auth_bloc.dart';
import '../auth/auth_event.dart';
import '../auth/auth_state.dart';

class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Airwire')),
      body: Center(
        child: BlocBuilder<AuthBloc, AuthState>(
          builder: (context, state) {
            return switch (state) {
              AuthRedirecting() => const CircularProgressIndicator(),
              AuthError(:final message) => Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(message),
                    const SizedBox(height: 16),
                    _loginButton(context),
                  ],
                ),
              _ => _loginButton(context),
            };
          },
        ),
      ),
    );
  }

  Widget _loginButton(BuildContext context) {
    return ElevatedButton(
      onPressed: () => context.read<AuthBloc>().add(const LoginRequested()),
      child: const Text('Log in with VK ID'),
    );
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd client/app && flutter test test/screens/login_screen_test.dart`
Expected: PASS (4 tests).

- [ ] **Step 5: Create `AirwireApp` in its own file, then wire it into `main.dart`**

`AirwireApp` needs to live in a file with no `dart:html` import, separate from `main.dart`. Reason: `flutter test`'s default (non-deprecated) platform is VM-based and cannot compile `dart:html` at all, while the alternative (`--platform chrome`) cannot run `auth_bloc_test.dart` (needs `dart:io` for real Hive disk I/O, from Task 8) — the two requirements are mutually exclusive under a single `--platform` flag, so whichever file test code imports to reach `AirwireApp` must not drag in `dart:html` transitively. This mirrors the same pattern already used for `AuthBloc`'s injected `redirect: void Function(Uri)` callback — keep the actual browser call at the thinnest possible edge, never inside anything a test imports.

```dart
// client/app/lib/app.dart
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'auth/auth_bloc.dart';
import 'auth/auth_state.dart';
import 'screens/login_screen.dart';

class AirwireApp extends StatelessWidget {
  const AirwireApp({required this.authBloc, super.key});

  final AuthBloc authBloc;

  @override
  Widget build(BuildContext context) {
    return BlocProvider<AuthBloc>.value(
      value: authBloc,
      child: MaterialApp(
        title: 'Airwire',
        home: BlocBuilder<AuthBloc, AuthState>(
          builder: (context, state) {
            if (state is AuthAuthenticated) {
              // Replaced with ConversationScreen in Task 11.
              return const Scaffold(body: Center(child: Text('Logged in.')));
            }
            return const LoginScreen();
          },
        ),
      ),
    );
  }
}
```

`main.dart` keeps the `dart:html`-touching bootstrap logic and imports `AirwireApp` from `app.dart` — it also sets up the `AuthBloc`, the redirect callback, and reads `Uri.base` on startup to detect a VK ID callback. Real values (`app_id`, redirect URI) are placeholders here, filled in for real in Task 12.

```dart
// client/app/lib/main.dart
import 'dart:html' as html;

import 'package:airwire_medium/airwire_medium.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'app.dart';
import 'auth/auth_bloc.dart';
import 'auth/auth_event.dart';

/// Placeholder until a real VK ID app is registered — see the design spec's
/// Risks section and this plan's Task 12.
const _vkIdClientId = 'PLACEHOLDER_APP_ID';
const _redirectUri = 'http://localhost:8080/callback';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final authStore = await AuthStore.open();
  final httpClient = http.Client();
  final oauth = VkIdOAuth(clientId: _vkIdClientId, redirectUri: _redirectUri);

  final authBloc = AuthBloc(
    authStore: authStore,
    oauth: oauth,
    httpClient: httpClient,
    redirect: (uri) => html.window.location.href = uri.toString(),
  );

  final startupUri = Uri.base;
  final callback = parseAuthorizeCallback(startupUri);
  if (callback != null) {
    // Strip the one-time code/state from the address bar before handing it
    // to the bloc — otherwise a page refresh replays the same (by then
    // already-consumed) code through AuthCallbackReceived and clobbers a
    // valid AuthStarted-restored session with a spurious AuthError. Must
    // use the captured startupUri (not a fresh Uri.base read) below —
    // Uri.base is a live view over window.location.href on web, so
    // replaceState mutates what a second Uri.base read would return,
    // silently dropping the code/state/device_id before the bloc sees them.
    html.window.history.replaceState(null, '', _redirectUri);
    authBloc.add(AuthCallbackReceived(startupUri));
  } else {
    authBloc.add(const AuthStarted());
  }

  runApp(AirwireApp(authBloc: authBloc));
}
```

Note: from this task onward, any other task that references `AirwireApp` (e.g. Task 11's wiring step) means `client/app/lib/app.dart`, not `main.dart`.

- [ ] **Step 6: Update the smoke test**

`main_smoke_test.dart` (Task 7) pumped `AirwireApp()` with no arguments — update it for the new required `authBloc` parameter, importing from `app.dart` rather than `main.dart` (per Step 5) since `main.dart` now imports `dart:html`, which the default `flutter test` platform cannot compile. Also note: `FakeAuthBloc` must extend `MockBloc<AuthEvent, AuthState>` (matching `AuthBloc extends Bloc<AuthEvent, AuthState>`'s actual type parameters) — `MockBloc<dynamic, AuthState>` does not work, since `implements AuthBloc` would then require `FakeAuthBloc` to simultaneously be both `Bloc<dynamic, AuthState>` and `Bloc<AuthEvent, AuthState>`, which Dart's analyzer rejects as conflicting instantiations of the same generic class.

```dart
// client/app/test/main_smoke_test.dart
import 'package:airwire_app/app.dart';
import 'package:airwire_app/auth/auth_bloc.dart';
import 'package:airwire_app/auth/auth_event.dart';
import 'package:airwire_app/auth/auth_state.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeAuthBloc extends MockBloc<AuthEvent, AuthState> implements AuthBloc {}

void main() {
  testWidgets('app shows the login screen when unauthenticated', (tester) async {
    final authBloc = FakeAuthBloc();
    whenListen(
      authBloc,
      const Stream<AuthState>.empty(),
      initialState: const AuthUnauthenticated(),
    );

    await tester.pumpWidget(AirwireApp(authBloc: authBloc));
    expect(find.text('Log in with VK ID'), findsOneWidget);
  });
}
```

- [ ] **Step 7: Run all app tests**

Run: `cd client/app && flutter test`
Expected: PASS (all tests across `test/` so far).

- [ ] **Step 8: Commit**

```bash
git add client/app/lib/screens/login_screen.dart client/app/lib/main.dart client/app/test/screens/ client/app/test/main_smoke_test.dart client/app/pubspec.yaml
git commit -m "feat: add login screen and wire VK ID redirect/callback in main.dart"
```

---

## Task 10: `MessagingBloc`

**Files:**
- Create: `client/app/lib/messaging/messaging_event.dart`
- Create: `client/app/lib/messaging/messaging_state.dart`
- Create: `client/app/lib/messaging/messaging_bloc.dart`
- Test: `client/app/test/messaging/messaging_bloc_test.dart`

**Interfaces:**
- Consumes: `Medium`/`OdnoklassnikiMedium` from `medium/` (Tasks 5-6).
- Produces: `class ChatMessage { String peerId; String text; bool fromMe; }`, `class MessagingBloc extends Bloc<MessagingEvent, MessagingState>` with events `ConversationStarted(String peerId)`, `MessageSubmitted(String text)`, and `MessageReceived(String peerId, String text)` (public, but only ever added internally by the bloc's own subscription to `medium.receive()` — screens never dispatch it directly); state `class MessagingState { String? peerId; List<ChatMessage> messages; bool sending; String? error; }`. Task 11 (conversation screen) dispatches `ConversationStarted`/`MessageSubmitted` and renders `messages`.

- [ ] **Step 1: Write the failing tests**

```dart
// client/app/test/messaging/messaging_bloc_test.dart
import 'dart:async';

import 'package:airwire_app/messaging/messaging_bloc.dart';
import 'package:airwire_app/messaging/messaging_event.dart';
import 'package:airwire_app/messaging/messaging_state.dart';
import 'package:airwire_medium/airwire_medium.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeMedium implements Medium {
  FakeMedium({required this.myId, this.sendError});

  @override
  final String myId;

  @override
  int get maxMessageSize => 4096;

  final Object? sendError;
  final List<(String, String)> sentMessages = [];
  final StreamController<(String, String)> _controller =
      StreamController.broadcast();

  @override
  Future<void> send(String peerId, String text) async {
    if (sendError != null) throw sendError!;
    sentMessages.add((peerId, text));
  }

  @override
  Stream<(String, String)> receive() => _controller.stream;

  void emitIncoming(String peerId, String text) {
    _controller.add((peerId, text));
  }

  void dispose() => _controller.close();
}

void main() {
  late FakeMedium medium;

  setUp(() {
    medium = FakeMedium(myId: 'me-1');
  });

  tearDown(() => medium.dispose());

  blocTest<MessagingBloc, MessagingState>(
    'ConversationStarted sets the peer id with an empty message list',
    build: () => MessagingBloc(medium: medium),
    act: (bloc) => bloc.add(const ConversationStarted('peer-1')),
    expect: () => [
      isA<MessagingState>()
          .having((s) => s.peerId, 'peerId', 'peer-1')
          .having((s) => s.messages, 'messages', isEmpty),
    ],
  );

  blocTest<MessagingBloc, MessagingState>(
    'MessageSubmitted sends via the medium and appends a fromMe message',
    build: () => MessagingBloc(medium: medium),
    seed: () => const MessagingState(peerId: 'peer-1', messages: [], sending: false),
    act: (bloc) => bloc.add(const MessageSubmitted('hello')),
    expect: () => [
      isA<MessagingState>().having((s) => s.sending, 'sending', true),
      isA<MessagingState>()
          .having((s) => s.sending, 'sending', false)
          .having(
            (s) => s.messages,
            'messages',
            [const ChatMessage(peerId: 'peer-1', text: 'hello', fromMe: true)],
          ),
    ],
    verify: (_) {
      expect(medium.sentMessages, equals([('peer-1', 'hello')]));
    },
  );

  blocTest<MessagingBloc, MessagingState>(
    'MessageSubmitted sets an error message when send throws',
    build: () => MessagingBloc(medium: FakeMedium(myId: 'me-1', sendError: Exception('boom'))),
    seed: () => const MessagingState(peerId: 'peer-1', messages: [], sending: false),
    act: (bloc) => bloc.add(const MessageSubmitted('hello')),
    expect: () => [
      isA<MessagingState>().having((s) => s.sending, 'sending', true),
      isA<MessagingState>()
          .having((s) => s.sending, 'sending', false)
          .having((s) => s.error, 'error', isNotNull),
    ],
  );

  blocTest<MessagingBloc, MessagingState>(
    'an incoming message from the medium is appended as not fromMe',
    build: () => MessagingBloc(medium: medium),
    seed: () => const MessagingState(peerId: 'peer-1', messages: [], sending: false),
    act: (bloc) => medium.emitIncoming('peer-1', 'hi back'),
    wait: const Duration(milliseconds: 10),
    expect: () => [
      isA<MessagingState>().having(
        (s) => s.messages,
        'messages',
        [const ChatMessage(peerId: 'peer-1', text: 'hi back', fromMe: false)],
      ),
    ],
  );
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd client/app && flutter test test/messaging/messaging_bloc_test.dart`
Expected: FAIL — `MessagingBloc` and friends undefined.

- [ ] **Step 3: Implement `MessagingEvent`**

```dart
// client/app/lib/messaging/messaging_event.dart
import 'package:equatable/equatable.dart';

sealed class MessagingEvent extends Equatable {
  const MessagingEvent();

  @override
  List<Object?> get props => [];
}

class ConversationStarted extends MessagingEvent {
  const ConversationStarted(this.peerId);

  final String peerId;

  @override
  List<Object?> get props => [peerId];
}

class MessageSubmitted extends MessagingEvent {
  const MessageSubmitted(this.text);

  final String text;

  @override
  List<Object?> get props => [text];
}

class MessageReceived extends MessagingEvent {
  const MessageReceived(this.peerId, this.text);

  final String peerId;
  final String text;

  @override
  List<Object?> get props => [peerId, text];
}
```

- [ ] **Step 4: Implement `MessagingState` and `ChatMessage`**

```dart
// client/app/lib/messaging/messaging_state.dart
import 'package:equatable/equatable.dart';

class ChatMessage extends Equatable {
  const ChatMessage({
    required this.peerId,
    required this.text,
    required this.fromMe,
  });

  final String peerId;
  final String text;
  final bool fromMe;

  @override
  List<Object?> get props => [peerId, text, fromMe];
}

class MessagingState extends Equatable {
  const MessagingState({
    this.peerId,
    this.messages = const [],
    this.sending = false,
    this.error,
  });

  final String? peerId;
  final List<ChatMessage> messages;
  final bool sending;
  final String? error;

  MessagingState copyWith({
    String? peerId,
    List<ChatMessage>? messages,
    bool? sending,
    String? error,
    bool clearError = false,
  }) {
    return MessagingState(
      peerId: peerId ?? this.peerId,
      messages: messages ?? this.messages,
      sending: sending ?? this.sending,
      error: clearError ? null : (error ?? this.error),
    );
  }

  @override
  List<Object?> get props => [peerId, messages, sending, error];
}
```

- [ ] **Step 5: Implement `MessagingBloc`**

```dart
// client/app/lib/messaging/messaging_bloc.dart
import 'dart:async';

import 'package:airwire_medium/airwire_medium.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'messaging_event.dart';
import 'messaging_state.dart';

class MessagingBloc extends Bloc<MessagingEvent, MessagingState> {
  MessagingBloc({required Medium medium})
      : _medium = medium,
        super(const MessagingState()) {
    on<ConversationStarted>(_onConversationStarted);
    on<MessageSubmitted>(_onMessageSubmitted);
    on<MessageReceived>(_onMessageReceived);

    _subscription = _medium.receive().listen(
      (event) => add(MessageReceived(event.$1, event.$2)),
    );
  }

  final Medium _medium;
  late final StreamSubscription<(String, String)> _subscription;

  void _onConversationStarted(
    ConversationStarted event,
    Emitter<MessagingState> emit,
  ) {
    emit(MessagingState(peerId: event.peerId, messages: const []));
  }

  Future<void> _onMessageSubmitted(
    MessageSubmitted event,
    Emitter<MessagingState> emit,
  ) async {
    final peerId = state.peerId;
    if (peerId == null) return;

    emit(state.copyWith(sending: true, clearError: true));
    try {
      await _medium.send(peerId, event.text);
      emit(state.copyWith(
        sending: false,
        messages: [
          ...state.messages,
          ChatMessage(peerId: peerId, text: event.text, fromMe: true),
        ],
      ));
    } catch (error) {
      emit(state.copyWith(sending: false, error: 'Send failed: $error'));
    }
  }

  void _onMessageReceived(
    MessageReceived event,
    Emitter<MessagingState> emit,
  ) {
    if (event.peerId != state.peerId) return;
    emit(state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(peerId: event.peerId, text: event.text, fromMe: false),
      ],
    ));
  }

  @override
  Future<void> close() {
    _subscription.cancel();
    return super.close();
  }
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd client/app && flutter test test/messaging/messaging_bloc_test.dart`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add client/app/lib/messaging/ client/app/test/messaging/
git commit -m "feat: add MessagingBloc wrapping Medium send/receive"
```

---

## Task 11: Conversation screen

**Files:**
- Create: `client/app/lib/screens/conversation_screen.dart`
- Modify: `client/app/lib/app.dart` (not `main.dart` — `AirwireApp` lives here since Task 9; see that task's Step 5 note)
- Modify: `client/app/lib/main.dart` (only for the `_conversationPeerId` placeholder constant, alongside the existing `_vkIdClientId`/`_redirectUri`)
- Test: `client/app/test/screens/conversation_screen_test.dart`

**Interfaces:**
- Consumes: `MessagingBloc`, `MessagingEvent`, `MessagingState`, `ChatMessage` from Task 10.
- Produces: `class ConversationScreen extends StatelessWidget`. Replaces the `Scaffold(body: Center(child: Text('Logged in.')))` placeholder in `client/app/lib/app.dart` (from Task 9).

- [ ] **Step 1: Write the failing test**

```dart
// client/app/test/screens/conversation_screen_test.dart
import 'package:airwire_app/messaging/messaging_bloc.dart';
import 'package:airwire_app/messaging/messaging_event.dart';
import 'package:airwire_app/messaging/messaging_state.dart';
import 'package:airwire_app/screens/conversation_screen.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockMessagingBloc extends MockBloc<MessagingEvent, MessagingState>
    implements MessagingBloc {}

void main() {
  late MockMessagingBloc bloc;

  setUp(() {
    bloc = MockMessagingBloc();
  });

  Widget wrap(Widget child) => MaterialApp(
        home: BlocProvider<MessagingBloc>.value(value: bloc, child: child),
      );

  testWidgets('renders messages with sent/received distinction', (tester) async {
    when(() => bloc.state).thenReturn(const MessagingState(
      peerId: 'peer-1',
      messages: [
        ChatMessage(peerId: 'peer-1', text: 'hello', fromMe: true),
        ChatMessage(peerId: 'peer-1', text: 'hi back', fromMe: false),
      ],
    ));

    await tester.pumpWidget(wrap(const ConversationScreen()));

    expect(find.text('hello'), findsOneWidget);
    expect(find.text('hi back'), findsOneWidget);
  });

  testWidgets('submitting text dispatches MessageSubmitted and clears the field',
      (tester) async {
    when(() => bloc.state).thenReturn(const MessagingState(peerId: 'peer-1'));
    await tester.pumpWidget(wrap(const ConversationScreen()));

    await tester.enterText(find.byType(TextField), 'hello there');
    await tester.tap(find.byIcon(Icons.send));

    verify(() => bloc.add(const MessageSubmitted('hello there'))).called(1);
  });

  testWidgets('shows the error banner when state has an error', (tester) async {
    when(() => bloc.state).thenReturn(const MessagingState(
      peerId: 'peer-1',
      error: 'Send failed: network error',
    ));

    await tester.pumpWidget(wrap(const ConversationScreen()));

    expect(find.text('Send failed: network error'), findsOneWidget);
  });
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd client/app && flutter test test/screens/conversation_screen_test.dart`
Expected: FAIL — `ConversationScreen` undefined.

- [ ] **Step 3: Implement `ConversationScreen`**

```dart
// client/app/lib/screens/conversation_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../messaging/messaging_bloc.dart';
import '../messaging/messaging_event.dart';
import '../messaging/messaging_state.dart';

class ConversationScreen extends StatefulWidget {
  const ConversationScreen({super.key});

  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit(BuildContext context) {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    context.read<MessagingBloc>().add(MessageSubmitted(text));
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Conversation')),
      body: BlocBuilder<MessagingBloc, MessagingState>(
        builder: (context, state) {
          return Column(
            children: [
              if (state.error != null)
                Container(
                  width: double.infinity,
                  color: Colors.red.shade100,
                  padding: const EdgeInsets.all(8),
                  child: Text(state.error!),
                ),
              Expanded(
                child: ListView.builder(
                  itemCount: state.messages.length,
                  itemBuilder: (context, index) {
                    final message = state.messages[index];
                    return Align(
                      alignment: message.fromMe
                          ? Alignment.centerRight
                          : Alignment.centerLeft,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 4,
                        ),
                        child: Text(message.text),
                      ),
                    );
                  },
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(8),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _controller,
                        onSubmitted: (_) => _submit(context),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.send),
                      onPressed: state.sending ? null : () => _submit(context),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd client/app && flutter test test/screens/conversation_screen_test.dart`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire `MessagingBloc`/`ConversationScreen` into `app.dart`**

`AirwireApp` lives in `client/app/lib/app.dart` (Task 9 extracted it out of `main.dart` so tests importing it don't drag in `dart:html`) — wire the conversation screen in there, not `main.dart`.

The hardcoded peer id (matching the design spec's "single hardcoded conversation partner" scope) needs to reach `app.dart` from `main.dart`, where it lives alongside the other two placeholders Task 12 fills in. **Do not** have `app.dart` do `import 'main.dart' show conversationPeerId;` — a `show` combinator only restricts which *names* are visible, it does not stop the imported library's own imports from being pulled in too, so this would drag `main.dart`'s `dart:html` import into `app.dart`'s import graph and break every test that imports `app.dart` on the default VM test platform (exactly what Task 9's extraction was meant to prevent). Instead, inject it as a constructor field, the same pattern already used for `authBloc`:

```dart
// client/app/lib/app.dart
// Add these imports:
import 'messaging/messaging_bloc.dart';
import 'messaging/messaging_event.dart';
import 'screens/conversation_screen.dart';

// Change the constructor and add a field:
class AirwireApp extends StatelessWidget {
  const AirwireApp({
    required this.authBloc,
    required this.conversationPeerId,
    super.key,
  });

  final AuthBloc authBloc;
  final String conversationPeerId;

  // ... build() unchanged except the AuthAuthenticated branch:

  @override
  Widget build(BuildContext context) {
    return BlocProvider<AuthBloc>.value(
      value: authBloc,
      child: MaterialApp(
        title: 'Airwire',
        home: BlocBuilder<AuthBloc, AuthState>(
          builder: (context, state) {
            if (state is AuthAuthenticated) {
              return BlocProvider<MessagingBloc>(
                create: (_) => MessagingBloc(medium: state.medium)
                  ..add(ConversationStarted(conversationPeerId)),
                child: const ConversationScreen(),
              );
            }
            return const LoginScreen();
          },
        ),
      ),
    );
  }
}
```

Add the constant to `main.dart` alongside the existing `_vkIdClientId`/`_redirectUri` placeholders, dropping the leading underscore on all three (they need to be public now that `app.dart` — a different file — reads `conversationPeerId` via the constructor field above; `main.dart` still owns the values, so update both existing reference sites in `main.dart` itself, `VkIdOAuth(clientId: ..., redirectUri: ...)` and the `replaceState` call, to match):

```dart
// client/app/lib/main.dart
const vkIdClientId = 'PLACEHOLDER_APP_ID';
const redirectUri = 'http://localhost:8080/callback';
const conversationPeerId = 'PLACEHOLDER_PEER_ID';

// Update the runApp call at the bottom of main():
runApp(AirwireApp(authBloc: authBloc, conversationPeerId: conversationPeerId));
```

Because `AirwireApp`'s constructor gained a new required parameter, the other call site — `test/main_smoke_test.dart`, from Task 9 — also needs a one-line update: `AirwireApp(authBloc: authBloc, conversationPeerId: 'peer-1')` (an inert value; that test only exercises the unauthenticated branch, which doesn't read it).

- [ ] **Step 6: Run all app tests**

Run: `cd client/app && flutter test`
Expected: PASS (all tests across `test/`, including the updated `main_smoke_test.dart`).

- [ ] **Step 7: Commit**

```bash
git add client/app/lib/screens/conversation_screen.dart client/app/lib/app.dart client/app/lib/main.dart client/app/test/screens/conversation_screen_test.dart client/app/test/main_smoke_test.dart
git commit -m "feat: add conversation screen and wire it in for authenticated state"
```

---

## Task 12: Manual verification (gated on real credentials)

**Files:**
- Modify: `client/app/lib/main.dart` (replace placeholders with real values — not committed with real secrets if `client_id` is meant to stay private; VK ID's `client_id` is not a secret — it's sent in a public redirect URL by design, so committing it is fine, unlike a client secret)

This task cannot start until you have registered a VK ID application (see the design spec's Risks section) and have a second OK.ru account/contact to test with, per your "full send/receive loop" answer during design. Nothing before this task depends on real credentials — everything else in this plan builds and unit-tests against placeholders.

- [ ] **Step 1: Register the VK ID application**

Via VK ID's developer console (`id.vk.com/business` or `id.vk.ru/about/business/`, per this session's research), register a new application. Configure:
- Platform: Web.
- Redirect URI: `http://localhost:8080/callback` (matching `_redirectUri` in `main.dart`) for local dev — add your real deployed URL later if you host this anywhere.
- Request whichever permission includes messaging — `VALUABLE_ACCESS` is the best-supported guess from this plan's research (see Global Constraints); if the app registration UI lists a more specific messaging permission, prefer that instead.

Record the resulting `client_id`.

- [ ] **Step 2: Fill in the real `client_id` and peer id**

```dart
// client/app/lib/main.dart
const _vkIdClientId = '<real client_id from Step 1>';
const _conversationPeerId = '<your test contacts OK.ru numeric user id>';
```

- [ ] **Step 3: Run the app locally**

Run: `cd client/app && flutter run -d chrome --web-port 8080`
Expected: the login screen appears.

- [ ] **Step 4: Verify login**

Click "Log in with VK ID". Expected: browser redirects to a real VK ID login page; after authenticating and consenting, it redirects back to `localhost:8080/callback?code=...&state=...&device_id=...` and the app shows the conversation screen (not an error). If it instead shows `AuthError`, read the message — it will be either an OAuth-level error (wrong redirect URI registered, wrong scope) or an API-level error surfaced from `graph/me` (in which case, check whether the `myId` field-name fallback chain in `OdnoklassnikiMedium.authenticate` — Task 5 — actually matched a real field; adjust the parsing if OK.ru returns something under a different key than `uid`/`id`/`user_id`).

- [ ] **Step 5: Verify send**

Type a message and hit send (or Enter). Expected: no error banner; the message appears right-aligned in the list. On the *other* account (logged in separately, e.g. a different browser profile or the regular OK.ru web app), confirm the message actually arrived.

- [ ] **Step 6: Verify receive**

From the other account, send a reply. Within ~5 seconds (the poll interval from Task 6), expected: the reply appears left-aligned in this app's conversation screen without any manual refresh.

**If nothing arrives**, check this specific thing before assuming the whole receive path is broken: `_pollMessages()` (in `client/medium/lib/src/odnoklassniki_medium.dart`) now dedups by the response's `message.mid` field, added during the final-review fix wave — this field name was never confirmed against a real API response (only inferred from documentation). If OK's real response either omits `mid` or names it something else, every incoming message gets silently filtered out by the `if (mid == null) continue;` guard (as opposed to the old timestamp-only dedup, which would have at least shown *something*, just with possible duplicates). If receive shows nothing, add a temporary print of the raw `/graph/me/messages` response body to see the real field name before debugging further downstream.

- [ ] **Step 7: Note any deviations found**

If any of Steps 4-6 surfaced a wrong assumption (identity field name, message size limit, permission scope name, the `mid` field name above, or the cold-messaging/prior-contact requirement from the design spec's Risks section), fix the relevant code from Tasks 5/6 and re-run that task's unit tests to make sure the fix didn't break the mocked-response tests — update the mock fixtures' field names to match what you now know is real, so the tests keep testing something true.

- [ ] **Step 8: Commit**

```bash
git add client/app/lib/main.dart
git commit -m "chore: fill in real VK ID app_id and test peer id"
```

Note: only do this commit if you're comfortable with `client_id` (not a secret, but still identifies your registered app) being in git history. If you'd rather keep it out of version control entirely, use `--dart-define=VK_ID_CLIENT_ID=...` at `flutter run`/`flutter build` time instead and read it via `String.fromEnvironment('VK_ID_CLIENT_ID')` in `main.dart` — a reasonable follow-up if this prototype grows past hands-on testing, not required to close out this plan.
