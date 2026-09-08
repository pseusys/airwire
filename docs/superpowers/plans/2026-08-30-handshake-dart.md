# Handshake and Peer Records (Dart) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the messaging protocol spec's §5 (identity, peer state, handshake) on top of the
already-planned [protocol-core envelope](2026-08-30-protocol-core-dart.md) — plain-TOFU certificate
exchange, canonically-ordered directional-key derivation, key selection on receive, and automatic
recovery from one-sided session loss.

**Architecture:** Two new files in the same `protocol/` package: `peer.dart` (the `PeerRecord` data
model and its key-derivation math) and `handshake.dart` (certificates and the top-level `PeerSession`
that ties everything — key selection, dispatch, recovery — into one testable API a future medium
wrapper can call directly). One small but necessary extension to `envelope.dart` from the prior plan,
in Task 1, done first since everything else depends on it.

**Tech Stack:** Same as the protocol-core plan — Dart 3, `package:cryptography`, `package:test`. No
new dependencies.

**Scope boundary:** Key rotation (§6) is a separate follow-on plan — `PeerRecord` here has the fields
rotation needs (counters, `root_key`, both directional keys) but nothing in this plan triggers a
rotation. Peer-record *persistence* (surviving app restarts) is also out of scope — `PeerSession`
holds its `PeerRecord` in memory; a future Hive-backed layer is expected to serialize/restore it,
not this plan.

## Global Constraints

- Same as the protocol-core plan: Dart SDK `>=3.0.0 <4.0.0`, no Flutter dependency in `protocol/`,
  no floating-point arithmetic in any coder path, every public class/function gets a `///` doc
  comment explaining why.
- This plan assumes the protocol-core plan's Tasks 1–7 are already implemented and passing —
  `packMessage`/`Reassembler`/`ChunkEncoding`/`deriveKey`/etc. are consumed here, not redefined.

---

## Task 1: Extend the envelope for certificate nonce transmission

> **Why this is first:** working out the certificate mechanics (this plan) surfaced a real gap in
> the protocol-core plan's envelope: its header nonce is derived from `(key, messageCounter)`, which
> is safe for ordinary data messages (part of an ongoing, continuously-tracked relationship, so a
> reliable counter exists) but *cannot* work for certificates — `bootstrap_key` is reused for every
> certificate a device ever sends, to every peer, for its whole lifetime, and a counter safe enough
> to never repeat across all of that would have to survive the exact event (local storage wiped)
> that `bootstrap_key` exists to recover from. Certificates instead transmit a fresh random nonce,
> disguised as its own chained block ahead of the header — one more link in the same
> nonce→header→data chain the envelope already uses for header→data. See protocol spec §5,
> "Certificate header nonce".

**Files:**
- Modify: `protocol/lib/src/envelope.dart`
- Modify: `protocol/test/envelope_pack_test.dart`
- Modify: `protocol/test/envelope_reassemble_test.dart`

**Interfaces:**
- Consumes: everything `envelope.dart` (protocol-core Tasks 6–7) already consumes, unchanged.
- Produces (modifies existing signatures, additive/optional so no existing caller breaks):
  - `Future<PackedMessage> packMessage({..., int? messageCounter, bool transmitNonce = false})` —
    exactly one of `messageCounter` or `transmitNonce: true` must be given.
  - `class Reassembler { Reassembler({..., int? messageCounter, bool transmitNonce = false}); }` —
    same constraint.

- [ ] **Step 1: Write the failing tests**

Add to `protocol/test/envelope_pack_test.dart` (inside the existing `main()`, alongside the tests
protocol-core Task 6 already wrote):

```dart
  test('transmitNonce mode produces a fragment that starts with a disguised nonce block', () async {
    final key = SecretKey(List<int>.filled(32, 41));
    final packed = await packMessage(
      plaintext: 'a certificate payload'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      transmitNonce: true,
    );
    // With plainEncoding (identity disguise), the first 24 bytes of the fragment are the raw
    // nonce, in the clear as far as this test can see -- confirming the block is really there and
    // really 24 bytes, not folded into the header some other way.
    expect(packed.fragments.first.length, greaterThanOrEqualTo(24 + 26));
  });

  test('passing neither or both of messageCounter/transmitNonce is rejected', () async {
    final key = SecretKey(List<int>.filled(32, 43));
    expect(
      () => packMessage(
        plaintext: 'hi'.codeUnits,
        key: key,
        headerEncoding: plainEncoding,
        dataEncoding: plainEncoding,
        maxFragmentSize: 1000,
      ),
      throwsA(isA<AssertionError>()),
    );
    expect(
      () => packMessage(
        plaintext: 'hi'.codeUnits,
        key: key,
        headerEncoding: plainEncoding,
        dataEncoding: plainEncoding,
        maxFragmentSize: 1000,
        messageCounter: 0,
        transmitNonce: true,
      ),
      throwsA(isA<AssertionError>()),
    );
  });
```

Add to `protocol/test/envelope_reassemble_test.dart`:

```dart
  test('round-trips in transmitNonce mode', () async {
    final key = SecretKey(List<int>.filled(32, 47));
    final plaintext = 'a certificate payload, round-tripped'.codeUnits;
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      transmitNonce: true,
    );

    final reassembler = Reassembler(
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      transmitNonce: true,
    );
    final result = await reassembler.addFragment(packed.fragments.single);
    expect(result, equals(plaintext));
  });

  test('transmitNonce mode still round-trips across multiple fragments', () async {
    final key = SecretKey(List<int>.filled(32, 53));
    final plaintext = List<int>.generate(400, (i) => (i * 7) % 256);
    final packed = await packMessage(
      plaintext: plaintext,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 100,
      transmitNonce: true,
    );
    expect(packed.fragments.length, greaterThan(1));

    final reassembler = Reassembler(
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      transmitNonce: true,
    );
    Uint8List? result;
    for (final fragment in packed.fragments) {
      result = await reassembler.addFragment(fragment);
    }
    expect(result, equals(plaintext));
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/envelope_pack_test.dart test/envelope_reassemble_test.dart`
Expected: FAIL — `transmitNonce` isn't a recognized parameter yet.

- [ ] **Step 3: Modify `packMessage`**

Replace the existing `packMessage` function in `protocol/lib/src/envelope.dart` (from the
protocol-core plan) with:

```dart
/// The data AEAD's nonce, for `transmitNonce` mode specifically -- derived from the *transmitted*
/// `header_nonce` rather than a counter (protocol spec §5, "Certificate header nonce"): the
/// receiver already has `header_nonce` in hand (it's the first thing decoded) before it ever needs
/// `data_nonce`, so there's no circularity, and this saves a certificate a second 24 random bytes
/// on top of the first. Same domain-separation label as [_dataNonceFor] -- the two modes are
/// mutually exclusive per message, so there's no cross-mode collision to worry about.
Future<Uint8List> _dataNonceFromTransmittedNonce(SecretKey key, List<int> headerNonce) async {
  final keyBytes = await key.extractBytes();
  return deriveKey([keyBytes, 'airwire-data-nonce'.codeUnits, headerNonce], length: aeadNonceSize);
}

/// Encrypts `plaintext` as a whole (protocol spec §4's data AEAD), disguises the result and a
/// preceding header describing it, and splits everything into `maxFragmentSize`-bounded wire
/// fragments. The first fragment always carries the header; a message that fits in one fragment
/// needs no others (`N = 0`) -- see protocol spec §4 for the full wire-shape rationale.
///
/// Exactly one of `messageCounter` or `transmitNonce: true` must be given. `messageCounter` is for
/// ordinary data messages under an established directional key (§4) -- a persisted, per-direction
/// count the caller increments and never resets except on rotation. `transmitNonce: true` is for
/// certificates (§5) -- see this task's opening note for why they can't share the counter approach:
/// a fresh random nonce is generated and transmitted as its own disguised block ahead of the header,
/// instead of being derived.
Future<PackedMessage> packMessage({
  required List<int> plaintext,
  required SecretKey key,
  required ChunkEncoding headerEncoding,
  required ChunkEncoding dataEncoding,
  required int maxFragmentSize,
  int? messageCounter,
  bool transmitNonce = false,
}) async {
  assert(
    transmitNonce ? messageCounter == null : messageCounter != null,
    'Pass exactly one of messageCounter (data messages) or transmitNonce: true (certificates).',
  );

  final headerNonce =
      transmitNonce ? randomBytes(aeadNonceSize) : await _headerNonceFor(key, messageCounter!);
  final dataNonce = transmitNonce
      ? await _dataNonceFromTransmittedNonce(key, headerNonce)
      : await _dataNonceFor(key, messageCounter!);
  final aead = await aeadEncrypt(key, dataNonce, plaintext);
  final dataAtoms = dataEncoding.encodeAtoms(aead.ciphertext, dataNonce).toList();
  const rotationMaterial = <int>[]; // always empty in this plan -- see protocol-core Task 6's note

  final nonceWire = transmitNonce
      ? headerEncoding.encodeAtoms(headerNonce, const []).expand((atom) => atom).toList()
      : const <int>[];

  final minimumBudget =
      (transmitNonce ? headerEncoding.minimumBudgetForHeader(aeadNonceSize) : 0) +
          headerEncoding.minimumBudgetForHeader(_headerBaseSize);
  if (maxFragmentSize < minimumBudget) {
    throw HeaderEncodingTooLargeError(
      'maxFragmentSize ($maxFragmentSize) is smaller than the chosen header encoding needs '
      '(minimum $minimumBudget bytes, nonce block included: $transmitNonce)!',
    );
  }

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

    final firstBlockLength = nonceWire.length + headerWire.length;
    if (firstBlockLength > maxFragmentSize) {
      throw HeaderEncodingTooLargeError(
        'Disguised nonce+header is $firstBlockLength bytes, which does not fit maxFragmentSize '
        '($maxFragmentSize) even though the minimum-budget check passed -- the safety margin for '
        'this encoding needs revisiting.',
      );
    }

    final firstFragmentRemaining = maxFragmentSize - firstBlockLength;
    final pieces = dataAtoms.isEmpty
        ? <Uint8List>[Uint8List(0)]
        : _greedyPack(dataAtoms, firstFragmentRemaining, maxFragmentSize);

    fragments = [
      Uint8List.fromList([...nonceWire, ...headerWire, ...pieces.first]),
      for (final piece in pieces.skip(1)) piece,
    ];

    final actualN = fragments.length - 1;
    if (actualN == candidateN) break;
    candidateN = actualN;
  }

  return PackedMessage(fragments);
}
```

- [ ] **Step 4: Modify `Reassembler`**

Replace the existing `Reassembler` class and its `_parseFirstFragment` method in
`protocol/lib/src/envelope.dart` with:

```dart
/// Incrementally reassembles one logical message from a peer's incoming wire fragments, in
/// arrival order -- mirrors how a real medium delivers messages one at a time (protocol spec §3:
/// lossless, in-order, per peer). Call [addFragment] as each one arrives; it returns the fully
/// reassembled, decrypted plaintext once the header-declared `N` fragments have all been fed, or
/// `null` while more are still expected. One `Reassembler` instance reassembles exactly one
/// logical message -- create a new one per peer's next incoming message.
///
/// Exactly one of `messageCounter` or `transmitNonce: true` must be given, matching whichever mode
/// [packMessage] used on the sending side for this specific message -- see that function's doc
/// comment.
class Reassembler {
  final SecretKey key;
  final ChunkEncoding headerEncoding;
  final ChunkEncoding dataEncoding;
  final int? messageCounter;
  final bool transmitNonce;

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
    this.messageCounter,
    this.transmitNonce = false,
  }) : assert(
          transmitNonce ? messageCounter == null : messageCounter != null,
          'Pass exactly one of messageCounter (data messages) or transmitNonce: true (certificates).',
        );

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
    var offset = 0;
    final Uint8List headerNonce;
    if (transmitNonce) {
      final nonceResult = headerEncoding.decode(wireBytes, aeadNonceSize, const []);
      headerNonce = nonceResult.plaintext;
      offset = nonceResult.consumedWireBytes;
    } else {
      headerNonce = await _headerNonceFor(key, messageCounter!);
    }
    final dataNonce = transmitNonce
        ? await _dataNonceFromTransmittedNonce(key, headerNonce)
        : await _dataNonceFor(key, messageCounter!);

    // The header's own disguised byte length isn't known ahead of time for a variable-expansion
    // encoding (protocol spec §4, "Header vs. data disguise") -- decode() with the fixed header
    // plaintext size reports how many wire bytes it actually consumed, leaving the rest for the
    // data decode below.
    final headerResult = headerEncoding.decode(wireBytes.sublist(offset), _headerBaseSize, const []);
    final headerCiphertext = headerResult.plaintext;

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
    const rotationMaterial = <int>[]; // always empty in this plan

    final expectedNTag = await _computeNTag(key, dataNonce, nBytes, rotationMaterial);
    if (!_bytesEqual(nTag, expectedNTag)) {
      throw TamperedHeaderError(
        'n_tag did not verify -- N was tampered, or the key/counter/nonce is wrong!',
      );
    }

    _dataNonce = Uint8List.fromList(dataNonce);
    _dataTag = Uint8List.fromList(dataTag);
    _dataLength = dataLength;
    _expectedMoreFragments = n;
    _headerParsed = true;
    _dataWireBytes.addAll(wireBytes.sublist(offset + headerResult.consumedWireBytes));
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/envelope_pack_test.dart test/envelope_reassemble_test.dart`
Expected: PASS (all tests, old and new).

- [ ] **Step 6: Run the full test suite to confirm nothing else broke**

Run: `cd protocol && dart test`
Expected: PASS (every test across every file).

- [ ] **Step 7: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add transmit-nonce mode to the envelope for certificate exchange"
```

---

## Task 2: PeerRecord and key derivation

**Files:**
- Create: `protocol/lib/src/peer.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/peer_test.dart`

**Interfaces:**
- Consumes: `computeSharedSecret`, `deriveKey`, `X25519KeyPair` (Task 2, `crypto.dart`);
  `SimplePublicKey`, `SecretKey` (from `package:cryptography`).
- Produces:
  - `class PeerRecord` — holds `rootKey`, both directional keys, both message counters, both
    rotation intervals, and which of the two directional keys is "ours" for writing.
    - `SecretKey get outgoingKey`, `set outgoingKey(SecretKey)`
    - `SecretKey get incomingKey`, `set incomingKey(SecretKey)`
    - `int outgoingCounter`, `int incomingCounter` (mutable, caller increments)
    - `final int outgoingRotationInterval`, `final int incomingRotationInterval`
  - `Future<PeerRecord> deriveSessionKeys({required SimplePublicKey ourPublicKey, required SimplePublicKey peerPublicKey, required SecretKey sharedSecret, required int outgoingRotationInterval, required int incomingRotationInterval})`

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/peer_test.dart
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:cryptography/cryptography.dart';
import 'package:test/test.dart';

void main() {
  test('both sides derive matching outgoing/incoming keys, crossed correctly', () async {
    final alice = await generateX25519KeyPair();
    final bob = await generateX25519KeyPair();

    final aliceSharedSecret = await computeSharedSecret(alice.secretKeyPair, bob.publicKey);
    final bobSharedSecret = await computeSharedSecret(bob.secretKeyPair, alice.publicKey);

    final aliceRecord = await deriveSessionKeys(
      ourPublicKey: alice.publicKey,
      peerPublicKey: bob.publicKey,
      sharedSecret: aliceSharedSecret,
      outgoingRotationInterval: 256,
      incomingRotationInterval: 128,
    );
    final bobRecord = await deriveSessionKeys(
      ourPublicKey: bob.publicKey,
      peerPublicKey: alice.publicKey,
      sharedSecret: bobSharedSecret,
      outgoingRotationInterval: 128,
      incomingRotationInterval: 256,
    );

    // What Alice writes with, Bob must read with, and vice versa.
    expect(
      await aliceRecord.outgoingKey.extractBytes(),
      equals(await bobRecord.incomingKey.extractBytes()),
    );
    expect(
      await aliceRecord.incomingKey.extractBytes(),
      equals(await bobRecord.outgoingKey.extractBytes()),
    );
    // root_key is symmetric -- neither side "writes" or "reads" with it.
    expect(
      await aliceRecord.rootKey.extractBytes(),
      equals(await bobRecord.rootKey.extractBytes()),
    );
  });

  test('counters start at zero', () async {
    final alice = await generateX25519KeyPair();
    final bob = await generateX25519KeyPair();
    final sharedSecret = await computeSharedSecret(alice.secretKeyPair, bob.publicKey);
    final record = await deriveSessionKeys(
      ourPublicKey: alice.publicKey,
      peerPublicKey: bob.publicKey,
      sharedSecret: sharedSecret,
      outgoingRotationInterval: 256,
      incomingRotationInterval: 256,
    );
    expect(record.outgoingCounter, equals(0));
    expect(record.incomingCounter, equals(0));
  });

  test('rotation intervals are recorded as given, not swapped', () async {
    final alice = await generateX25519KeyPair();
    final bob = await generateX25519KeyPair();
    final sharedSecret = await computeSharedSecret(alice.secretKeyPair, bob.publicKey);
    final record = await deriveSessionKeys(
      ourPublicKey: alice.publicKey,
      peerPublicKey: bob.publicKey,
      sharedSecret: sharedSecret,
      outgoingRotationInterval: 111,
      incomingRotationInterval: 222,
    );
    expect(record.outgoingRotationInterval, equals(111));
    expect(record.incomingRotationInterval, equals(222));
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/peer_test.dart`
Expected: FAIL — `lib/src/peer.dart` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/peer.dart
import 'package:cryptography/cryptography.dart';

import 'crypto.dart';

int _compareBytes(List<int> a, List<int> b) {
  final length = a.length < b.length ? a.length : b.length;
  for (var i = 0; i < length; i++) {
    if (a[i] != b[i]) return a[i] - b[i];
  }
  return a.length - b.length;
}

/// Local state for one chat -- protocol spec §5: this record *is* the chat, its presence or
/// absence the only signal of whether one exists. Directional keys are stored canonically by
/// sorted-pubkey order (`min2max`/`max2min`, protocol spec §5-§6) rather than "ours"/"theirs" --
/// [outgoingKey]/[incomingKey] map onto whichever of the two that canonical order makes ours,
/// computed once at construction and fixed for the record's life (the ordering can't change
/// without a whole new handshake, since it's derived from the ephemeral keys that handshake used).
class PeerRecord {
  SecretKey rootKey;
  SecretKey _keyMin2Max;
  SecretKey _keyMax2Min;
  final bool _weAreMin;

  int outgoingCounter = 0;
  int incomingCounter = 0;
  final int outgoingRotationInterval;
  final int incomingRotationInterval;

  PeerRecord._({
    required this.rootKey,
    required SecretKey keyMin2Max,
    required SecretKey keyMax2Min,
    required bool weAreMin,
    required this.outgoingRotationInterval,
    required this.incomingRotationInterval,
  })  : _keyMin2Max = keyMin2Max,
        _keyMax2Min = keyMax2Min,
        _weAreMin = weAreMin;

  SecretKey get outgoingKey => _weAreMin ? _keyMin2Max : _keyMax2Min;
  set outgoingKey(SecretKey key) {
    if (_weAreMin) {
      _keyMin2Max = key;
    } else {
      _keyMax2Min = key;
    }
  }

  SecretKey get incomingKey => _weAreMin ? _keyMax2Min : _keyMin2Max;
  set incomingKey(SecretKey key) {
    if (_weAreMin) {
      _keyMax2Min = key;
    } else {
      _keyMin2Max = key;
    }
  }
}

/// Derives a fresh [PeerRecord] from a completed ECDH exchange -- protocol spec §5's
/// `root_key`/`key_min2max`/`key_max2min` derivation, with the canonical (sorted, not "self"/
/// "peer") byte ordering that makes both sides agree regardless of who computed first.
/// `outgoingRotationInterval` is what *we* announced in our own certificate;
/// `incomingRotationInterval` is what the peer announced in theirs (protocol spec §5-§6) -- both
/// are recorded as given, not derived from anything here.
Future<PeerRecord> deriveSessionKeys({
  required SimplePublicKey ourPublicKey,
  required SimplePublicKey peerPublicKey,
  required SecretKey sharedSecret,
  required int outgoingRotationInterval,
  required int incomingRotationInterval,
}) async {
  final sharedSecretBytes = await sharedSecret.extractBytes();
  final ourBytes = ourPublicKey.bytes;
  final peerBytes = peerPublicKey.bytes;
  final weAreMin = _compareBytes(ourBytes, peerBytes) < 0;
  final minBytes = weAreMin ? ourBytes : peerBytes;
  final maxBytes = weAreMin ? peerBytes : ourBytes;

  final rootKeyBytes = await deriveKey(
    [sharedSecretBytes, minBytes, maxBytes, 'airwire-root-key'.codeUnits],
    length: 32,
  );
  final keyMin2MaxBytes = await deriveKey(
    [sharedSecretBytes, minBytes, maxBytes, 'airwire-min2max'.codeUnits],
    length: 32,
  );
  final keyMax2MinBytes = await deriveKey(
    [sharedSecretBytes, minBytes, maxBytes, 'airwire-max2min'.codeUnits],
    length: 32,
  );

  return PeerRecord._(
    rootKey: SecretKey(rootKeyBytes),
    keyMin2Max: SecretKey(keyMin2MaxBytes),
    keyMax2Min: SecretKey(keyMax2MinBytes),
    weAreMin: weAreMin,
    outgoingRotationInterval: outgoingRotationInterval,
    incomingRotationInterval: incomingRotationInterval,
  );
}
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
export 'src/peer.dart';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/peer_test.dart`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add PeerRecord and canonically-ordered key derivation"
```

---

## Task 3: Certificate message

**Files:**
- Create: `protocol/lib/src/handshake.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/handshake_certificate_test.dart`

**Interfaces:**
- Consumes: nothing from this package yet (pure encode/decode of a byte layout).
- Produces:
  - `class ParsedCertificate { SimplePublicKey ephemeralPublicKey; int rotationInterval; }` —
    deliberately no `senderId` field, see below.
  - `Uint8List encodeCertificate(List<int> ephemeralPublicKeyBytes, int rotationInterval)`
  - `ParsedCertificate decodeCertificate(List<int> plaintext)` — throws `FormatException` on a
    malformed layout.
  - `Future<SecretKey> bootstrapKey(String senderId, String recipientId)` — pair-specific (protocol
    spec §5), not a function of `senderId` alone, so it differs across every peer a sender talks
    to, not just across senders.

`sender_id` is not part of the certificate itself: the receiver already has to know it before it
can even pick which `bootstrap_key` to try decrypting with, and a successful AEAD tag already
proves it was correct — a redundant copy in the plaintext would add no assurance and just cost
bytes. Plaintext is a fixed 34 bytes (`ephemeral_public_key` + `rotation_interval`), no
length-prefix framing needed at all.

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/handshake_certificate_test.dart
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:test/test.dart';

void main() {
  test('encode then decode recovers both fields', () {
    final publicKeyBytes = List<int>.generate(32, (i) => i);
    final encoded = encodeCertificate(publicKeyBytes, 256);
    final decoded = decodeCertificate(encoded);
    expect(decoded.ephemeralPublicKey.bytes, equals(publicKeyBytes));
    expect(decoded.rotationInterval, equals(256));
  });

  test('decode rejects a truncated certificate', () {
    final encoded = encodeCertificate(List<int>.filled(32, 1), 100);
    expect(
      () => decodeCertificate(encoded.sublist(0, encoded.length - 5)),
      throwsFormatException,
    );
  });

  test('bootstrapKey is deterministic per (sender, recipient) pair', () async {
    final a1 = await (await bootstrapKey('alice', 'bob')).extractBytes();
    final a2 = await (await bootstrapKey('alice', 'bob')).extractBytes();
    expect(a1, equals(a2));
  });

  test('bootstrapKey differs across different recipients of the same sender', () async {
    final toBob = await (await bootstrapKey('alice', 'bob')).extractBytes();
    final toCharlie = await (await bootstrapKey('alice', 'charlie')).extractBytes();
    expect(toBob, isNot(equals(toCharlie)));
  });

  test('bootstrapKey differs across different senders to the same recipient', () async {
    final fromAlice = await (await bootstrapKey('alice', 'bob')).extractBytes();
    final fromCharlie = await (await bootstrapKey('charlie', 'bob')).extractBytes();
    expect(fromAlice, isNot(equals(fromCharlie)));
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/handshake_certificate_test.dart`
Expected: FAIL — `lib/src/handshake.dart` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/handshake.dart
import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'crypto.dart';

/// A peer's unsigned handshake certificate, decoded -- protocol spec §5: `{ephemeral_public_key,
/// rotation_interval}`. No `sender_id` field -- see this task's opening note for why it would be
/// redundant. Unsigned is deliberate (plain TOFU); see the protocol spec's security-properties
/// table (§8) for what that does and doesn't provide.
class ParsedCertificate {
  final SimplePublicKey ephemeralPublicKey;
  final int rotationInterval;

  const ParsedCertificate(this.ephemeralPublicKey, this.rotationInterval);
}

/// Serializes a certificate's plaintext fields. Fixed layout, no framing needed: 32-byte X25519
/// public key, 2-byte big-endian `rotationInterval` -- 34 bytes total, always. A custom fixed
/// layout rather than Protobuf -- this is an independent Dart implementation with no wire
/// compatibility requirement with `core/`'s Python (see the protocol-core plan's architecture
/// note), so a full Protobuf toolchain buys nothing here.
Uint8List encodeCertificate(List<int> ephemeralPublicKeyBytes, int rotationInterval) {
  final rotationIntervalBytes = ByteData(2)..setUint16(0, rotationInterval);
  return Uint8List.fromList([
    ...ephemeralPublicKeyBytes,
    ...rotationIntervalBytes.buffer.asUint8List(),
  ]);
}

/// Inverse of [encodeCertificate]. Throws [FormatException] if `plaintext` is too short to
/// contain a well-formed certificate.
ParsedCertificate decodeCertificate(List<int> plaintext) {
  const expectedLength = 34;
  if (plaintext.length < expectedLength) {
    throw FormatException(
      'Certificate plaintext is ${plaintext.length} bytes, needs at least $expectedLength!',
    );
  }
  final publicKeyBytes = plaintext.sublist(0, 32);
  final rotationInterval =
      ByteData.sublistView(Uint8List.fromList(plaintext.sublist(32, 34))).getUint16(0);
  return ParsedCertificate(
    SimplePublicKey(publicKeyBytes, type: KeyPairType.x25519),
    rotationInterval,
  );
}

/// A pure function of both `senderId` and `recipientId`, computable unilaterally by anyone who
/// knows both (which, per protocol spec constraint 3, is everyone -- addressing a message requires
/// knowing the recipient's ID too) -- protocol spec §5: bootstraps the very first message of a
/// handshake, before any session key exists. Pair-specific rather than sender-only: this is what
/// keeps the certificate's own transmitted nonce (see [encodeCertificate]/`Reassembler`'s
/// `transmitNonce` mode) a genuinely narrow, single-pair concern rather than a sender-wide one --
/// see protocol spec §5, "Certificate header nonce". Provides no confidentiality on its own either
/// way (anyone can derive it) -- see protocol spec §8 for what this does and doesn't buy.
Future<SecretKey> bootstrapKey(String senderId, String recipientId) async {
  final keyBytes = await deriveKey(
    [utf8.encode(senderId), utf8.encode(recipientId), 'airwire-handshake-bootstrap'.codeUnits],
    length: 32,
  );
  return SecretKey(keyBytes);
}
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
export 'src/handshake.dart';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/handshake_certificate_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add certificate message encode/decode and bootstrap key"
```

---

## Task 4: Sending a certificate

**Files:**
- Modify: `protocol/lib/src/handshake.dart`
- Modify: `protocol/test/handshake_certificate_test.dart`

**Interfaces:**
- Consumes: `bootstrapKey`, `encodeCertificate` (Task 3, same file); `generateX25519KeyPair`,
  `X25519KeyPair` (Task 2, `crypto.dart`); `packMessage` (protocol-core Task 6, extended Task 1
  above); `ChunkEncoding` (protocol-core Task 4).
- Produces:
  - `class OutgoingCertificate { PackedMessage packed; X25519KeyPair ephemeralKeyPair; int outgoingRotationInterval; }`
    — the caller must hold onto `ephemeralKeyPair` until the peer's own certificate arrives, to
    complete the ECDH exchange (Task 5); `outgoingRotationInterval` is carried along too, since
    Task 5's `completeHandshake` needs the value *we* announced, not just the peer's.
  - `Future<OutgoingCertificate> sendCertificate({required String ourSenderId, required String recipientId, required int outgoingRotationInterval, required ChunkEncoding headerEncoding, required ChunkEncoding dataEncoding, required int maxFragmentSize})`
    — `recipientId` is who this certificate is being sent *to*; needed for `bootstrapKey`'s
    pair-specific derivation (Task 3), not stored anywhere in the certificate itself.

- [ ] **Step 1: Write the failing test**

Add to `protocol/test/handshake_certificate_test.dart`:

```dart
  test('sendCertificate produces fragments decodable back to the same certificate', () async {
    final outgoing = await sendCertificate(
      ourSenderId: '+15559876543',
      recipientId: '+15551112222',
      outgoingRotationInterval: 256,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
    );
    expect(outgoing.packed.fragments.length, equals(1));

    final key = await bootstrapKey('+15559876543', '+15551112222');
    final reassembler = Reassembler(
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      transmitNonce: true,
    );
    final plaintext = await reassembler.addFragment(outgoing.packed.fragments.single);
    final certificate = decodeCertificate(plaintext!);
    expect(certificate.rotationInterval, equals(256));
    expect(certificate.ephemeralPublicKey.bytes, equals(outgoing.ephemeralKeyPair.publicKey.bytes));
  });
```

(Add the necessary imports to the top of the test file if not already present: `import
'dart:typed_data';` and `import 'package:cryptography/cryptography.dart';`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd protocol && dart test test/handshake_certificate_test.dart`
Expected: FAIL — `sendCertificate`/`OutgoingCertificate` don't exist yet.

- [ ] **Step 3: Write minimal implementation**

Append to `protocol/lib/src/handshake.dart`:

```dart
/// The result of [sendCertificate]: the wire fragments to actually send, the ephemeral keypair
/// generated for this handshake -- the caller must keep it (specifically its private half) until
/// the peer's own certificate arrives, since completing the ECDH exchange (Task 5) needs it -- and
/// the rotation interval we announced, which Task 5's `completeHandshake` also needs (it's *our*
/// value, not derivable from the peer's certificate).
class OutgoingCertificate {
  final PackedMessage packed;
  final X25519KeyPair ephemeralKeyPair;
  final int outgoingRotationInterval;

  const OutgoingCertificate(this.packed, this.ephemeralKeyPair, this.outgoingRotationInterval);
}

/// Generates a fresh, conversation-scoped ephemeral X25519 keypair and packages a certificate
/// announcing it -- protocol spec §5. Unilateral: needs nothing from the peer, can be called
/// before or after their own certificate arrives, even the very first time `ourSenderId` has ever
/// talked to `recipientId`.
Future<OutgoingCertificate> sendCertificate({
  required String ourSenderId,
  required String recipientId,
  required int outgoingRotationInterval,
  required ChunkEncoding headerEncoding,
  required ChunkEncoding dataEncoding,
  required int maxFragmentSize,
}) async {
  final ephemeralKeyPair = await generateX25519KeyPair();
  final key = await bootstrapKey(ourSenderId, recipientId);
  final plaintext = encodeCertificate(
    ephemeralKeyPair.publicKey.bytes,
    outgoingRotationInterval,
  );
  final packed = await packMessage(
    plaintext: plaintext,
    key: key,
    headerEncoding: headerEncoding,
    dataEncoding: dataEncoding,
    maxFragmentSize: maxFragmentSize,
    transmitNonce: true,
  );
  return OutgoingCertificate(packed, ephemeralKeyPair, outgoingRotationInterval);
}
```

Add the missing import at the top of `protocol/lib/src/handshake.dart`:

```dart
import 'envelope.dart';
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd protocol && dart test test/handshake_certificate_test.dart`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add sendCertificate"
```

---

## Task 5: Completing a handshake

**Files:**
- Modify: `protocol/lib/src/handshake.dart`
- Test: `protocol/test/handshake_complete_test.dart`

**Interfaces:**
- Consumes: `ParsedCertificate`, `OutgoingCertificate`, `sendCertificate` (Task 3-4, same file);
  `computeSharedSecret` (Task 2, `crypto.dart`); `deriveSessionKeys`, `PeerRecord` (Task 2, `peer.dart`).
- Produces:
  - `Future<PeerRecord> completeHandshake({required OutgoingCertificate ours, required ParsedCertificate theirs})`

- [ ] **Step 1: Write the failing test**

```dart
// protocol/test/handshake_complete_test.dart
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:test/test.dart';

void main() {
  test('both sides complete a handshake and land on matching, crossed directional keys', () async {
    final aliceOutgoing = await sendCertificate(
      ourSenderId: 'alice',
      recipientId: 'bob',
      outgoingRotationInterval: 256,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
    );
    final bobOutgoing = await sendCertificate(
      ourSenderId: 'bob',
      recipientId: 'alice',
      outgoingRotationInterval: 128,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
    );

    // Each side "receives" the other's certificate -- reusing decodeCertificate directly here
    // since Task 6's dispatch logic (which would normally do this via a Reassembler) isn't built
    // yet; this task only cares about what happens once a ParsedCertificate is in hand.
    final aliceReceivesBob = ParsedCertificate(
      bobOutgoing.ephemeralKeyPair.publicKey,
      128,
    );
    final bobReceivesAlice = ParsedCertificate(
      aliceOutgoing.ephemeralKeyPair.publicKey,
      256,
    );

    final aliceRecord = await completeHandshake(ours: aliceOutgoing, theirs: aliceReceivesBob);
    final bobRecord = await completeHandshake(ours: bobOutgoing, theirs: bobReceivesAlice);

    expect(
      await aliceRecord.outgoingKey.extractBytes(),
      equals(await bobRecord.incomingKey.extractBytes()),
    );
    expect(
      await aliceRecord.incomingKey.extractBytes(),
      equals(await bobRecord.outgoingKey.extractBytes()),
    );
    expect(aliceRecord.outgoingRotationInterval, equals(256));
    expect(aliceRecord.incomingRotationInterval, equals(128));
    expect(bobRecord.outgoingRotationInterval, equals(128));
    expect(bobRecord.incomingRotationInterval, equals(256));
  });
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd protocol && dart test test/handshake_complete_test.dart`
Expected: FAIL — `completeHandshake` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

Append to `protocol/lib/src/handshake.dart`:

```dart
/// Completes a handshake once both our own certificate (already sent -- [ours], carrying our
/// ephemeral keypair and the rotation interval we announced) and the peer's (just received --
/// [theirs]) are in hand: runs the ECDH exchange and derives a fresh [PeerRecord]. Protocol spec
/// §5: "sending data to a peer requires having already received their certificate" -- this is the
/// function that transition represents.
Future<PeerRecord> completeHandshake({
  required OutgoingCertificate ours,
  required ParsedCertificate theirs,
}) async {
  final sharedSecret = await computeSharedSecret(
    ours.ephemeralKeyPair.secretKeyPair,
    theirs.ephemeralPublicKey,
  );
  return deriveSessionKeys(
    ourPublicKey: ours.ephemeralKeyPair.publicKey,
    peerPublicKey: theirs.ephemeralPublicKey,
    sharedSecret: sharedSecret,
    outgoingRotationInterval: ours.outgoingRotationInterval,
    incomingRotationInterval: theirs.rotationInterval,
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd protocol && dart test test/handshake_complete_test.dart`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add completeHandshake"
```

---

## Task 6: PeerSession — key selection, dispatch, and recovery

**Files:**
- Create: `protocol/lib/src/session.dart`
- Modify: `protocol/lib/airwire_protocol.dart` (export)
- Test: `protocol/test/session_test.dart`

**Interfaces:**
- Consumes: everything from Tasks 1–5 (`PeerRecord`, `sendCertificate`, `completeHandshake`,
  `decodeCertificate`, `bootstrapKey`), plus `packMessage`, `Reassembler`, `ChunkEncoding` (protocol-core).
- Produces:
  - `sealed class SessionEvent {}`
  - `class DataReceived extends SessionEvent { Uint8List plaintext; }`
  - `class PeerEstablished extends SessionEvent { PeerRecord record; }` — fired the moment a
    handshake (first contact *or* recovery) completes as a side effect of an incoming fragment.
  - `class PeerSession { PeerSession({required String ourSenderId, required String peerSenderId, required int outgoingRotationInterval, required ChunkEncoding headerEncoding, required ChunkEncoding dataEncoding, required int maxFragmentSize, PeerRecord? existingRecord}); PeerRecord? get record; Future<PackedMessage> ensureCertificateSent(); Future<PackedMessage> sendData(List<int> plaintext); Future<SessionEvent?> receiveFragment(List<int> wireBytes); }`

- [ ] **Step 1: Write the failing tests**

```dart
// protocol/test/session_test.dart
import 'dart:typed_data';
import 'package:airwire_protocol/airwire_protocol.dart';
import 'package:test/test.dart';

/// Drives two PeerSessions through a full handshake by hand-delivering each other's outgoing
/// fragments -- there's no medium in this plan (protocol-core's scope boundary), so the test plays
/// that role directly.
Future<void> _completeHandshake(PeerSession alice, PeerSession bob) async {
  final aliceCert = await alice.ensureCertificateSent();
  final bobCert = await bob.ensureCertificateSent();

  SessionEvent? aliceEvent;
  for (final fragment in bobCert.fragments) {
    aliceEvent = await alice.receiveFragment(fragment);
  }
  SessionEvent? bobEvent;
  for (final fragment in aliceCert.fragments) {
    bobEvent = await bob.receiveFragment(fragment);
  }

  expect(aliceEvent, isA<PeerEstablished>());
  expect(bobEvent, isA<PeerEstablished>());
}

PeerSession _newSession(String ourId, String peerId, {int rotationInterval = 256}) {
  return PeerSession(
    ourSenderId: ourId,
    peerSenderId: peerId,
    outgoingRotationInterval: rotationInterval,
    headerEncoding: plainEncoding,
    dataEncoding: plainEncoding,
    maxFragmentSize: 1000,
  );
}

void main() {
  test('a full handshake establishes matching peer records on both sides', () async {
    final alice = _newSession('alice', 'bob');
    final bob = _newSession('bob', 'alice');
    await _completeHandshake(alice, bob);

    expect(alice.record, isNotNull);
    expect(bob.record, isNotNull);
    expect(
      await alice.record!.outgoingKey.extractBytes(),
      equals(await bob.record!.incomingKey.extractBytes()),
    );
  });

  test('data sent after the handshake round-trips', () async {
    final alice = _newSession('alice', 'bob');
    final bob = _newSession('bob', 'alice');
    await _completeHandshake(alice, bob);

    final packed = await alice.sendData('hello bob'.codeUnits);
    SessionEvent? event;
    for (final fragment in packed.fragments) {
      event = await bob.receiveFragment(fragment);
    }
    expect(event, isA<DataReceived>());
    expect((event as DataReceived).plaintext, equals('hello bob'.codeUnits));
  });

  test('an unrecognized sender before any handshake is dropped, not thrown', () async {
    final bob = _newSession('bob', 'alice');
    // Something claiming to be from a third party neither certificate nor data -- bob has no
    // record for it and it won't authenticate under any bootstrap key bob tries either, since
    // it's not even correctly formed. Should fail closed quietly (return null), not crash.
    final result = await bob.receiveFragment(List<int>.filled(60, 0));
    expect(result, isNull);
  });

  test('recovery: a fresh certificate from an already-known peer re-establishes the session', () async {
    final alice = _newSession('alice', 'bob');
    final bob = _newSession('bob', 'alice');
    await _completeHandshake(alice, bob);
    final oldBobOutgoingKeyBytes = await bob.record!.outgoingKey.extractBytes();

    // Alice "forgets everything" -- a brand new session, no memory of the old one.
    final freshAlice = _newSession('alice', 'bob');
    final newCert = await freshAlice.ensureCertificateSent();

    SessionEvent? bobEvent;
    for (final fragment in newCert.fragments) {
      bobEvent = await bob.receiveFragment(fragment);
    }

    expect(bobEvent, isA<PeerEstablished>());
    final newBobOutgoingKeyBytes = await bob.record!.outgoingKey.extractBytes();
    expect(newBobOutgoingKeyBytes, isNot(equals(oldBobOutgoingKeyBytes)));
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/session_test.dart`
Expected: FAIL — `PeerSession` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```dart
// protocol/lib/src/session.dart
import 'dart:typed_data';

import 'encodings.dart';
import 'envelope.dart';
import 'handshake.dart';
import 'peer.dart';

/// Something [PeerSession.receiveFragment] can report back once a logical message finishes
/// reassembling -- either real data, or the side effect of a handshake (first contact or
/// recovery) having just completed. `sealed` so callers get exhaustiveness checking.
sealed class SessionEvent {}

class DataReceived extends SessionEvent {
  final Uint8List plaintext;
  DataReceived(this.plaintext);
}

class PeerEstablished extends SessionEvent {
  final PeerRecord record;
  PeerEstablished(this.record);
}

/// Ties together certificate exchange, key selection, and recovery into one per-peer API --
/// protocol spec §5's "key selection on receive" and "recovery from one-sided session loss",
/// made concrete. Holds at most one in-progress incoming [Reassembler] at a time, matching the
/// medium's own one-logical-message-at-a-time delivery per peer (protocol spec §3).
class PeerSession {
  final String ourSenderId;
  final String peerSenderId;
  final int outgoingRotationInterval;
  final ChunkEncoding headerEncoding;
  final ChunkEncoding dataEncoding;
  final int maxFragmentSize;

  PeerRecord? _record;
  OutgoingCertificate? _ourCertificate;
  Reassembler? _activeReassembler;
  bool _activeReassemblerIsBootstrap = false;

  PeerSession({
    required this.ourSenderId,
    required this.peerSenderId,
    required this.outgoingRotationInterval,
    required this.headerEncoding,
    required this.dataEncoding,
    required this.maxFragmentSize,
    PeerRecord? existingRecord,
  }) : _record = existingRecord;

  PeerRecord? get record => _record;

  /// Sends our own certificate if we haven't already for this session -- idempotent, since
  /// protocol spec §5 says sending it needs nothing from the peer and it's fine for both sides to
  /// do this independently, even redundantly.
  Future<PackedMessage> ensureCertificateSent() async {
    if (_ourCertificate == null) {
      _ourCertificate = await sendCertificate(
        ourSenderId: ourSenderId,
        recipientId: peerSenderId,
        outgoingRotationInterval: outgoingRotationInterval,
        headerEncoding: headerEncoding,
        dataEncoding: dataEncoding,
        maxFragmentSize: maxFragmentSize,
      );
    }
    return _ourCertificate!.packed;
  }

  /// Encrypts and packs `plaintext` under the current outgoing directional key. Requires a
  /// completed handshake ([record] non-null) -- protocol spec §5: "sending data to a peer requires
  /// having already received their certificate."
  Future<PackedMessage> sendData(List<int> plaintext) async {
    final currentRecord = _record;
    if (currentRecord == null) {
      throw StateError('Cannot send data to $peerSenderId before a handshake has completed!');
    }
    final packed = await packMessage(
      plaintext: plaintext,
      key: currentRecord.outgoingKey,
      headerEncoding: headerEncoding,
      dataEncoding: dataEncoding,
      maxFragmentSize: maxFragmentSize,
      messageCounter: currentRecord.outgoingCounter,
    );
    currentRecord.outgoingCounter++;
    return packed;
  }

  /// Feeds one incoming wire fragment. Returns a [SessionEvent] once a logical message finishes
  /// reassembling, or `null` if more fragments are still expected, or if the fragment couldn't be
  /// attributed to anything at all (fails closed quietly, per protocol spec §2's reliable-medium
  /// assumption -- a genuinely foreign or corrupted fragment isn't expected traffic to begin with).
  Future<SessionEvent?> receiveFragment(List<int> wireBytes) async {
    if (_activeReassembler == null) {
      final started = await _startReassembler(wireBytes);
      if (!started) return null;
      // _startReassembler already fed `wireBytes` to the header it started, so fall through to
      // check completion below rather than feeding it again.
    } else {
      final result = await _feedActive(wireBytes);
      if (result != null) return result;
      return null;
    }
    return _checkActiveCompletion();
  }

  Future<bool> _startReassembler(List<int> wireBytes) async {
    final currentRecord = _record;
    if (currentRecord != null) {
      final dataReassembler = Reassembler(
        key: currentRecord.incomingKey,
        headerEncoding: headerEncoding,
        dataEncoding: dataEncoding,
        messageCounter: currentRecord.incomingCounter,
      );
      try {
        final plaintext = await dataReassembler.addFragment(wireBytes);
        _activeReassembler = dataReassembler;
        _activeReassemblerIsBootstrap = false;
        if (plaintext != null) {
          currentRecord.incomingCounter++;
          _activeReassembler = null;
          // Single-fragment message -- report it via the same path the multi-fragment case uses.
          _pendingResult = DataReceived(plaintext);
        }
        return true;
      } on TamperedHeaderError {
        // Falls through to the bootstrap-key attempt below -- protocol spec §5's recovery path.
      }
    }

    // Sender is the peer, recipient is us -- matches sendCertificate's (ourSenderId, recipientId)
    // ordering from the peer's own point of view.
    final key = await bootstrapKey(peerSenderId, ourSenderId);
    final bootstrapReassembler = Reassembler(
      key: key,
      headerEncoding: headerEncoding,
      dataEncoding: dataEncoding,
      transmitNonce: true,
    );
    try {
      final plaintext = await bootstrapReassembler.addFragment(wireBytes);
      _activeReassembler = bootstrapReassembler;
      _activeReassemblerIsBootstrap = true;
      if (plaintext != null) {
        _activeReassembler = null;
        _pendingResult = await _completeFromCertificate(plaintext);
      }
      return true;
    } on TamperedHeaderError {
      return false; // Not attributable to anything this session knows -- drop it.
    } on FormatException {
      return false;
    }
  }

  SessionEvent? _pendingResult;

  Future<Uint8List?> _feedActive(List<int> wireBytes) async {
    final plaintext = await _activeReassembler!.addFragment(wireBytes);
    if (plaintext == null) return null;
    _activeReassembler = null;
    if (_activeReassemblerIsBootstrap) {
      _pendingResult = await _completeFromCertificate(plaintext);
    } else {
      _record!.incomingCounter++;
      _pendingResult = DataReceived(plaintext);
    }
    return plaintext;
  }

  SessionEvent? _checkActiveCompletion() {
    final result = _pendingResult;
    _pendingResult = null;
    return result;
  }

  Future<SessionEvent> _completeFromCertificate(List<int> plaintext) async {
    final theirCertificate = decodeCertificate(plaintext);
    if (_ourCertificate == null) {
      await ensureCertificateSent();
    }
    final newRecord = await completeHandshake(ours: _ourCertificate!, theirs: theirCertificate);
    _record = newRecord;
    return PeerEstablished(newRecord);
  }
}
```

- [ ] **Step 4: Export from the barrel file**

```dart
// protocol/lib/airwire_protocol.dart
export 'src/session.dart';
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd protocol && dart test test/session_test.dart`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full test suite to confirm nothing else broke**

Run: `cd protocol && dart test`
Expected: PASS (every test across every file, protocol-core and this plan combined).

- [ ] **Step 7: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add PeerSession, completing protocol spec §5"
```

---

## What's next (not part of this plan)

- **§6 key rotation** — a separate follow-on plan. `PeerRecord` already has the fields it needs
  (`rootKey`, both counters, both rotation intervals); what's missing is the trigger logic in
  `PeerSession.sendData`/`receiveFragment` and extending the envelope's header to actually carry
  and parse rotation material (deferred in the protocol-core plan, `n_tag`'s formula already covers
  it).
- **Peer-record persistence** — `PeerSession` holds its `PeerRecord` in memory only. A future
  Hive-backed layer needs to serialize it (including both counters, whose correctness the header
  nonce depends on) and pass it back in via `PeerSession`'s `existingRecord` constructor parameter
  on app restart.
- **`medium-interface.md` as Dart abstract classes, and the Odnoklassniki wrapper** — unaffected by
  anything in this plan, still the natural next slices after protocol logic is complete.
