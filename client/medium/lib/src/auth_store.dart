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
