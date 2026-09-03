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
