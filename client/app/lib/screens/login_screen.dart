import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../auth/auth_bloc.dart';
import '../auth/auth_event.dart';
import '../auth/auth_state.dart';

class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Airwire')),
      body: Center(
        child: BlocBuilder<AuthBloc, AuthState>(
          builder: (context, state) {
            return switch (state) {
              AuthRedirecting() => const CircularProgressIndicator(),
              AuthError(:final message) => Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(message),
                    const SizedBox(height: 16),
                    _loginButton(context),
                  ],
                ),
              _ => _loginButton(context),
            };
          },
        ),
      ),
    );
  }

  Widget _loginButton(BuildContext context) {
    return ElevatedButton(
      onPressed: () => context.read<AuthBloc>().add(const LoginRequested()),
      child: const Text('Log in with VK ID'),
    );
  }
}
