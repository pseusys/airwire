import 'package:airwire_medium/airwire_medium.dart';
import 'package:test/test.dart';

void main() {
  group('codeChallengeFor', () {
    test('matches the RFC 7636 Appendix B test vector', () {
      // https://www.rfc-editor.org/rfc/rfc7636#appendix-B
      const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
      const expectedChallenge = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
      expect(codeChallengeFor(verifier), equals(expectedChallenge));
    });
  });

  group('generateCodeVerifier', () {
    test('produces a URL-safe string within RFC 7636 length bounds', () {
      final verifier = generateCodeVerifier();
      expect(verifier.length, inInclusiveRange(43, 128));
      expect(RegExp(r'^[A-Za-z0-9\-_]+$').hasMatch(verifier), isTrue);
    });

    test('produces a different value each call', () {
      expect(generateCodeVerifier(), isNot(equals(generateCodeVerifier())));
    });
  });

  group('generateState', () {
    test('produces a URL-safe, non-empty string', () {
      final state = generateState();
      expect(state, isNotEmpty);
      expect(RegExp(r'^[A-Za-z0-9\-_]+$').hasMatch(state), isTrue);
    });
  });
}
