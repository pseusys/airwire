import 'dart:async';

import 'package:airwire_medium/airwire_medium.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'messaging_event.dart';
import 'messaging_state.dart';

class MessagingBloc extends Bloc<MessagingEvent, MessagingState> {
  MessagingBloc({required Medium medium})
      : _medium = medium,
        super(const MessagingState()) {
    on<ConversationStarted>(_onConversationStarted);
    on<MessageSubmitted>(_onMessageSubmitted);
    on<MessageReceived>(_onMessageReceived);

    _subscription = _medium.receive().listen(
      (event) => add(MessageReceived(event.$1, event.$2)),
    );
  }

  final Medium _medium;
  late final StreamSubscription<(String, String)> _subscription;

  void _onConversationStarted(
    ConversationStarted event,
    Emitter<MessagingState> emit,
  ) {
    emit(MessagingState(peerId: event.peerId, messages: const []));
  }

  Future<void> _onMessageSubmitted(
    MessageSubmitted event,
    Emitter<MessagingState> emit,
  ) async {
    final peerId = state.peerId;
    if (peerId == null) return;

    emit(state.copyWith(sending: true, clearError: true));
    try {
      await _medium.send(peerId, event.text);
      emit(state.copyWith(
        sending: false,
        messages: [
          ...state.messages,
          ChatMessage(peerId: peerId, text: event.text, fromMe: true),
        ],
      ));
    } catch (error) {
      emit(state.copyWith(sending: false, error: 'Send failed: $error'));
    }
  }

  void _onMessageReceived(
    MessageReceived event,
    Emitter<MessagingState> emit,
  ) {
    if (event.peerId != state.peerId) return;
    emit(state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(peerId: event.peerId, text: event.text, fromMe: false),
      ],
    ));
  }

  @override
  Future<void> close() {
    _subscription.cancel();
    _medium.dispose();
    return super.close();
  }
}
