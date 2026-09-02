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
