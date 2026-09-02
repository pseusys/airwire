import 'package:flutter/material.dart';

void main() {
  runApp(const AirwireApp());
}

class AirwireApp extends StatelessWidget {
  const AirwireApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Airwire',
      home: Scaffold(
        appBar: AppBar(title: const Text('Airwire')),
        body: const Center(child: Text('Airwire prototype — coming online')),
      ),
    );
  }
}
