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
        captured = request;
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

    test(
      'throws a diagnosable VkIdAuthException, not a raw TypeError, when a '
      '200 response is shaped unexpectedly',
      () async {
        final mockClient = MockClient((request) async {
          // Missing access_token entirely — would otherwise throw a raw
          // "type 'Null' is not a subtype of type 'String'" TypeError.
          return http.Response(jsonEncode({'user_id': 12345}), 200);
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
          throwsA(
            isA<VkIdAuthException>().having(
              (e) => e.toString(),
              'message',
              contains('Unexpected token response shape'),
            ),
          ),
        );
      },
    );
  });
}
