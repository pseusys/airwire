import 'package:equatable/equatable.dart';

sealed class MessagingEvent extends Equatable {
  const MessagingEvent();

  @override
  List<Object?> get props => [];
}

class ConversationStarted extends MessagingEvent {
  const ConversationStarted(this.peerId);

  final String peerId;

  @override
  List<Object?> get props => [peerId];
}

class MessageSubmitted extends MessagingEvent {
  const MessageSubmitted(this.text);

  final String text;

  @override
  List<Object?> get props => [text];
}

class MessageReceived extends MessagingEvent {
  const MessageReceived(this.peerId, this.text);

  final String peerId;
  final String text;

  @override
  List<Object?> get props => [peerId, text];
}
