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

  final callback = parseAuthorizeCallback(Uri.base);
  if (callback != null) {
    // Strip the one-time code/state from the address bar before handing it
    // to the bloc — otherwise a page refresh replays the same (by then
    // already-consumed) code through AuthCallbackReceived and clobbers a
    // valid AuthStarted-restored session with a spurious AuthError.
    html.window.history.replaceState(null, '', _redirectUri);
    authBloc.add(AuthCallbackReceived(Uri.base));
  } else {
    authBloc.add(const AuthStarted());
  }

  runApp(AirwireApp(authBloc: authBloc));
}
