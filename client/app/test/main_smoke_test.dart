import 'package:airwire_app/app.dart';
import 'package:airwire_app/auth/auth_bloc.dart';
import 'package:airwire_app/auth/auth_event.dart';
import 'package:airwire_app/auth/auth_state.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeAuthBloc extends MockBloc<AuthEvent, AuthState> implements AuthBloc {}

void main() {
  testWidgets('app shows the login screen when unauthenticated', (tester) async {
    final authBloc = FakeAuthBloc();
    whenListen(
      authBloc,
      const Stream<AuthState>.empty(),
      initialState: const AuthUnauthenticated(),
    );

    await tester.pumpWidget(AirwireApp(authBloc: authBloc));
    expect(find.text('Log in with VK ID'), findsOneWidget);
  });
}
