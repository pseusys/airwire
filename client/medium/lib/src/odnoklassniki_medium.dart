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
