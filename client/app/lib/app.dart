import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'auth/auth_bloc.dart';
import 'auth/auth_state.dart';
import 'messaging/messaging_bloc.dart';
import 'messaging/messaging_event.dart';
import 'screens/conversation_screen.dart';
import 'screens/login_screen.dart';

/// The root widget, kept in its own file (no `dart:html` in its import
/// graph) so widget tests can pump it directly on the VM test platform —
/// `main.dart` imports `dart:html` for the VK ID redirect/callback wiring,
/// and that library isn't available under `flutter test`'s default
/// VM-based ("tester") platform. See `main.dart` for the bootstrap that
/// constructs the real `AuthBloc` and calls `runApp(AirwireApp(...))`.
class AirwireApp extends StatelessWidget {
  const AirwireApp({
    required this.authBloc,
    required this.conversationPeerId,
    super.key,
  });

  final AuthBloc authBloc;

  // Injected from `main.dart`'s `conversationPeerId` constant rather than
  // imported here directly — an `import 'main.dart' ...` would pull
  // `main.dart`'s `dart:html` import into this file's import graph too
  // (a `show` combinator only restricts which names are visible, not what
  // gets compiled in), defeating Task 9's extraction of AirwireApp into its
  // own dart:html-free file. Passing it as a constructor field instead
  // keeps that isolation, matching how `authBloc` is already injected.
  final String conversationPeerId;

  @override
  Widget build(BuildContext context) {
    return BlocProvider<AuthBloc>.value(
      value: authBloc,
      child: MaterialApp(
        title: 'Airwire',
        home: BlocBuilder<AuthBloc, AuthState>(
          builder: (context, state) {
            if (state is AuthAuthenticated) {
              return BlocProvider<MessagingBloc>(
                create: (_) => MessagingBloc(medium: state.medium)
                  ..add(ConversationStarted(conversationPeerId)),
                child: const ConversationScreen(),
              );
            }
            return const LoginScreen();
          },
        ),
      ),
    );
  }
}
