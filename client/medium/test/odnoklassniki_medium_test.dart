import 'dart:async';
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

      // myId must always be normalized to the bare id, regardless of which
      // field it came from — every comparison site elsewhere strips a
      // `user:` prefix before comparing, so _myId itself must already be
      // bare or those comparisons silently never match.
      expect(medium.myId, equals('555000111'));
    });

    test('normalizes myId when the uid field itself is prefixed', () async {
      final mockClient = MockClient((request) async {
        return http.Response(jsonEncode({'uid': 'user:555000111'}), 200);
      });

      final medium = await OdnoklassnikiMedium.authenticate(
        accessToken: 'token-1',
        httpClient: mockClient,
      );

      expect(medium.myId, equals('555000111'));
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

    test(
      'self-filter and participant selection still work when myId is '
      'resolved from a user:-prefixed field',
      () async {
        final mockClient = MockClient((request) async {
          if (request.url.path == '/graph/me') {
            // Falls back to user_id, which (per OK's convention) is prefixed.
            return http.Response(jsonEncode({'user_id': 'user:me-1'}), 200);
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
                  {
                    'sender': {'user_id': 'user:peer-1'},
                    'message': {'text': 'hi from peer', 'mid': 'mid:2'},
                    'timestamp': 5001,
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
        expect(medium.myId, equals('me-1'));

        final events = <(String, String)>[];
        final subscription = medium.receive().listen(events.add);
        await medium.pollOnce();
        await Future<void>.delayed(Duration.zero);

        // The self-sent message must be filtered out, and the peer message
        // must be attributed to the correct (non-me) participant.
        expect(events, equals([('peer-1', 'hi from peer')]));

        await subscription.cancel();
        medium.dispose();
      },
    );
  });
}
