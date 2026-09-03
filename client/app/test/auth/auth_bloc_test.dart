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
      // AuthStore.savePendingFlow performs real Hive disk writes, which can
      // outlast bloc_test's default post-act grace period — wait for the
      // actual terminal state instead of guessing a timeout.
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
      // AuthStore.saveTokens performs real Hive disk writes, which can
      // outlast bloc_test's default post-act grace period — wait for the
      // actual terminal state instead of guessing a timeout.
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
    // Seeded as AuthInitial (not AuthUnauthenticated) so the Unauthenticated
    // state the handler emits is a genuinely new value: Bloc.emit() silently
    // no-ops when the new state equals the current state, which would make
    // this test vacuously pass without ever exercising the handler's emit.
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
      // AuthStore.clearTokens performs real Hive disk writes, which can
      // outlast bloc_test's default post-act grace period — wait for the
      // actual terminal state instead of guessing a timeout.
      await bloc.stream.firstWhere((state) => state is AuthUnauthenticated);
    },
    expect: () => [isA<AuthUnauthenticated>()],
    verify: (_) {
      expect(authStore.loadTokens(), isNull);
    },
  );
}
