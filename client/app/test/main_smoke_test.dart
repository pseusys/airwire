import 'package:airwire_app/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('app shows the placeholder home screen', (tester) async {
    await tester.pumpWidget(const AirwireApp());
    expect(find.text('Airwire prototype — coming online'), findsOneWidget);
  });
}
