import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../messaging/messaging_bloc.dart';
import '../messaging/messaging_event.dart';
import '../messaging/messaging_state.dart';

class ConversationScreen extends StatefulWidget {
  const ConversationScreen({super.key});

  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit(BuildContext context) {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    context.read<MessagingBloc>().add(MessageSubmitted(text));
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Conversation')),
      body: BlocBuilder<MessagingBloc, MessagingState>(
        builder: (context, state) {
          return Column(
            children: [
              if (state.error != null)
                Container(
                  width: double.infinity,
                  color: Colors.red.shade100,
                  padding: const EdgeInsets.all(8),
                  child: Text(state.error!),
                ),
              Expanded(
                child: ListView.builder(
                  itemCount: state.messages.length,
                  itemBuilder: (context, index) {
                    final message = state.messages[index];
                    return Align(
                      alignment: message.fromMe
                          ? Alignment.centerRight
                          : Alignment.centerLeft,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 4,
                        ),
                        child: Text(message.text),
                      ),
                    );
                  },
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(8),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _controller,
                        onSubmitted: (_) => _submit(context),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.send),
                      onPressed: state.sending ? null : () => _submit(context),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
