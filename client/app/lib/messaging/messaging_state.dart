import 'package:equatable/equatable.dart';

class ChatMessage extends Equatable {
  const ChatMessage({
    required this.peerId,
    required this.text,
    required this.fromMe,
  });

  final String peerId;
  final String text;
  final bool fromMe;

  @override
  List<Object?> get props => [peerId, text, fromMe];
}

class MessagingState extends Equatable {
  const MessagingState({
    this.peerId,
    this.messages = const [],
    this.sending = false,
    this.error,
  });

  final String? peerId;
  final List<ChatMessage> messages;
  final bool sending;
  final String? error;

  MessagingState copyWith({
    String? peerId,
    List<ChatMessage>? messages,
    bool? sending,
    String? error,
    bool clearError = false,
  }) {
    return MessagingState(
      peerId: peerId ?? this.peerId,
      messages: messages ?? this.messages,
      sending: sending ?? this.sending,
      error: clearError ? null : (error ?? this.error),
    );
  }

  @override
  List<Object?> get props => [peerId, messages, sending, error];
}
