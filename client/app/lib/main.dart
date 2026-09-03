// dart:html is a deliberate, load-bearing choice for this Flutter Web-only
// prototype (window.location/history access for the VK ID redirect
// callback flow) — see the design spec's Risks section. A migration to
// package:web/dart:js_interop is a known future improvement, not done here
// to keep this prototype's scope minimal.
// ignore: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;

import 'package:airwire_medium/airwire_medium.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'app.dart';
import 'auth/auth_bloc.dart';
import 'auth/auth_event.dart';

/// Placeholder until a real VK ID app is registered — see the design spec's
/// Risks section and this plan's Task 12.
const vkIdClientId = 'PLACEHOLDER_APP_ID';
const redirectUri = 'http://localhost:8080/callback';

/// Placeholder for the single hardcoded conversation partner — see the
/// design spec's scope and this plan's Task 12.
const conversationPeerId = 'PLACEHOLDER_PEER_ID';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final authStore = await AuthStore.open();
  final httpClient = http.Client();
  final oauth = VkIdOAuth(clientId: vkIdClientId, redirectUri: redirectUri);

  final authBloc = AuthBloc(
    authStore: authStore,
    oauth: oauth,
    httpClient: httpClient,
    redirect: (uri) => html.window.location.href = uri.toString(),
  );

  final startupUri = Uri.base;
  final callback = parseAuthorizeCallback(startupUri);
  if (callback != null) {
    // Strip the one-time code/state from the address bar before handing it
    // to the bloc — otherwise a page refresh replays the same (by then
    // already-consumed) code through AuthCallbackReceived and clobbers a
    // valid AuthStarted-restored session with a spurious AuthError. Must
    // use the captured startupUri (not a fresh Uri.base read) below —
    // Uri.base is a live view over window.location.href on web, so
    // replaceState mutates what a second Uri.base read would return,
    // silently dropping the code/state/device_id before the bloc sees them.
    // Use the actual current URL (minus its query) rather than the
    // hardcoded placeholder redirectUri — history.replaceState's third
    // argument must be same-origin with the current page or the browser
    // throws SecurityError synchronously, which would blank the page before
    // runApp() ever runs anywhere the origin doesn't match the placeholder.
    html.window.history.replaceState(null, '', startupUri.replace(query: '').toString());
    authBloc.add(AuthCallbackReceived(startupUri));
  } else {
    authBloc.add(const AuthStarted());
  }

  runApp(AirwireApp(authBloc: authBloc, conversationPeerId: conversationPeerId));
}
