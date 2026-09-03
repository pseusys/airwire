import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'auth/auth_bloc.dart';
import 'auth/auth_state.dart';
import 'screens/login_screen.dart';

/// The root widget, kept in its own file (no `dart:html` in its import
/// graph) so widget tests can pump it directly on the VM test platform —
/// `main.dart` imports `dart:html` for the VK ID redirect/callback wiring,
/// and that library isn't available under `flutter test`'s default
/// VM-based ("tester") platform. See `main.dart` for the bootstrap that
/// constructs the real `AuthBloc` and calls `runApp(AirwireApp(...))`.
class AirwireApp extends StatelessWidget {
  const AirwireApp({required this.authBloc, super.key});

  final AuthBloc authBloc;

  @override
  Widget build(BuildContext context) {
    return BlocProvider<AuthBloc>.value(
      value: authBloc,
      child: MaterialApp(
        title: 'Airwire',
        home: BlocBuilder<AuthBloc, AuthState>(
          builder: (context, state) {
            if (state is AuthAuthenticated) {
              // Replaced with ConversationScreen in Task 11.
              return const Scaffold(body: Center(child: Text('Logged in.')));
            }
            return const LoginScreen();
          },
        ),
      ),
    );
  }
}
