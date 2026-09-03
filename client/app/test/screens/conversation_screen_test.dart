import 'package:airwire_app/messaging/messaging_bloc.dart';
import 'package:airwire_app/messaging/messaging_event.dart';
import 'package:airwire_app/messaging/messaging_state.dart';
import 'package:airwire_app/screens/conversation_screen.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockMessagingBloc extends MockBloc<MessagingEvent, MessagingState>
    implements MessagingBloc {}

void main() {
  late MockMessagingBloc bloc;

  setUp(() {
    bloc = MockMessagingBloc();
  });

  Widget wrap(Widget child) => MaterialApp(
        home: BlocProvider<MessagingBloc>.value(value: bloc, child: child),
      );

  testWidgets('renders messages with sent/received distinction', (tester) async {
    when(() => bloc.state).thenReturn(const MessagingState(
      peerId: 'peer-1',
      messages: [
        ChatMessage(peerId: 'peer-1', text: 'hello', fromMe: true),
        ChatMessage(peerId: 'peer-1', text: 'hi back', fromMe: false),
      ],
    ));

    await tester.pumpWidget(wrap(const ConversationScreen()));

    expect(find.text('hello'), findsOneWidget);
    expect(find.text('hi back'), findsOneWidget);
  });

  testWidgets('submitting text dispatches MessageSubmitted and clears the field',
      (tester) async {
    when(() => bloc.state).thenReturn(const MessagingState(peerId: 'peer-1'));
    await tester.pumpWidget(wrap(const ConversationScreen()));

    await tester.enterText(find.byType(TextField), 'hello there');
    await tester.tap(find.byIcon(Icons.send));

    verify(() => bloc.add(const MessageSubmitted('hello there'))).called(1);
  });

  testWidgets('shows the error banner when state has an error', (tester) async {
    when(() => bloc.state).thenReturn(const MessagingState(
      peerId: 'peer-1',
      error: 'Send failed: network error',
    ));

    await tester.pumpWidget(wrap(const ConversationScreen()));

    expect(find.text('Send failed: network error'), findsOneWidget);
  });
}
