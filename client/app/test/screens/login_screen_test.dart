import 'package:airwire_app/auth/auth_bloc.dart';
import 'package:airwire_app/auth/auth_event.dart';
import 'package:airwire_app/auth/auth_state.dart';
import 'package:airwire_app/screens/login_screen.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockAuthBloc extends MockBloc<AuthEvent, AuthState> implements AuthBloc {}

void main() {
  late MockAuthBloc authBloc;

  setUp(() {
    authBloc = MockAuthBloc();
  });

  Widget wrap(Widget child) => MaterialApp(
        home: BlocProvider<AuthBloc>.value(value: authBloc, child: child),
      );

  testWidgets('shows a login button when unauthenticated', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthUnauthenticated());
    await tester.pumpWidget(wrap(const LoginScreen()));

    expect(find.text('Log in with VK ID'), findsOneWidget);
  });

  testWidgets('tapping the login button dispatches LoginRequested', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthUnauthenticated());
    await tester.pumpWidget(wrap(const LoginScreen()));

    await tester.tap(find.text('Log in with VK ID'));
    verify(() => authBloc.add(const LoginRequested())).called(1);
  });

  testWidgets('shows a progress indicator while redirecting', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthRedirecting());
    await tester.pumpWidget(wrap(const LoginScreen()));

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('shows the error message when login failed', (tester) async {
    when(() => authBloc.state).thenReturn(const AuthError('something broke'));
    await tester.pumpWidget(wrap(const LoginScreen()));

    expect(find.text('something broke'), findsOneWidget);
  });
}
