# Protocol Core (Dart) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone, pure-Dart library implementing the data path of the [messaging protocol
spec](../specs/2026-08-27-messaging-protocol-design.md) §4 (message envelope, fragmentation,
disguise) — crypto primitives, the shared arithmetic coder, `ChunkEncoding` (Plain/Base64/Markov),
and pack/reassemble of a logical message into medium-sized wire fragments.

**Architecture:** A pure-Dart package (no Flutter dependency) at `protocol/`, importable later by
the Flutter app as `package:airwire_protocol/airwire_protocol.dart`. Each layer from the spec is one
file with one job: `crypto.dart` (primitives), `arithmetic.dart` (the shared coder), `encodings.dart`
(the `ChunkEncoding` interface plus Plain/Base64), `markov.dart` (the text disguise), `envelope.dart`
(pack/reassemble, tying the rest together). This is an **independent** Dart implementation of the
spec, not a port of `core/`'s Python — no wire or byte-level compatibility with `core/` is required
or attempted (only two instances of *this* Dart implementation ever need to talk to each other); the
arithmetic coder specifically is grounded directly against `core/sources/arithmetic.py`'s exact
algorithm since that one *is* worth porting faithfully (subtle, already-debugged bit manipulation).

**Tech Stack:** Dart 3 (records, pattern matching), [`package:cryptography`](https://pub.dev/packages/cryptography)
(X25519, XChaCha20-Poly1305, BLAKE2b — pure-Dart fallback on every platform), `package:test`.

**Scope boundary:** This plan covers §4 only — the envelope/fragmentation/disguise data path, given
a symmetric key from *outside* this module. The §5 handshake (certificate exchange, peer records,
session-key derivation) and §6 key rotation are follow-on plans, deferred deliberately so this one
stays reviewable and independently testable — `packMessage`/`Reassembler` below take a `SecretKey`
directly, with no opinion on how it was obtained. Image-steganography disguise (`SYNTHESIS_*`) is
also out of scope — a separate, largely independent porting effort (procedural texture generation,
patch library, PNG codec) that doesn't block anything here, deferred the same way medium-interface
and the Odnoklassniki wrapper were.

## Global Constraints

- Dart SDK `>=3.0.0 <4.0.0` (records required).
- `package:cryptography ^2.8.1` is the only runtime dependency; `package:test` is the only dev
  dependency for this plan.
- No Flutter dependency anywhere in `protocol/` — this package must build and test with plain `dart
  test`, no `flutter` toolchain involved.
- No floating-point arithmetic anywhere in the arithmetic-coder path (`arithmetic.dart`,
  `markov.dart`'s use of it) — `BigInt` throughout, matching `core/sources/arithmetic.py`'s own
  "zero floating point in the encode/decode-critical path" constraint and its documented reason
  (range values can exceed what a 64-bit float represents exactly).
- Every public class/function gets a doc comment (`///`) explaining *why*, not restating the
  signature — matching this repo's stated comment style (WHY over WHAT).

---

## Task 1: Package scaffolding

**Files:**
- Create: `protocol/pubspec.yaml`
- Create: `protocol/analysis_options.yaml`
- Create: `protocol/lib/airwire_protocol.dart`
- Create: `protocol/.gitignore`
- Test: `protocol/test/airwire_protocol_test.dart`

**Interfaces:**
- Produces: `protocolLibraryVersion` (a `String` constant), importable via
  `package:airwire_protocol/airwire_protocol.dart` — proves the package, its dependency
  resolution, and `dart test` all work end to end before any real logic is written.

- [ ] **Step 1: Write the failing test**

```dart
// protocol/test/airwire_protocol_test.dart
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:test/test.dart';

void main() {
  test('library exposes its version constant', () {
    expect(protocolLibraryVersion, equals('0.1.0'));
  });
}
```

- [ ] **Step 2: Create the package manifest**

```yaml
# protocol/pubspec.yaml
name: airwire_protocol
description: >
  Independent Dart implementation of airwire's serverless messaging protocol data path
  (envelope, fragmentation, disguise) -- see docs/superpowers/specs/2026-08-27-messaging-protocol-design.md.
version: 0.1.0
publish_to: 'none'

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  cryptography: ^2.8.1

dev_dependencies:
  test: ^1.25.0
  lints: ^4.0.0
```

```yaml
# protocol/analysis_options.yaml
include: package:lints/recommended.yaml
```

```
# protocol/.gitignore
.dart_tool/
.packages
pubspec.lock
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd protocol && dart pub get && dart test`
Expected: FAIL — `lib/airwire_protocol.dart` doesn't exist yet (import error), or
`protocolLibraryVersion` is undefined.

- [ ] **Step 4: Write minimal implementation**

```dart
// protocol/lib/airwire_protocol.dart
/// Version of this library, independent of the pubspec version (bump when the wire-relevant
/// parts of the protocol implementation change, not on every internal refactor).
const String protocolLibraryVersion = '0.1.0';
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd protocol && dart test`
Expected: PASS (1 test).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "chore: scaffold airwire_protocol Dart package"
```

---

## Task 2: Crypto primitives

**Files:**
- Create: `protocol/lib/src/crypto.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/crypto_test.dart`

**Interfaces:**
- Consumes: nothing (first real logic in the package).
- Produces (all in `package:airwire_protocol/src/crypto.dart`, re-exported from the barrel file):
  - `Uint8List randomBytes(int length)`
  - `class X25519KeyPair { SimpleKeyPair secretKeyPair; SimplePublicKey publicKey; }`
  - `Future<X25519KeyPair> generateX25519KeyPair()`
  - `Future<SecretKey> computeSharedSecret(SimpleKeyPair ownKeyPair, SimplePublicKey peerPublicKey)`
  - `class AeadResult { Uint8List ciphertext; Uint8List tag; }`
  - `Future<AeadResult> aeadEncrypt(SecretKey key, List<int> nonce, List<int> plaintext, {List<int> aad = const []})`
  - `Future<Uint8List> aeadDecrypt(SecretKey key, List<int> nonce, List<int> ciphertext, List<int> tag, {List<int> aad = const []})` — throws `SecretBoxAuthenticationError` on tag mismatch.
  - `Future<Uint8List> streamEncrypt(SecretKey key, List<int> nonce, List<int> plaintext)` — tagless, confidentiality only.
  - `Future<Uint8List> streamDecrypt(SecretKey key, List<int> nonce, List<int> ciphertext)`
  - `Future<Uint8List> deriveKey(List<List<int>> parts, {int length = 32})`
  - `const int aeadNonceSize = 24;`
  - `const int aeadTagSize = 16;`

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/crypto_test.dart
import 'dart:typed_data';
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:cryptography/cryptography.dart';
import 'package:test/test.dart';

void main() {
  test('randomBytes returns the requested length and is not all-zero', () async {
    final bytes = randomBytes(32);
    expect(bytes.length, equals(32));
    expect(bytes.any((b) => b != 0), isTrue);
  });

  test('two X25519 keypairs derive the same shared secret from both sides', () async {
    final alice = await generateX25519KeyPair();
    final bob = await generateX25519KeyPair();

    final aliceSecret = await computeSharedSecret(alice.secretKeyPair, bob.publicKey);
    final bobSecret = await computeSharedSecret(bob.secretKeyPair, alice.publicKey);

    expect(await aliceSecret.extractBytes(), equals(await bobSecret.extractBytes()));
  });

  test('AEAD round-trips and rejects a tampered tag', () async {
    final key = SecretKey(List<int>.filled(32, 7));
    final nonce = randomBytes(aeadNonceSize);
    final plaintext = 'hello airwire'.codeUnits;

    final result = await aeadEncrypt(key, nonce, plaintext);
    final decrypted = await aeadDecrypt(key, nonce, result.ciphertext, result.tag);
    expect(decrypted, equals(plaintext));

    final tamperedTag = Uint8List.fromList(result.tag)..[0] ^= 0xff;
    expect(
      () => aeadDecrypt(key, nonce, result.ciphertext, tamperedTag),
      throwsA(isA<SecretBoxAuthenticationError>()),
    );
  });

  test('stream cipher round-trips with no tag at all', () async {
    final key = SecretKey(List<int>.filled(32, 9));
    final nonce = randomBytes(aeadNonceSize);
    final plaintext = 'a short header blob'.codeUnits;

    final ciphertext = await streamEncrypt(key, nonce, plaintext);
    expect(ciphertext.length, equals(plaintext.length));
    final decrypted = await streamDecrypt(key, nonce, ciphertext);
    expect(decrypted, equals(plaintext));
  });

  test('deriveKey is deterministic and distinguishes different inputs', () async {
    final a = await deriveKey([
      'part-one'.codeUnits,
      'part-two'.codeUnits,
    ], length: 16);
    final aAgain = await deriveKey([
      'part-one'.codeUnits,
      'part-two'.codeUnits,
    ], length: 16);
    final b = await deriveKey([
      'part-one'.codeUnits,
      'part-three'.codeUnits,
    ], length: 16);

    expect(a, equals(aAgain));
    expect(a, isNot(equals(b)));
    expect(a.length, equals(16));
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/crypto_test.dart`
Expected: FAIL — `lib/src/crypto.dart` doesn't exist, none of the imported names resolve.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/crypto.dart
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

/// XChaCha20-Poly1305's extended nonce size -- chosen over plain ChaCha20's 12-byte nonce so
/// nonces can be generated randomly per message without a meaningful collision risk, matching
/// core/sources/crypto.py's Symmetric class.
const int aeadNonceSize = 24;

/// Poly1305 authentication tag size, kept as its own constant since header encryption (envelope.dart)
/// deliberately omits it -- see the protocol spec's §4 "why the header has no full tag".
const int aeadTagSize = 16;

final Random _secureRandom = Random.secure();

/// Cryptographically-secure random bytes, for nonces, ephemeral keys, and rotation material.
Uint8List randomBytes(int length) {
  final bytes = Uint8List(length);
  for (var i = 0; i < length; i++) {
    bytes[i] = _secureRandom.nextInt(256);
  }
  return bytes;
}

/// An X25519 keypair, kept together since every handshake operation needs both halves at once.
class X25519KeyPair {
  final SimpleKeyPair secretKeyPair;
  final SimplePublicKey publicKey;

  const X25519KeyPair(this.secretKeyPair, this.publicKey);
}

/// Generates a fresh, conversation-scoped X25519 keypair (protocol spec §5: ephemeral, never
/// reused across sessions, so a future key compromise can't retroactively expose other chats).
Future<X25519KeyPair> generateX25519KeyPair() async {
  final keyPair = await X25519().newKeyPair();
  final publicKey = await keyPair.extractPublicKey();
  return X25519KeyPair(keyPair, publicKey);
}

/// Raw ECDH: the shared secret two sides land on from their own private key and the other's
/// public key. Callers are responsible for the canonical (sorted) ordering protocol spec §5
/// requires when deriving anything further from this, so both sides agree regardless of who
/// computed first.
Future<SecretKey> computeSharedSecret(SimpleKeyPair ownKeyPair, SimplePublicKey peerPublicKey) {
  return X25519().sharedSecretKey(keyPair: ownKeyPair, remotePublicKey: peerPublicKey);
}

/// The two halves of an AEAD operation's output, kept separate rather than concatenated -- the
/// protocol's wire format (envelope.dart) carries `data_nonce`/`data_tag` as distinct header
/// fields, not a combined blob.
class AeadResult {
  final Uint8List ciphertext;
  final Uint8List tag;

  const AeadResult(this.ciphertext, this.tag);
}

/// XChaCha20-Poly1305 AEAD encryption, confidentiality and integrity together -- the protocol's
/// data-phase primitive (protocol spec §4, §8).
Future<AeadResult> aeadEncrypt(
  SecretKey key,
  List<int> nonce,
  List<int> plaintext, {
  List<int> aad = const [],
}) async {
  final box = await Xchacha20.poly1305Aead().encrypt(
    plaintext,
    secretKey: key,
    nonce: nonce,
    aad: aad,
  );
  return AeadResult(Uint8List.fromList(box.cipherText), Uint8List.fromList(box.mac.bytes));
}

/// Inverse of [aeadEncrypt]. Throws [SecretBoxAuthenticationError] if `tag` doesn't match --
/// the fail-closed behavior every part of this protocol relies on for tamper detection.
Future<Uint8List> aeadDecrypt(
  SecretKey key,
  List<int> nonce,
  List<int> ciphertext,
  List<int> tag, {
  List<int> aad = const [],
}) async {
  final box = SecretBox(ciphertext, nonce: nonce, mac: Mac(tag));
  final plaintext = await Xchacha20.poly1305Aead().decrypt(box, secretKey: key, aad: aad);
  return Uint8List.fromList(plaintext);
}

/// XChaCha20 as a plain stream cipher, no Poly1305 step -- confidentiality only, no tag. Used
/// for header encryption (protocol spec §4): most header fields fail closed indirectly via the
/// downstream data-AEAD check, so paying for a second full tag isn't needed there.
Future<Uint8List> streamEncrypt(SecretKey key, List<int> nonce, List<int> plaintext) async {
  final box = await Xchacha20(macAlgorithm: MacAlgorithm.empty).encrypt(
    plaintext,
    secretKey: key,
    nonce: nonce,
  );
  return Uint8List.fromList(box.cipherText);
}

/// Inverse of [streamEncrypt].
Future<Uint8List> streamDecrypt(SecretKey key, List<int> nonce, List<int> ciphertext) async {
  final box = SecretBox(ciphertext, nonce: nonce, mac: Mac.empty);
  final plaintext = await Xchacha20(macAlgorithm: MacAlgorithm.empty).decrypt(
    box,
    secretKey: key,
  );
  return Uint8List.fromList(plaintext);
}

/// Deterministically derives a `length`-byte value from `parts` via BLAKE2b, mirroring
/// core/sources/crypto.py's `derive_key` (sequential hash of concatenated parts -- safe here for
/// the same reason it is there: every call site guarantees `parts` uniquely determines whatever's
/// being derived, e.g. by including a fixed domain-separation label as one of the parts).
Future<Uint8List> deriveKey(List<List<int>> parts, {int length = 32}) async {
  final combined = <int>[];
  for (final part in parts) {
    combined.addAll(part);
  }
  final hash = await Blake2b(hashLengthInBytes: length).hash(combined);
  return Uint8List.fromList(hash.bytes);
}
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
/// Version of this library, independent of the pubspec version (bump when the wire-relevant
/// parts of the protocol implementation change, not on every internal refactor).
const String protocolLibraryVersion = '0.1.0';

export 'src/crypto.dart';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/crypto_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add X25519/XChaCha20-Poly1305/BLAKE2b crypto primitives"
```

---

## Task 3: Arithmetic coder primitives

**Files:**
- Create: `protocol/lib/src/arithmetic.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/arithmetic_test.dart`

**Interfaces:**
- Consumes: nothing (self-contained; ported directly from `core/sources/arithmetic.py`, verified
  line-by-line against that file, not reconstructed from memory).
- Produces:
  - `class BitCursor { BitCursor(List<int> data); int remaining(); BigInt peek(int n); void consume(int n); }`
  - `class BitAccumulator { BitAccumulator(int targetBytes); int remaining(); bool done(); void append(BigInt value, int width, int available); Uint8List finish(); }`
  - `class CandidateRange<T> { T candidate; BigInt low; BigInt high; }`
  - `(List<CandidateRange<T>>, BigInt, BigInt, int) candidateRanges<T>(BigInt low, BigInt high, int width, List<(T, int)> candidates, int budget)`
  - `int commonLeadingBits(BigInt low, BigInt high, int width)`
  - `(BigInt, BigInt, int) stripTopBits(BigInt low, BigInt high, int width, int n)`
  - `BigInt topBits(BigInt value, int width, int n)`

- [ ] **Step 1: Write the failing tests**

These exercise the primitives directly, mirroring what `core/tests` verifies for the Python
original: a full encode/decode round trip through a tiny synthetic weighted-candidate walk (the
same shape `markov.dart` will use in Task 5, but without needing a real model yet), plus the
individual bit-manipulation helpers.

```dart
// protocol/test/arithmetic_test.dart
import 'dart:typed_data';
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:test/test.dart';

/// A minimal two-candidate "walk": each step picks 'A' (weight 3) or 'B' (weight 1) from the
/// same fixed candidate list every time -- enough to exercise candidateRanges/commonLeadingBits/
/// stripTopBits/BitCursor/BitAccumulator together without needing markov.dart yet.
List<(String, int)> _candidates() => [('A', 3), ('B', 1)];

String _encode(List<int> data) {
  final cursor = BitCursor(data);
  var low = BigInt.zero, high = BigInt.one;
  var width = 1;
  final words = StringBuffer();

  while (cursor.remaining() > 0) {
    final budget = cursor.remaining();
    final (ranges, l, h, w) = candidateRanges(low, high, width, _candidates(), budget);
    low = l; high = h; width = w;
    final peeked = cursor.peek(width);
    final chosen = ranges.firstWhere((r) => r.low <= peeked && peeked <= r.high);
    words.write(chosen.candidate);
    low = chosen.low; high = chosen.high;
    final common = commonLeadingBits(low, high, width);
    if (common > 0) {
      cursor.consume(common > cursor.remaining() ? cursor.remaining() : common);
      final (sl, sh, sw) = stripTopBits(low, high, width, common);
      low = sl; high = sh; width = sw;
    }
  }
  return words.toString();
}

Uint8List _decode(String words, int targetBytes) {
  final accumulator = BitAccumulator(targetBytes);
  var low = BigInt.zero, high = BigInt.one;
  var width = 1;

  for (final char in words.split('')) {
    if (accumulator.done()) break;
    final (ranges, l, h, w) = candidateRanges(low, high, width, _candidates(), accumulator.remaining());
    low = l; high = h; width = w;
    final match = ranges.firstWhere((r) => r.candidate == char);
    low = match.low; high = match.high;
    final common = commonLeadingBits(low, high, width);
    if (common > 0) {
      accumulator.append(low, width, common);
      final (sl, sh, sw) = stripTopBits(low, high, width, common);
      low = sl; high = sh; width = sw;
    }
  }
  return accumulator.finish();
}

void main() {
  test('encode then decode recovers the original bytes, across several lengths', () {
    for (final original in [
      <int>[],
      [0],
      [255],
      [0, 1, 2, 3, 4, 5],
      List<int>.generate(64, (i) => (i * 37) % 256),
    ]) {
      final words = _encode(original);
      final recovered = _decode(words, original.length);
      expect(recovered, equals(Uint8List.fromList(original)), reason: 'input: $original');
    }
  });

  test('encoding the same bytes twice is deterministic', () {
    final data = [1, 2, 3, 4, 5];
    expect(_encode(data), equals(_encode(data)));
  });

  test('BitCursor peeks without consuming, and reports remaining correctly', () {
    final cursor = BitCursor([0xff, 0x00]);
    expect(cursor.remaining(), equals(16));
    expect(cursor.peek(4), equals(BigInt.from(0xf)));
    expect(cursor.remaining(), equals(16));
    cursor.consume(4);
    expect(cursor.remaining(), equals(12));
    expect(cursor.peek(4), equals(BigInt.from(0xf)));
  });

  test('BitAccumulator.finish throws if the target was not fully reached', () {
    final accumulator = BitAccumulator(1);
    accumulator.append(BigInt.from(1), 1, 1);
    expect(() => accumulator.finish(), throwsStateError);
  });

  test('stripTopBits removes exactly n leading bits from both bounds', () {
    final (low, high, width) = stripTopBits(BigInt.from(0xb), BigInt.from(0xf), 4, 2);
    expect(width, equals(2));
    expect(low, equals(BigInt.from(0x3)));
    expect(high, equals(BigInt.from(0x3)));
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/arithmetic_test.dart`
Expected: FAIL — `lib/src/arithmetic.dart` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/arithmetic.dart
import 'dart:typed_data';

/// Smallest non-negative `extra` such that `(denominator << extra) >= numerator` -- an exact
/// integer computation of `ceil(log2(numerator / denominator))`, avoiding any BigInt-to-double
/// conversion. core/sources/arithmetic.py uses `math.log2` for this same spot; the earlier
/// TypeScript port (web-demo/) already found and fixed the float-precision risk that creates
/// (a ratio landing extremely close to a power of two can tip a float-based `ceil()` the wrong
/// way) -- this reuses that same fix rather than reintroducing the risk.
int _ceilLog2Ratio(BigInt numerator, BigInt denominator) {
  if (numerator <= denominator) return 0;
  var extra = 0;
  var scaled = denominator;
  while (scaled < numerator) {
    scaled = scaled << 1;
    extra++;
  }
  return extra;
}

/// Widens `[low, high]` (a `width`-bit range) with extra binary digits, up to `maxDigits` total,
/// until it has at least `desiredRangeLen` distinct positions -- or as close as `maxDigits` allows.
(BigInt, BigInt, int) _addDigitsToRange(
  BigInt low,
  BigInt high,
  int width,
  BigInt desiredRangeLen,
  int maxDigits,
) {
  final rangePossibleValues = high - low + BigInt.one;
  if (desiredRangeLen <= rangePossibleValues) {
    return (low, high, width);
  }
  var extra = _ceilLog2Ratio(desiredRangeLen, rangePossibleValues);
  if (width + extra > maxDigits) {
    extra = maxDigits - width;
  }
  if (extra <= 0) {
    return (low, high, width);
  }
  final shiftedLow = low << extra;
  final shiftedHigh = (high << extra) | ((BigInt.one << extra) - BigInt.one);
  return (shiftedLow, shiftedHigh, width + extra);
}

/// One candidate's sub-interval within a subdivided range -- the output of [candidateRanges].
class CandidateRange<T> {
  final T candidate;
  final BigInt low;
  final BigInt high;

  const CandidateRange(this.candidate, this.low, this.high);
}

/// Subdivides `[low, high]` (a `width`-bit range) among `candidates`, proportionally to their
/// integer weights, growing the range (up to `budget` bits) first if it isn't wide enough to give
/// every candidate at least one position -- candidates that still don't fit even then are simply
/// unreachable at this step. Pure integer arithmetic throughout, ported directly from
/// core/sources/arithmetic.py's `candidate_ranges`.
(List<CandidateRange<T>>, BigInt, BigInt, int) candidateRanges<T>(
  BigInt low,
  BigInt high,
  int width,
  List<(T, int)> candidates,
  int budget,
) {
  var denominator = BigInt.zero;
  for (final (_, weight) in candidates) {
    denominator += BigInt.from(weight);
  }
  final (widenedLow, widenedHigh, widenedWidth) =
      _addDigitsToRange(low, high, width, denominator, budget);
  low = widenedLow;
  high = widenedHigh;
  width = widenedWidth;
  final rangeSize = high - low + BigInt.one;
  final base = low;

  final boundaries = <(T, BigInt)>[];
  var cumulative = BigInt.zero;
  for (final (candidate, weight) in candidates) {
    cumulative += BigInt.from(weight);
    boundaries.add((candidate, (cumulative * rangeSize) ~/ denominator - BigInt.one));
  }
  final lastCandidate = boundaries.last.$1;
  boundaries[boundaries.length - 1] = (lastCandidate, rangeSize - BigInt.one);

  final result = <CandidateRange<T>>[];
  var cursor = BigInt.zero;
  for (final (candidate, end) in boundaries) {
    if (end >= cursor) {
      result.add(CandidateRange(candidate, cursor + base, end + base));
      cursor = end + BigInt.one;
    }
  }
  return (result, low, high, width);
}

/// How many leading bits `low` and `high` currently agree on -- those bits are "locked in" and
/// can be popped off both the interval and the source bit cursor (renormalization).
int commonLeadingBits(BigInt low, BigInt high, int width) {
  var count = 0;
  while (width - count >= 1 &&
      ((low >> (width - count - 1)) & BigInt.one) ==
          ((high >> (width - count - 1)) & BigInt.one)) {
    count++;
  }
  return count;
}

/// Drops the top `n` bits from both bounds of a `width`-bit range.
(BigInt, BigInt, int) stripTopBits(BigInt low, BigInt high, int width, int n) {
  if (n >= width) {
    return (BigInt.zero, BigInt.zero, 0);
  }
  final mask = (BigInt.one << (width - n)) - BigInt.one;
  return (low & mask, high & mask, width - n);
}

/// The top `n` bits of a `width`-bit `value`.
BigInt topBits(BigInt value, int width, int n) {
  if (n == 0) return BigInt.zero;
  return (value >> (width - n)) & ((BigInt.one << n) - BigInt.one);
}

/// Reads a fixed byte buffer as a peekable/consumable bit stream, MSB-first.
class BitCursor {
  final BigInt _value;
  final int _total;
  int _pos = 0;

  BitCursor(List<int> data)
      : _value = data.fold(BigInt.zero, (acc, byte) => (acc << 8) | BigInt.from(byte)),
        _total = data.length * 8;

  int remaining() => _total - _pos;

  BigInt peek(int n) {
    if (n == 0) return BigInt.zero;
    final shift = _total - _pos - n;
    return (_value >> shift) & ((BigInt.one << n) - BigInt.one);
  }

  void consume(int n) {
    _pos += n;
  }
}

/// The write-side counterpart to [BitCursor]: accumulates decoded bits up to a fixed target byte
/// count, then renders them as bytes. [finish] throws if called before the target is reached --
/// a short decode means the caller didn't feed it enough candidate selections.
class BitAccumulator {
  BigInt _value = BigInt.zero;
  int _bits = 0;
  final int _targetBytes;
  final int _targetBits;

  BitAccumulator(int targetBytes)
      : _targetBytes = targetBytes,
        _targetBits = targetBytes * 8;

  int remaining() => _targetBits - _bits;

  bool done() => _bits >= _targetBits;

  void append(BigInt value, int width, int available) {
    final r = remaining();
    final take = available < r ? available : r;
    _value = (_value << take) | topBits(value, width, take);
    _bits += take;
  }

  Uint8List finish() {
    if (_bits != _targetBits) {
      throw StateError('Only accumulated $_bits/$_targetBits bits!');
    }
    if (_targetBytes == 0) return Uint8List(0);
    final bytes = Uint8List(_targetBytes);
    var v = _value;
    for (var i = _targetBytes - 1; i >= 0; i--) {
      bytes[i] = (v & BigInt.from(0xff)).toInt();
      v = v >> 8;
    }
    return bytes;
  }
}
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
export 'src/arithmetic.dart';
```

(Append this line after the existing `export 'src/crypto.dart';` line from Task 2.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/arithmetic_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: port the shared arithmetic coder from core/sources/arithmetic.py"
```

---

## Task 4: ChunkEncoding interface, Plain and Base64

**Files:**
- Create: `protocol/lib/src/encodings.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/encodings_test.dart`

**Interfaces:**
- Consumes: nothing directly (Plain/Base64 don't need the arithmetic coder).
- Produces:
  - `class DecodeResult { Uint8List plaintext; int consumedWireBytes; }`
  - `abstract class ChunkEncoding { int get identifier; Iterable<Uint8List> encodeAtoms(List<int> data, List<int> nonce); DecodeResult decode(List<int> wire, int length, List<int> nonce); int minimumBudgetForHeader(int headerCiphertextSize); }`
  - `class PlainEncoding implements ChunkEncoding` and `const plainEncoding = PlainEncoding();`
  - `class Base64Encoding implements ChunkEncoding` and `const base64Encoding = Base64Encoding();`
  - `const int chunkEncodingPlain = 0;`
  - `const int chunkEncodingBase64 = 1;`

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/encodings_test.dart
import 'dart:convert';
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:test/test.dart';

void main() {
  group('PlainEncoding', () {
    test('round-trips arbitrary bytes, one atom per byte', () {
      final data = [0, 1, 2, 255, 128];
      final atoms = plainEncoding.encodeAtoms(data, const []).toList();
      expect(atoms.length, equals(data.length));
      for (var i = 0; i < data.length; i++) {
        expect(atoms[i], equals([data[i]]));
      }
      final wire = atoms.expand((a) => a).toList();
      final result = plainEncoding.decode(wire, data.length, const []);
      expect(result.plaintext, equals(data));
      expect(result.consumedWireBytes, equals(data.length));
    });

    test('minimumBudgetForHeader is 1:1', () {
      expect(plainEncoding.minimumBudgetForHeader(50), equals(50));
    });
  });

  group('Base64Encoding', () {
    test('round-trips arbitrary bytes, one atom per 3-byte group', () {
      final data = List<int>.generate(10, (i) => i * 17 % 256);
      final atoms = base64Encoding.encodeAtoms(data, const []).toList();
      expect(atoms.length, equals(4)); // 10 bytes -> 4 groups of up to 3 bytes each
      final wire = atoms.expand((a) => a).toList();
      final result = base64Encoding.decode(wire, data.length, const []);
      expect(result.plaintext, equals(data));
      expect(result.consumedWireBytes, equals(wire.length));
    });

    test('a non-multiple-of-3 length pads correctly, still round-trips', () {
      final data = [1, 2, 3, 4, 5]; // 5 bytes -> groups of 3 then 2
      final wire = base64Encoding.encodeAtoms(data, const []).expand((a) => a).toList();
      final result = base64Encoding.decode(wire, data.length, const []);
      expect(result.plaintext, equals(data));
    });

    test('minimumBudgetForHeader matches the exact base64 expansion formula', () {
      // ceil(size / 3) * 4
      expect(base64Encoding.minimumBudgetForHeader(3), equals(4));
      expect(base64Encoding.minimumBudgetForHeader(4), equals(8));
      expect(base64Encoding.minimumBudgetForHeader(50), equals(base64.encode(List.filled(50, 0)).length));
    });
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/encodings_test.dart`
Expected: FAIL — `lib/src/encodings.dart` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/encodings.dart
import 'dart:convert';
import 'dart:typed_data';

const int chunkEncodingPlain = 0;
const int chunkEncodingBase64 = 1;
// chunkEncodingMarkov is defined in markov.dart (Task 5) -- kept there since it's the encoding
// that owns the identifier, not this shared-interface file.

/// The result of decoding the *front* of an already-disguise-encoded wire byte stream: the
/// plaintext bytes recovered, and how many wire bytes were actually consumed to get them. The
/// consumed count matters because header and data are two independent, chained disguise
/// operations sharing one wire fragment (protocol spec §4, "Header vs. data disguise") -- for
/// Plain/Base64 it's a direct formula, for Markov (Task 5) it's however many words the arithmetic
/// walk actually needed.
class DecodeResult {
  final Uint8List plaintext;
  final int consumedWireBytes;

  const DecodeResult(this.plaintext, this.consumedWireBytes);
}

/// A pluggable strategy for turning plaintext bytes into the bytes that actually travel on the
/// wire, and back -- protocol spec §4's "disguise" layer. `nonce` is the message's own data
/// nonce (already unique and transmitted regardless of encoding); most implementations ignore it,
/// same as most ignore `length` on [decode] -- one that needs a per-message seed can derive it
/// from here for free.
abstract class ChunkEncoding {
  int get identifier;

  /// Yields indivisible output atoms that, concatenated in order, encode all of `data`.
  Iterable<Uint8List> encodeAtoms(List<int> data, List<int> nonce);

  /// Decodes exactly `length` plaintext bytes from the front of `wire`. See [DecodeResult] for
  /// why the consumed-byte count is part of the return value.
  DecodeResult decode(List<int> wire, int length, List<int> nonce);

  /// The smallest wire-byte budget under which this encoding can safely disguise a
  /// `headerCiphertextSize`-byte input as a single, non-fragmenting unit -- see protocol spec §4,
  /// "Minimum fragment budget for header disguise". Plain and Base64 have exact, predictable
  /// answers; Markov (Task 5) does not and returns a conservative heuristic instead.
  int minimumBudgetForHeader(int headerCiphertextSize);
}

/// Identity transform: chunk payloads are the raw bytes, unmodified. Ported from
/// core/sources/encodings.py's `PlainEncoding`.
class PlainEncoding implements ChunkEncoding {
  const PlainEncoding();

  @override
  int get identifier => chunkEncodingPlain;

  @override
  Iterable<Uint8List> encodeAtoms(List<int> data, List<int> nonce) sync* {
    for (final byte in data) {
      yield Uint8List.fromList([byte]);
    }
  }

  @override
  DecodeResult decode(List<int> wire, int length, List<int> nonce) {
    final slice = wire.sublist(0, length);
    return DecodeResult(Uint8List.fromList(slice), length);
  }

  @override
  int minimumBudgetForHeader(int headerCiphertextSize) => headerCiphertextSize;
}

const PlainEncoding plainEncoding = PlainEncoding();

/// Base64 transform, one 3-byte group (4 output characters, always -- base64 pads only the final
/// partial group) per atom. Ported from core/sources/encodings.py's `Base64Encoding`.
class Base64Encoding implements ChunkEncoding {
  const Base64Encoding();

  @override
  int get identifier => chunkEncodingBase64;

  @override
  Iterable<Uint8List> encodeAtoms(List<int> data, List<int> nonce) sync* {
    for (var i = 0; i < data.length; i += 3) {
      final group = data.sublist(i, i + 3 > data.length ? data.length : i + 3);
      yield Uint8List.fromList(utf8.encode(base64.encode(group)));
    }
  }

  @override
  DecodeResult decode(List<int> wire, int length, List<int> nonce) {
    final wireLength = minimumBudgetForHeader(length);
    final slice = wire.sublist(0, wireLength);
    final decoded = base64.decode(utf8.decode(slice));
    return DecodeResult(Uint8List.fromList(decoded), wireLength);
  }

  @override
  int minimumBudgetForHeader(int headerCiphertextSize) {
    return ((headerCiphertextSize + 2) ~/ 3) * 4;
  }
}

const Base64Encoding base64Encoding = Base64Encoding();
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
export 'src/encodings.dart';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/encodings_test.dart`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add ChunkEncoding interface with Plain and Base64"
```

---

## Task 5: Markov-chain text disguise

**Files:**
- Create: `protocol/lib/src/markov.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/markov_test.dart`

**Interfaces:**
- Consumes: `BitCursor`, `BitAccumulator`, `candidateRanges`, `commonLeadingBits`, `stripTopBits`
  (Task 3, `arithmetic.dart`); `ChunkEncoding`, `DecodeResult` (Task 4, `encodings.dart`).
- Produces:
  - `class MarkovModel { int stateSize; Map<String, List<(String, int)>> chain; }`
  - `MarkovModel.fromJson(Map<String, dynamic> json)` — accepts the same shape
    `core/sources/data/markov_<language>.json` uses (`state_size`, `chain`), so a real frozen model
    can be loaded later without changing this class; not exercised by this task's tests, which use
    a small synthetic model instead.
  - `class MarkovEncoding implements ChunkEncoding { MarkovEncoding(MarkovModel model); }`
  - `const int chunkEncodingMarkov = 2;`
  - `const String markovBeginToken = '___BEGIN__';`
  - `const String markovEndToken = '___END__';`

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/markov_test.dart
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:test/test.dart';

/// A tiny synthetic bigram model -- enough branching to be a real exercise of the arithmetic
/// coder without needing a real frozen corpus file. Mirrors the shape
/// core/sources/markov.py's tests use a synthetic low-branching-factor model for the same reason.
MarkovModel _syntheticModel() {
  const begin = '___BEGIN__';
  const end = '___END__';
  return MarkovModel(
    stateSize: 2,
    chain: {
      '$begin $begin': [('the', 5), ('a', 3), (end, 1)],
      '$begin the': [('cat', 4), ('dog', 2), (end, 1)],
      'the cat': [('sat', 3), ('ran', 3), (end, 1)],
      'the dog': [('sat', 3), ('ran', 3), (end, 1)],
      '$begin a': [('cat', 2), ('dog', 2), (end, 1)],
      'a cat': [('sat', 2), (end, 2)],
      'a dog': [('ran', 2), (end, 2)],
      'cat sat': [(end, 1)],
      'cat ran': [(end, 1)],
      'dog sat': [(end, 1)],
      'dog ran': [(end, 1)],
    },
  );
}

void main() {
  test('encode then decode round-trips, across several byte lengths', () {
    final encoding = MarkovEncoding(_syntheticModel());
    for (final original in [
      <int>[],
      [0],
      [1, 2, 3],
      List<int>.generate(20, (i) => (i * 53) % 256),
    ]) {
      final wire = encoding.encodeAtoms(original, const []).expand((a) => a).toList();
      final result = encoding.decode(wire, original.length, const []);
      expect(result.plaintext, equals(original), reason: 'input: $original');
      expect(result.consumedWireBytes, equals(wire.length));
    }
  });

  test('output is space-separated words drawn from the model', () {
    final encoding = MarkovEncoding(_syntheticModel());
    final wire = encoding.encodeAtoms([42, 17], const []).expand((a) => a).toList();
    final text = String.fromCharCodes(wire);
    for (final word in text.trim().split(RegExp(r'\s+'))) {
      expect(
        ['the', 'a', 'cat', 'dog', 'sat', 'ran', '___END__'].contains(word),
        isTrue,
        reason: 'unexpected word: $word',
      );
    }
  });

  test('decode leaves the remainder of `wire` untouched when more trails it', () {
    // Simulates a header-then-data chained decode (protocol spec §4): encode two independent
    // messages back to back with no delimiter, decode the first with its own known length, and
    // confirm the leftover wire bytes are exactly the second message's encoding.
    final encoding = MarkovEncoding(_syntheticModel());
    final first = [9];
    final second = [200, 201];
    final firstWire = encoding.encodeAtoms(first, const []).expand((a) => a).toList();
    final secondWire = encoding.encodeAtoms(second, const []).expand((a) => a).toList();
    final combined = [...firstWire, ...secondWire];

    final firstResult = encoding.decode(combined, first.length, const []);
    expect(firstResult.plaintext, equals(first));
    expect(firstResult.consumedWireBytes, equals(firstWire.length));

    final remainder = combined.sublist(firstResult.consumedWireBytes);
    final secondResult = encoding.decode(remainder, second.length, const []);
    expect(secondResult.plaintext, equals(second));
  });

  test('a word that is not a valid continuation fails closed', () {
    final encoding = MarkovEncoding(_syntheticModel());
    final wire = 'the elephant '.codeUnits;
    expect(() => encoding.decode(wire, 1, const []), throwsFormatException);
  });

  test('minimumBudgetForHeader is a conservative multiplier, not a formula', () {
    final encoding = MarkovEncoding(_syntheticModel());
    expect(encoding.minimumBudgetForHeader(50), greaterThan(50));
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/markov_test.dart`
Expected: FAIL — `lib/src/markov.dart` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/markov.dart
import 'dart:convert';
import 'dart:typed_data';

import 'arithmetic.dart';
import 'encodings.dart';

const int chunkEncodingMarkov = 2;

const String markovBeginToken = '___BEGIN__';
const String markovEndToken = '___END__';

/// Conservative safety margin for [MarkovEncoding.minimumBudgetForHeader] -- see protocol spec
/// §4, "Minimum fragment budget for header disguise": an exact worst-case expansion bound isn't
/// practically computable (a corpus-driven chain could in principle force many low-information
/// word choices in a row), so this multiplier is a reasoned estimate, not a proven bound. Revisit
/// empirically against a real frozen model if it ever needs tightening.
const int _headerExpansionSafetyFactor = 12;

/// A frozen Markov chain: for every state (the last `stateSize` words chosen, joined with a NUL
/// separator that can't appear in a real word), the candidate next words and their corpus-frequency
/// weights. Matches the shape of core/sources/data/markov_<language>.json (`state_size`, `chain`)
/// so a real frozen model can be loaded via [MarkovModel.fromJson] without any change here --
/// training/downloading that data is out of scope for this plan (see core/sources/corpus.py,
/// core/scripts/model.py for how core/ produces it).
class MarkovModel {
  final int stateSize;
  final Map<String, List<(String, int)>> chain;

  const MarkovModel({required this.stateSize, required this.chain});

  factory MarkovModel.fromJson(Map<String, dynamic> json) {
    final stateSize = json['state_size'] as int;
    final rawChain = jsonDecode(json['chain'] as String) as List<dynamic>;
    final chain = <String, List<(String, int)>>{};
    for (final entry in rawChain) {
      final stateWords = (entry[0] as List<dynamic>).cast<String>();
      final candidates = entry[1] as Map<String, dynamic>;
      final sorted = candidates.entries.map((e) => (e.key, e.value as int)).toList()
        ..sort((a, b) => a.$1.compareTo(b.$1));
      chain[stateWords.join(' ')] = sorted;
    }
    return MarkovModel(stateSize: stateSize, chain: chain);
  }
}

/// Disguises plaintext bytes as plausible natural-language text by walking a frozen Markov chain,
/// using the shared arithmetic coder (arithmetic.dart) to pick which words represent which bits.
/// Ported from core/sources/markov.py's `MarkovEncoding` -- see that file's docstring for the full
/// design rationale (why a general-purpose entropy-coding library didn't fit, the self-terminating
/// walk, no floating point anywhere in this path).
class MarkovEncoding implements ChunkEncoding {
  final MarkovModel model;
  late final String _beginState;

  MarkovEncoding(this.model) {
    _beginState = List.filled(model.stateSize, markovBeginToken).join(' ');
  }

  @override
  int get identifier => chunkEncodingMarkov;

  List<(String, int)> _candidatesFor(String state) {
    final candidates = model.chain[state];
    if (candidates == null) {
      throw FormatException('No transitions recorded for state "$state" -- the model may be truncated!');
    }
    return candidates;
  }

  String _nextState(String state, String word, List<String> stateWords) {
    if (word == markovEndToken) return _beginState;
    final next = [...stateWords.sublist(1), word];
    return next.join(' ');
  }

  List<String> _stateWords(String state) => state.split(' ');

  @override
  Iterable<Uint8List> encodeAtoms(List<int> data, List<int> nonce) sync* {
    final cursor = BitCursor(data);
    var low = BigInt.zero, high = BigInt.one;
    var width = 1;
    var state = _beginState;

    while (cursor.remaining() > 0) {
      final budget = cursor.remaining();
      final candidates = _candidatesFor(state);
      final (ranges, l, h, w) = candidateRanges(low, high, width, candidates, budget);
      low = l; high = h; width = w;
      final peeked = cursor.peek(width);
      final chosen = ranges.firstWhere((r) => r.low <= peeked && peeked <= r.high);
      yield Uint8List.fromList(utf8.encode('${chosen.candidate} '));
      state = _nextState(state, chosen.candidate, _stateWords(state));
      low = chosen.low; high = chosen.high;
      final common = commonLeadingBits(low, high, width);
      if (common > 0) {
        cursor.consume(common > cursor.remaining() ? cursor.remaining() : common);
        final (sl, sh, sw) = stripTopBits(low, high, width, common);
        low = sl; high = sh; width = sw;
      }
    }
  }

  @override
  DecodeResult decode(List<int> wire, int length, List<int> nonce) {
    late String text;
    try {
      text = utf8.decode(wire);
    } on FormatException {
      rethrow;
    }
    final words = text.trimLeft().split(RegExp(r'(?<=\s)'));
    // Each element of `words` retains its trailing whitespace (the split lookbehind keeps the
    // separator attached to the word before it), so re-joining consumed words below reproduces
    // the exact original wire bytes -- needed to compute `consumedWireBytes` correctly.

    final accumulator = BitAccumulator(length);
    var low = BigInt.zero, high = BigInt.one;
    var width = 1;
    var state = _beginState;
    var consumedChars = 0;

    for (final rawWord in words) {
      if (accumulator.done()) break;
      final word = rawWord.trim();
      if (word.isEmpty) continue;
      final candidates = _candidatesFor(state);
      final (ranges, l, h, w) = candidateRanges(low, high, width, candidates, accumulator.remaining());
      low = l; high = h; width = w;
      final matches = ranges.where((r) => r.candidate == word);
      if (matches.isEmpty) {
        throw FormatException('"$word" is not a valid continuation at this point in the Markov walk!');
      }
      final match = matches.first;
      low = match.low; high = match.high;
      state = _nextState(state, word, _stateWords(state));
      consumedChars += rawWord.length;
      final common = commonLeadingBits(low, high, width);
      if (common > 0) {
        accumulator.append(low, width, common);
        final (sl, sh, sw) = stripTopBits(low, high, width, common);
        low = sl; high = sh; width = sw;
      }
    }

    final consumedBytes = utf8.encode(text.substring(0, consumedChars)).length;
    return DecodeResult(accumulator.finish(), consumedBytes);
  }

  @override
  int minimumBudgetForHeader(int headerCiphertextSize) {
    return headerCiphertextSize * _headerExpansionSafetyFactor;
  }
}
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
export 'src/markov.dart';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/markov_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: port the Markov-chain text disguise from core/sources/markov.py"
```

---

## Task 6: Envelope packing

> **Note on scope, decided while writing this task:** the protocol spec originally proposed
> deriving the header's encryption nonce from the leading bytes of the data ciphertext, to avoid
> transmitting anything new. Working out the receiver side in detail (below) showed that doesn't
> actually work — recovering those bytes requires disguise-decoding the data portion first, which
> for a non-self-delimiting encoding needs the target length, which lives inside the header this
> nonce unlocks. The spec now derives it from `(directional key, "header-nonce", a persisted
> per-direction message counter)` instead — safe (the counter never repeats under a given key),
> costs nothing on the wire, and the counter doubles as what §6's rotation trigger needs anyway.
> Since peer-record persistence doesn't exist until the §5/§6 follow-on plans, `packMessage` takes
> the counter as a plain caller-supplied `int`, same as it already does for `key`. Rotation
> material support (the header's variable-length trailing field) is deferred to that same
> follow-on plan for the same reason — `n_tag`'s formula already reserves space for it (covering
> `data_nonce || N || rotation_material`), but this plan never populates it, so the header is
> always exactly `_headerBaseSize` bytes here.
>
> **Second simplification, found the same way:** `data_nonce` doesn't need to be a transmitted
> header field either — it derives the same way `header_nonce` does, `(directional key,
> "data-nonce", message_counter)`, the identical `(key, counter)` pair with a different
> domain-separation label. Safe for the same reason `header_nonce` is (the counter never repeats
> under a given key), and it shrinks the header from 50 to 26 bytes. The two labels
> (`"airwire-header-nonce"` vs `"airwire-data-nonce"`) staying distinct is genuinely load-bearing —
> conflating them would make the header's stream cipher and the data's AEAD share a nonce under the
> same key.

**Files:**
- Create: `protocol/lib/src/envelope.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/envelope_pack_test.dart`

**Interfaces:**
- Consumes: `aeadEncrypt`, `streamEncrypt`, `deriveKey`, `randomBytes`, `aeadNonceSize` (Task 2,
  `crypto.dart`); `ChunkEncoding` (Task 4, `encodings.dart`); `SecretKey` (from `package:cryptography`).
- Produces:
  - `class PackedMessage { List<Uint8List> fragments; }`
  - `class HeaderEncodingTooLargeError implements Exception` — thrown when `maxFragmentSize` can't
    fit the chosen header encoding's `minimumBudgetForHeader` result.
  - `class FragmentTooSmallError implements Exception` — thrown when a single data atom doesn't
    fit `maxFragmentSize` at all.
  - `Future<PackedMessage> packMessage({required List<int> plaintext, required SecretKey key, required ChunkEncoding headerEncoding, required ChunkEncoding dataEncoding, required int maxFragmentSize, required int messageCounter})`
  - Internal (not exported, but Task 7 relies on the wire format this produces being exactly as
    documented): header plaintext layout `tag(16) || dataLength(4, big-endian) || n(2, big-endian)
    || nTag(4)`, always exactly `_headerBaseSize` (26) bytes in this plan. Neither nonce is a field
    here: `header_nonce = derive_key(key_bytes, "airwire-header-nonce", messageCounter as 4-byte
    big-endian)` and `data_nonce = derive_key(key_bytes, "airwire-data-nonce", messageCounter as
    4-byte big-endian)` — Task 7's `Reassembler` recomputes both identically from the same inputs.

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/envelope_pack_test.dart
import 'dart:convert';
import 'dart:typed_data';
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:cryptography/cryptography.dart';
import 'package:test/test.dart';

void main() {
  test('a short message needs exactly one fragment', () async {
    final key = SecretKey(List<int>.filled(32, 3));
    final packed = await packMessage(
      plaintext: 'hi'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
    );
    expect(packed.fragments.length, equals(1));
  });

  test('a message too large for one fragment needs several, and header stays fixed-size', () async {
    final key = SecretKey(List<int>.filled(32, 5));
    final plaintext = List<int>.generate(500, (i) => i % 256);
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 100,
      messageCounter: 0,
    );
    expect(packed.fragments.length, greaterThan(1));
    for (final fragment in packed.fragments) {
      expect(fragment.length, lessThanOrEqualTo(100));
    }
  });

  test('the header carries data_tag, data_length and N, recoverable by hand', () async {
    final key = SecretKey(List<int>.filled(32, 11));
    final plaintext = 'a test message'.codeUnits;
    const counter = 7;
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: counter,
    );

    final first = packed.fragments.first;
    // With plainEncoding, the disguise step is the identity -- the header ciphertext bytes are
    // the leading bytes of the fragment, unmodified, so this test can decrypt them directly
    // without going through Task 7's Reassembler (kept independent on purpose). Neither nonce is
    // embedded anywhere in the fragment -- both are independently re-derivable from (key, counter)
    // alone, which is exactly what makes it safe to omit them from the wire.
    final headerCiphertext = first.sublist(0, 26); // _headerBaseSize, no rotation material yet
    final keyBytes = await key.extractBytes();
    final counterBytes = ByteData(4)..setUint32(0, counter);
    final headerNonce = await deriveKey(
      [keyBytes, 'airwire-header-nonce'.codeUnits, counterBytes.buffer.asUint8List()],
      length: 24,
    );
    final headerPlain = await streamDecrypt(key, headerNonce, headerCiphertext);
    final dataLength = ByteData.sublistView(Uint8List.fromList(headerPlain.sublist(16, 20)))
        .getUint32(0);
    final n = ByteData.sublistView(Uint8List.fromList(headerPlain.sublist(20, 22))).getUint16(0);
    expect(dataLength, equals(plaintext.length));
    expect(n, equals(packed.fragments.length - 1));
  });

  test('rejects a header encoding that cannot fit the fragment budget', () async {
    final key = SecretKey(List<int>.filled(32, 13));
    expect(
      () => packMessage(
        plaintext: 'hi'.codeUnits,
        key: key,
        headerEncoding: base64Encoding,
        dataEncoding: base64Encoding,
        maxFragmentSize: 10, // far smaller than base64's ~36-byte minimum for a 26-byte header
        messageCounter: 0,
      ),
      throwsA(isA<HeaderEncodingTooLargeError>()),
    );
  });

  test('different message counters produce different header ciphertext for the same plaintext', () async {
    final key = SecretKey(List<int>.filled(32, 17));
    final first = await packMessage(
      plaintext: 'hi'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
    );
    final second = await packMessage(
      plaintext: 'hi'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 1,
    );
    // The header portion (first 26 bytes) must differ between the two counters -- proof the
    // counter genuinely feeds the nonce rather than being silently ignored.
    expect(
      first.fragments.single.sublist(0, 26),
      isNot(equals(second.fragments.single.sublist(0, 26))),
    );
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/envelope_pack_test.dart`
Expected: FAIL — `lib/src/envelope.dart` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/envelope.dart
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'crypto.dart';
import 'encodings.dart';

/// Fixed byte offsets/widths within the header plaintext -- see protocol spec §4's "Wire shape".
/// Neither `data_nonce` nor `header_nonce` is a field here -- both are derived (below), not
/// transmitted. The header's rotation-material field isn't represented here at all -- this plan
/// never populates it, see this task's opening note for why.
const int _dataTagSize = aeadTagSize; // 16
const int _dataLengthFieldSize = 4;
const int _nFieldSize = 2;
const int _nTagSize = 4;
const int _headerBaseSize = _dataTagSize + _dataLengthFieldSize + _nFieldSize + _nTagSize;

/// The medium-sized wire messages produced by [packMessage] -- send these, in order, to the peer.
class PackedMessage {
  final List<Uint8List> fragments;

  const PackedMessage(this.fragments);
}

/// Thrown when `maxFragmentSize` can't fit `headerEncoding`'s disguised representation of the
/// header at all -- see protocol spec §4, "Minimum fragment budget for header disguise".
class HeaderEncodingTooLargeError implements Exception {
  final String message;
  const HeaderEncodingTooLargeError(this.message);
  @override
  String toString() => 'HeaderEncodingTooLargeError: $message';
}

/// Thrown when a single disguise atom (of the *data* encoding) doesn't fit `maxFragmentSize` at
/// all, so no amount of fragmenting could ever place it.
class FragmentTooSmallError implements Exception {
  final String message;
  const FragmentTooSmallError(this.message);
  @override
  String toString() => 'FragmentTooSmallError: $message';
}

Uint8List _uint32be(int value) {
  final bytes = ByteData(4)..setUint32(0, value);
  return bytes.buffer.asUint8List();
}

Uint8List _uint16be(int value) {
  final bytes = ByteData(2)..setUint16(0, value);
  return bytes.buffer.asUint8List();
}

Future<Uint8List> _computeNTag(
  SecretKey key,
  List<int> dataNonce,
  List<int> nBytes,
  List<int> rotationMaterial,
) async {
  final keyBytes = await key.extractBytes();
  final subkey = await deriveKey([keyBytes, 'airwire-envelope-n-tag'.codeUnits]);
  return deriveKey([subkey, dataNonce, nBytes, rotationMaterial], length: _nTagSize);
}

/// The header's own encryption nonce -- derived from the directional key and a persisted,
/// monotonically-increasing per-direction message counter, *not* from any message content, so it
/// never depends on decoding anything first. See the note at the top of this task for why this
/// replaced the originally-specified "reuse the data ciphertext's leading bytes" approach.
Future<Uint8List> _headerNonceFor(SecretKey key, int messageCounter) async {
  final keyBytes = await key.extractBytes();
  final counterBytes = ByteData(4)..setUint32(0, messageCounter);
  return deriveKey(
    [keyBytes, 'airwire-header-nonce'.codeUnits, counterBytes.buffer.asUint8List()],
    length: aeadNonceSize,
  );
}

/// The data AEAD's nonce -- the identical `(key, messageCounter)` pair [_headerNonceFor] uses,
/// with a different domain-separation label, which is what keeps the two values independent
/// despite sharing an input (the standard technique for deriving several values from one shared
/// secret). Never transmitted, same reasoning as [_headerNonceFor]. The two label strings staying
/// distinct is genuinely load-bearing -- conflating them would make the header's stream cipher and
/// the data's AEAD share a nonce under the same key.
Future<Uint8List> _dataNonceFor(SecretKey key, int messageCounter) async {
  final keyBytes = await key.extractBytes();
  final counterBytes = ByteData(4)..setUint32(0, messageCounter);
  return deriveKey(
    [keyBytes, 'airwire-data-nonce'.codeUnits, counterBytes.buffer.asUint8List()],
    length: aeadNonceSize,
  );
}

/// Greedily fills `budget`-bounded pieces from `atoms`, never splitting one atom across two
/// pieces -- ported from core/sources/chunking.py's `_greedy_pack`, generalized to also accept a
/// smaller budget for the very first piece (fragment 1 has less room, since the header occupies
/// part of it).
List<Uint8List> _greedyPack(
  List<Uint8List> atoms,
  int firstBudget,
  int restBudget,
) {
  final pieces = <Uint8List>[];
  var current = <int>[];
  var budget = firstBudget;
  for (final atom in atoms) {
    if (atom.length > budget && current.isEmpty) {
      throw FragmentTooSmallError(
        'A single disguise atom is ${atom.length} bytes, which does not fit a budget of $budget!',
      );
    }
    if (current.isNotEmpty && current.length + atom.length > budget) {
      pieces.add(Uint8List.fromList(current));
      current = <int>[];
      budget = restBudget;
      if (atom.length > budget) {
        throw FragmentTooSmallError(
          'A single disguise atom is ${atom.length} bytes, which does not fit a budget of $budget!',
        );
      }
    }
    current.addAll(atom);
  }
  pieces.add(Uint8List.fromList(current));
  return pieces;
}

/// Encrypts `plaintext` as a whole (protocol spec §4's data AEAD), disguises the result and a
/// preceding header describing it, and splits everything into `maxFragmentSize`-bounded wire
/// fragments. The first fragment always carries the header; a message that fits in one fragment
/// needs no others (`N = 0`) -- see protocol spec §4 for the full wire-shape rationale.
/// `messageCounter` must be a per-direction count of messages already sent under `key` that the
/// caller increments and persists across calls -- see this task's opening note for why.
Future<PackedMessage> packMessage({
  required List<int> plaintext,
  required SecretKey key,
  required ChunkEncoding headerEncoding,
  required ChunkEncoding dataEncoding,
  required int maxFragmentSize,
  required int messageCounter,
}) async {
  final dataNonce = await _dataNonceFor(key, messageCounter);
  final aead = await aeadEncrypt(key, dataNonce, plaintext);
  final dataAtoms = dataEncoding.encodeAtoms(aead.ciphertext, dataNonce).toList();
  final headerNonce = await _headerNonceFor(key, messageCounter);
  const rotationMaterial = <int>[]; // always empty in this plan -- see opening note

  if (maxFragmentSize < headerEncoding.minimumBudgetForHeader(_headerBaseSize)) {
    throw HeaderEncodingTooLargeError(
      'maxFragmentSize ($maxFragmentSize) is smaller than the chosen header encoding needs '
      'for a $_headerBaseSize-byte header!',
    );
  }

  // Fixed-point convergence on N, mirroring core/sources/chunking.py's chunk_id_size loop: the
  // header's own disguised byte length can (for Markov) depend on N's specific bit pattern, so
  // packing has to converge on a value of N consistent with the fragment layout it produces.
  var candidateN = 0;
  List<Uint8List> fragments;
  while (true) {
    final nBytes = _uint16be(candidateN);
    final nTag = await _computeNTag(key, dataNonce, nBytes, rotationMaterial);
    final headerPlain = <int>[
      ...aead.tag,
      ..._uint32be(aead.ciphertext.length),
      ...nBytes,
      ...nTag,
    ];
    final headerCiphertext = await streamEncrypt(key, headerNonce, headerPlain);
    final headerWire = headerEncoding
        .encodeAtoms(headerCiphertext, headerNonce)
        .expand((atom) => atom)
        .toList();

    if (headerWire.length > maxFragmentSize) {
      throw HeaderEncodingTooLargeError(
        'Disguised header is ${headerWire.length} bytes, which does not fit maxFragmentSize '
        '($maxFragmentSize) even though the minimum-budget check passed -- the safety margin for '
        'this encoding needs revisiting.',
      );
    }

    final firstFragmentRemaining = maxFragmentSize - headerWire.length;
    final pieces = dataAtoms.isEmpty
        ? <Uint8List>[Uint8List(0)]
        : _greedyPack(dataAtoms, firstFragmentRemaining, maxFragmentSize);

    fragments = [
      Uint8List.fromList([...headerWire, ...pieces.first]),
      for (final piece in pieces.skip(1)) piece,
    ];

    final actualN = fragments.length - 1;
    if (actualN == candidateN) break;
    candidateN = actualN;
  }

  return PackedMessage(fragments);
}
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
export 'src/envelope.dart';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/envelope_pack_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add envelope packing (protocol spec §4 wire shape)"
```

---

## Task 7: Envelope reassembly

**Files:**
- Modify: `protocol/lib/src/envelope.dart`
- Test: `protocol/test/envelope_reassemble_test.dart`

**Interfaces:**
- Consumes: `packMessage`, `PackedMessage`, `_headerNonceFor`, `_dataNonceFor`, `_computeNTag`
  (Task 6, same file); `streamDecrypt`, `aeadDecrypt` (Task 2, `crypto.dart`); `ChunkEncoding`,
  `DecodeResult` (Task 4, `encodings.dart`).
- Produces:
  - `class TamperedHeaderError implements Exception` — `n_tag` verification failed, or no valid
    header could be recovered at all (wrong key, wrong counter, or corruption).
  - `class Reassembler { Reassembler({required SecretKey key, required ChunkEncoding headerEncoding, required ChunkEncoding dataEncoding, required int messageCounter}); Future<Uint8List?> addFragment(List<int> wireBytes); }`
    — `addFragment` returns the fully reassembled plaintext once the last fragment has been fed,
    or `null` if more fragments are still expected. `messageCounter` must be the same
    per-direction count `packMessage` used on the sending side for this specific message — the
    caller (a future peer-record owner) is responsible for keeping the two in lockstep, the same
    requirement `packMessage` already has.

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/envelope_reassemble_test.dart
import 'dart:typed_data';
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:cryptography/cryptography.dart';
import 'package:test/test.dart';

void main() {
  test('round-trips a single-fragment message', () async {
    final key = SecretKey(List<int>.filled(32, 21));
    final plaintext = 'a short message'.codeUnits;
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
    );
    expect(packed.fragments.length, equals(1));

    final reassembler = Reassembler(
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      messageCounter: 0,
    );
    final result = await reassembler.addFragment(packed.fragments.single);
    expect(result, equals(plaintext));
  });

  test('round-trips a multi-fragment message, feeding fragments one at a time', () async {
    final key = SecretKey(List<int>.filled(32, 23));
    final plaintext = List<int>.generate(500, (i) => (i * 3) % 256);
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 100,
      messageCounter: 4,
    );
    expect(packed.fragments.length, greaterThan(1));

    final reassembler = Reassembler(
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      messageCounter: 4,
    );
    Uint8List? result;
    for (final fragment in packed.fragments) {
      result = await reassembler.addFragment(fragment);
    }
    expect(result, equals(plaintext));
  });

  test('round-trips through Base64 disguise for both header and data', () async {
    final key = SecretKey(List<int>.filled(32, 29));
    final plaintext = 'disguised as base64'.codeUnits;
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: base64Encoding,
      dataEncoding: base64Encoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
    );

    final reassembler = Reassembler(
      key: key,
      headerEncoding: base64Encoding,
      dataEncoding: base64Encoding,
      messageCounter: 0,
    );
    Uint8List? result;
    for (final fragment in packed.fragments) {
      result = await reassembler.addFragment(fragment);
    }
    expect(result, equals(plaintext));
  });

  test('rejects a wrong key with a clean failure, not a crash', () async {
    final key = SecretKey(List<int>.filled(32, 31));
    final wrongKey = SecretKey(List<int>.filled(32, 32));
    final packed = await packMessage(
      plaintext: 'secret'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
    );

    final reassembler = Reassembler(
      key: wrongKey,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      messageCounter: 0,
    );
    expect(
      () => reassembler.addFragment(packed.fragments.single),
      throwsA(isA<TamperedHeaderError>()),
    );
  });

  test('rejects a mismatched message counter with a clean failure', () async {
    final key = SecretKey(List<int>.filled(32, 33));
    final packed = await packMessage(
      plaintext: 'secret'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
    );

    // A different counter derives a different, wrong header nonce -- streamDecrypt "succeeds"
    // (it's unauthenticated) but produces garbage, which n_tag catches.
    final reassembler = Reassembler(
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      messageCounter: 1,
    );
    expect(
      () => reassembler.addFragment(packed.fragments.single),
      throwsA(isA<TamperedHeaderError>()),
    );
  });

  test('a tampered N is caught before any subsequent fragment is misread', () async {
    final key = SecretKey(List<int>.filled(32, 37));
    final plaintext = List<int>.generate(300, (i) => i % 256);
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 100,
      messageCounter: 0,
    );
    expect(packed.fragments.length, greaterThan(1));

    // Flip a bit inside the header's encrypted N field (bytes 20-21 of the header plaintext,
    // which after streamEncrypt is still bytes 20-21 of the fragment -- XChaCha20 is length-
    // preserving and position-preserving byte-for-byte). Layout: tag(0-16) + dataLength(16-20) +
    // N(20-22) + nTag(22-26).
    final tampered = Uint8List.fromList(packed.fragments.first);
    tampered[20] ^= 0xff;

    final reassembler = Reassembler(
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      messageCounter: 0,
    );
    expect(
      () => reassembler.addFragment(tampered),
      throwsA(isA<TamperedHeaderError>()),
    );
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/envelope_reassemble_test.dart`
Expected: FAIL — `Reassembler`/`TamperedHeaderError` don't exist yet.

- [ ] **Step 3: Write minimal implementation**

Append to `protocol/lib/src/envelope.dart` (the file Task 6 created):

```dart
/// Thrown when the header can't be recovered at all (wrong key, wrong counter, or corruption) or
/// when its short `n_tag` doesn't verify -- protocol spec §4's protection against a tampered `N`,
/// checked *before* acting on it, so a corrupted header fails this one message closed with no
/// risk of misreading subsequent fragments.
class TamperedHeaderError implements Exception {
  final String message;
  const TamperedHeaderError(this.message);
  @override
  String toString() => 'TamperedHeaderError: $message';
}

/// Incrementally reassembles one logical message from a peer's incoming wire fragments, in
/// arrival order -- mirrors how a real medium delivers messages one at a time (protocol spec §3:
/// lossless, in-order, per peer). Call [addFragment] as each one arrives; it returns the fully
/// reassembled, decrypted plaintext once the header-declared `N` fragments have all been fed, or
/// `null` while more are still expected. One `Reassembler` instance reassembles exactly one
/// logical message -- create a new one per peer's next incoming message.
class Reassembler {
  final SecretKey key;
  final ChunkEncoding headerEncoding;
  final ChunkEncoding dataEncoding;
  final int messageCounter;

  bool _headerParsed = false;
  int _expectedMoreFragments = 0;
  late Uint8List _dataNonce;
  late Uint8List _dataTag;
  late int _dataLength;
  final List<int> _dataWireBytes = [];

  Reassembler({
    required this.key,
    required this.headerEncoding,
    required this.dataEncoding,
    required this.messageCounter,
  });

  Future<Uint8List?> addFragment(List<int> wireBytes) async {
    if (!_headerParsed) {
      await _parseFirstFragment(wireBytes);
    } else {
      _dataWireBytes.addAll(wireBytes);
    }

    if (_expectedMoreFragments > 0) {
      _expectedMoreFragments--;
      return null;
    }

    final dataResult = dataEncoding.decode(_dataWireBytes, _dataLength, _dataNonce);
    return aeadDecrypt(key, _dataNonce, dataResult.plaintext, _dataTag);
  }

  Future<void> _parseFirstFragment(List<int> wireBytes) async {
    // The header's own disguised byte length isn't known ahead of time for a variable-expansion
    // encoding (protocol spec §4, "Header vs. data disguise") -- decode() with the fixed header
    // plaintext size reports how many wire bytes it actually consumed, leaving the rest for the
    // data decode below. Rotation-material support (a second, larger candidate size to try) is
    // deferred to the §6 follow-on plan along with rotation itself -- see Task 6's opening note.
    final headerResult = headerEncoding.decode(wireBytes, _headerBaseSize, const []);
    final headerCiphertext = headerResult.plaintext;

    final headerNonce = await _headerNonceFor(key, messageCounter);
    final dataNonce = await _dataNonceFor(key, messageCounter);
    final Uint8List headerPlain;
    try {
      headerPlain = await streamDecrypt(key, headerNonce, headerCiphertext);
    } catch (error) {
      throw TamperedHeaderError('Could not decrypt the header: $error');
    }

    final dataTag = headerPlain.sublist(0, _dataTagSize);
    final dataLength = ByteData.sublistView(
      Uint8List.fromList(headerPlain.sublist(_dataTagSize, _dataTagSize + _dataLengthFieldSize)),
    ).getUint32(0);
    final nOffset = _dataTagSize + _dataLengthFieldSize;
    final nBytes = headerPlain.sublist(nOffset, nOffset + _nFieldSize);
    final n = ByteData.sublistView(Uint8List.fromList(nBytes)).getUint16(0);
    final nTagOffset = nOffset + _nFieldSize;
    final nTag = headerPlain.sublist(nTagOffset, nTagOffset + _nTagSize);
    const rotationMaterial = <int>[]; // always empty in this plan -- see Task 6's opening note

    final expectedNTag = await _computeNTag(key, dataNonce, nBytes, rotationMaterial);
    if (!_bytesEqual(nTag, expectedNTag)) {
      throw TamperedHeaderError(
        'n_tag did not verify -- N was tampered, or the key/counter is wrong!',
      );
    }

    _dataNonce = Uint8List.fromList(dataNonce);
    _dataTag = Uint8List.fromList(dataTag);
    _dataLength = dataLength;
    _expectedMoreFragments = n;
    _headerParsed = true;
    _dataWireBytes.addAll(wireBytes.sublist(headerResult.consumedWireBytes));
  }
}

bool _bytesEqual(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd protocol && dart test test/envelope_reassemble_test.dart`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

Run: `cd protocol && dart test`
Expected: PASS (all tests across every task).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add envelope reassembly, completing the protocol spec §4 data path"
```

---

## What's next (not part of this plan)

- **§5 handshake and peer records** — certificate exchange, TOFU, session-loss recovery. Needs
  `packMessage`/`Reassembler` above as its transport (a certificate *is* a logical message), so this
  plan is its prerequisite, not a parallel track. This is also where `messageCounter` persistence
  has to live: `packMessage`/`Reassembler` both require it as a plain caller-supplied `int` and
  correctness (header-nonce uniqueness) depends on it never resetting or repeating for a given key
  across app restarts — the peer record is the natural owner of that state, alongside the
  directional keys themselves.
- **§6 key rotation** — directional key derivation and the rotation trigger, plus extending
  `envelope.dart`'s header to actually carry and parse rotation material (the `n_tag` formula
  already covers it, always-empty for now; `packMessage`/`Reassembler` both need a second,
  larger candidate header size added back once the peer record can tell them when to expect it —
  removed from this plan for being unreachable dead code without rotation to trigger it).
- **Image-steganography disguise** — deferred per this plan's scope boundary, above.
- **`medium-interface.md` as Dart abstract classes, and the Odnoklassniki wrapper** — the two
  follow-on slices already named when this work was scoped, unaffected by anything in this plan.
