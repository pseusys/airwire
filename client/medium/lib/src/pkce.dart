import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';

/// A fresh 32-byte random token, base64url-encoded with padding stripped
/// (RFC 7636 requires the unpadded form). Shared by the verifier and state
/// generators since both just need an unguessable, URL-safe string.
String _randomUrlSafeToken() {
  final random = Random.secure();
  final bytes = List<int>.generate(32, (_) => random.nextInt(256));
  return base64Url.encode(bytes).replaceAll('=', '');
}

/// RFC 7636 `code_verifier`: generated fresh per login attempt, persisted
/// until the redirect comes back so it can be replayed in the token exchange.
String generateCodeVerifier() => _randomUrlSafeToken();

/// Anti-CSRF `state` value for the OAuth redirect round trip. Same shape as
/// the code verifier (any unguessable URL-safe string works) but kept as a
/// separate function since the two serve different purposes.
String generateState() => _randomUrlSafeToken();

/// RFC 7636 `code_challenge` (S256 method): base64url(SHA-256(verifier)),
/// padding stripped.
String codeChallengeFor(String verifier) {
  final digest = sha256.convert(ascii.encode(verifier));
  return base64Url.encode(digest.bytes).replaceAll('=', '');
}
