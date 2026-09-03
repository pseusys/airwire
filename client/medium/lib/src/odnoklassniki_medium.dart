import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'medium.dart';

class OdnoklassnikiApiException implements Exception {
  OdnoklassnikiApiException(this.message);

  final String message;

  @override
  String toString() => 'OdnoklassnikiApiException: $message';
}

/// OK ids are sometimes seen prefixed (`user:12345`) and sometimes bare,
/// depending on which API surface they come from. Every place in this file
/// that compares two ids for equality must normalize both sides through
/// this helper first, or a prefixed id will never equal an equivalent bare
/// one.
String _stripUserPrefix(String id) =>
    id.startsWith('user:') ? id.substring(5) : id;

/// Odnoklassniki's Graph API wrapper. Constructed via [authenticate] rather
/// than a plain constructor because resolving `myId` requires a network
/// call — there is no meaningful zero-argument instance.
///
/// `receive()` is added in Task 6; until then this class intentionally does
/// not `implements Medium`, since it doesn't yet satisfy that contract.
class OdnoklassnikiMedium implements Medium {
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
    final rawMyId = (json['uid'] ?? json['id'] ?? json['user_id'])?.toString();
    if (rawMyId == null) {
      throw OdnoklassnikiApiException(
        'graph/me response had no recognizable id field: ${response.body}',
      );
    }

    return OdnoklassnikiMedium._(
      accessToken: accessToken,
      myId: _stripUserPrefix(rawMyId),
      httpClient: client,
    );
  }

  @override
  String get myId => _myId;

  /// OK's documented limits didn't specify a message text length during
  /// planning — this is a conservative default, tightened based on real
  /// API error responses during the manual-verification task if needed.
  @override
  int get maxMessageSize => 4096;

  @override
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

  StreamController<(String, String)>? _receiveController;
  Timer? _pollTimer;
  final Map<String, int> _lastSeenTimestamp = {};

  /// The authoritative dedup key, per chat — a message is only ever emitted
  /// once per `mid`. `_lastSeenTimestamp` above is kept only as a cheap
  /// prefilter to limit how much history gets re-scanned each poll; it must
  /// never be the sole dedup decision, since two distinct messages can share
  /// a `timestamp` value (e.g. coarse server-side granularity).
  final Map<String, Set<String>> _seenMessageIds = {};

  @override
  Stream<(String, String)> receive() {
    _receiveController ??= StreamController<(String, String)>.broadcast();
    // pollOnce()'s returned Future must not be discarded bare — any
    // exception it throws (network failure, malformed JSON, a non-200 from
    // the API) needs to reach the stream as an error rather than becoming
    // an unhandled async error with no signal to the app.
    _pollTimer ??= Timer.periodic(const Duration(seconds: 5), (_) {
      pollOnce().catchError((Object error, StackTrace stack) {
        _receiveController?.addError(error, stack);
      });
    });
    return _receiveController!.stream;
  }

  /// Runs one poll cycle: list active chats, then fetch unseen messages in
  /// each. Public (not private) so tests can trigger a deterministic poll
  /// instead of waiting on the real Timer.
  Future<void> pollOnce() async {
    final chatsResponse = await _httpClient.get(
      Uri.https(_apiHost, '/graph/me/chats', {'access_token': _accessToken}),
    );
    if (chatsResponse.statusCode != 200) {
      throw OdnoklassnikiApiException(
        'Failed to list chats: ${chatsResponse.statusCode} ${chatsResponse.body}',
      );
    }

    final chatsJson = jsonDecode(chatsResponse.body) as Map<String, dynamic>;
    final chats = (chatsJson['chats'] as List?) ?? const [];

    for (final chat in chats.cast<Map<String, dynamic>>()) {
      final chatId = chat['chat_id'] as String?;
      final participants =
          (chat['participants'] as Map?)?.cast<String, dynamic>() ?? const {};
      final otherPeerId = participants.keys
          .map(_stripUserPrefix)
          .firstWhere((id) => id != _myId, orElse: () => '');
      if (chatId == null || otherPeerId.isEmpty) continue;
      await _pollMessages(chatId, otherPeerId);
    }
  }

  Future<void> _pollMessages(String chatId, String peerId) async {
    final since = _lastSeenTimestamp[chatId] ?? 0;
    final seenIds = _seenMessageIds.putIfAbsent(chatId, () => <String>{});
    final response = await _httpClient.get(
      Uri.https(_apiHost, '/graph/me/messages', {
        'chat_id': chatId,
        'access_token': _accessToken,
        'count': '50',
      }),
    );
    if (response.statusCode != 200) {
      throw OdnoklassnikiApiException(
        'Failed to fetch messages for $chatId: ${response.statusCode} ${response.body}',
      );
    }

    final json = jsonDecode(response.body) as Map<String, dynamic>;
    final messages = (json['messages'] as List?) ?? const [];
    var latest = since;

    for (final entry in messages.cast<Map<String, dynamic>>()) {
      final timestamp = (entry['timestamp'] as num?)?.toInt() ?? 0;
      // Cheap prefilter only — strictly-older entries can't possibly be new,
      // but entries AT the watermark timestamp still need the mid check
      // below, since another message can share that same timestamp value.
      if (timestamp < since) continue;

      final mid = (entry['message'] as Map?)?['mid'] as String?;
      final rawSenderId = (entry['sender'] as Map?)?['user_id'] as String?;
      final senderId = rawSenderId == null ? null : _stripUserPrefix(rawSenderId);
      final text = (entry['message'] as Map?)?['text'] as String?;
      if (mid == null || senderId == null || senderId == _myId || text == null) {
        continue;
      }
      if (!seenIds.add(mid)) continue; // already emitted this mid before

      _receiveController?.add((peerId, text));
      if (timestamp > latest) latest = timestamp;
    }

    _lastSeenTimestamp[chatId] = latest;
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _receiveController?.close();
    _receiveController = null;
  }
}
