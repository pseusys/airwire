import 'dart:async';

import 'package:airwire_app/messaging/messaging_bloc.dart';
import 'package:airwire_app/messaging/messaging_event.dart';
import 'package:airwire_app/messaging/messaging_state.dart';
import 'package:airwire_medium/airwire_medium.dart';
import 'package:bloc_test/bloc_test.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeMedium implements Medium {
  FakeMedium({required this.myId, this.sendError});

  @override
  final String myId;

  @override
  int get maxMessageSize => 4096;

  final Object? sendError;
  final List<(String, String)> sentMessages = [];
  final StreamController<(String, String)> _controller =
      StreamController.broadcast();

  @override
  Future<void> send(String peerId, String text) async {
    if (sendError != null) throw sendError!;
    sentMessages.add((peerId, text));
  }

  @override
  Stream<(String, String)> receive() => _controller.stream;

  void emitIncoming(String peerId, String text) {
    _controller.add((peerId, text));
  }

  void dispose() => _controller.close();
}

void main() {
  late FakeMedium medium;

  setUp(() {
    medium = FakeMedium(myId: 'me-1');
  });

  tearDown(() => medium.dispose());

  blocTest<MessagingBloc, MessagingState>(
    'ConversationStarted sets the peer id with an empty message list',
    build: () => MessagingBloc(medium: medium),
    act: (bloc) => bloc.add(const ConversationStarted('peer-1')),
    expect: () => [
      isA<MessagingState>()
          .having((s) => s.peerId, 'peerId', 'peer-1')
          .having((s) => s.messages, 'messages', isEmpty),
    ],
  );

  blocTest<MessagingBloc, MessagingState>(
    'MessageSubmitted sends via the medium and appends a fromMe message',
    build: () => MessagingBloc(medium: medium),
    seed: () => const MessagingState(peerId: 'peer-1', messages: [], sending: false),
    act: (bloc) => bloc.add(const MessageSubmitted('hello')),
    expect: () => [
      isA<MessagingState>().having((s) => s.sending, 'sending', true),
      isA<MessagingState>()
          .having((s) => s.sending, 'sending', false)
          .having(
            (s) => s.messages,
            'messages',
            [const ChatMessage(peerId: 'peer-1', text: 'hello', fromMe: true)],
          ),
    ],
    verify: (_) {
      expect(medium.sentMessages, equals([('peer-1', 'hello')]));
    },
  );

  blocTest<MessagingBloc, MessagingState>(
    'MessageSubmitted sets an error message when send throws',
    build: () => MessagingBloc(medium: FakeMedium(myId: 'me-1', sendError: Exception('boom'))),
    seed: () => const MessagingState(peerId: 'peer-1', messages: [], sending: false),
    act: (bloc) => bloc.add(const MessageSubmitted('hello')),
    expect: () => [
      isA<MessagingState>().having((s) => s.sending, 'sending', true),
      isA<MessagingState>()
          .having((s) => s.sending, 'sending', false)
          .having((s) => s.error, 'error', isNotNull),
    ],
  );

  blocTest<MessagingBloc, MessagingState>(
    'an incoming message from the medium is appended as not fromMe',
    build: () => MessagingBloc(medium: medium),
    seed: () => const MessagingState(peerId: 'peer-1', messages: [], sending: false),
    act: (bloc) => medium.emitIncoming('peer-1', 'hi back'),
    wait: const Duration(milliseconds: 10),
    expect: () => [
      isA<MessagingState>().having(
        (s) => s.messages,
        'messages',
        [const ChatMessage(peerId: 'peer-1', text: 'hi back', fromMe: false)],
      ),
    ],
  );
}
