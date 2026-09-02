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
