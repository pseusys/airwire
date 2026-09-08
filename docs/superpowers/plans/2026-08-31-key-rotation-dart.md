# Key Rotation (Dart) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the messaging protocol spec's §6 (key rotation) on top of the
[handshake plan](2026-08-30-handshake-dart.md) — per-direction directional-key rotation triggered
by message count, with the header/data key split worked out precisely in
[`docs/crypto-summary.md`](../../crypto-summary.md) §4.

**Architecture:** A small, targeted extension to `envelope.dart` (the wire-format change: a header
can optionally carry 32 bytes of rotation material, and which key encrypts the data portion can
differ from which key encrypts the header) plus rotation logic added to `PeerSession` in
`session.dart`. No new files — this plan only touches what already exists.

**Tech Stack:** Same as prior plans — Dart 3, `package:cryptography`, `package:test`.

**Scope boundary:** Deriving the rotated key (`derive_key(root_key, current_key, material)`) is
deliberately *not* envelope.dart's concern — `packMessage`/`Reassembler` only need to know which
already-computed key encrypts which part of the message. `packMessage`'s caller (Task 3 below)
pre-computes the new key before calling it, since it has `material` in hand from the start;
`Reassembler` computes it internally (Task 1), since it only learns `material` mid-parse, after
decrypting the header. This mirrors an inherent asymmetry, not an arbitrary design choice — see
crypto-summary.md §4.

## Global Constraints

- Same as prior plans: Dart SDK `>=3.0.0 <4.0.0`, no Flutter dependency, no floating-point
  arithmetic in any coder path, every public class/function gets a `///` doc comment explaining why.
- This plan assumes the protocol-core and handshake plans are already implemented and passing.

---

## Task 1: Extend the envelope for rotation material

**Files:**
- Modify: `protocol/lib/src/envelope.dart`
- Modify: `protocol/test/envelope_pack_test.dart`
- Modify: `protocol/test/envelope_reassemble_test.dart`

**Interfaces:**
- Consumes: `deriveKey` (Task 2, `crypto.dart`) — newly needed by `Reassembler` to derive the
  rotated data key internally.
- Produces (modifies existing signatures, additive so no existing caller breaks):
  - `Future<PackedMessage> packMessage({..., SecretKey? dataKey, List<int>? rotationMaterial})` —
    `dataKey` defaults to `key` (the header key) when omitted; `rotationMaterial`, when non-null,
    must be exactly 32 bytes and is embedded in the header and folded into `n_tag`'s scope.
  - `class Reassembler { Reassembler({..., bool expectRotationMaterial = false, SecretKey? rootKey}); SecretKey get resolvedDataKey; }`
    — `rootKey` is required when `expectRotationMaterial: true` (the derivation needs it once
    `material` is recovered from the header) and ignored otherwise. `resolvedDataKey` exposes
    whichever key ended up decrypting the data portion, so a caller that needs to persist a
    rotated key (key-rotation plan Task 4) can read it back instead of re-deriving it.

- [ ] **Step 1: Write the failing tests**

Add to `protocol/test/envelope_pack_test.dart`:

```dart
  test('rotation material makes the header 32 bytes longer', () async {
    final key = SecretKey(List<int>.filled(32, 61));
    final withoutRotation = await packMessage(
      plaintext: 'hi'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
    );
    final withRotation = await packMessage(
      plaintext: 'hi'.codeUnits,
      key: key,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
      rotationMaterial: List<int>.filled(32, 9),
    );
    expect(
      withRotation.fragments.first.length,
      equals(withoutRotation.fragments.first.length + 32),
    );
  });

  test('the data portion is encrypted with dataKey, not the header key, when they differ', () async {
    final headerKey = SecretKey(List<int>.filled(32, 63));
    final newDataKey = SecretKey(List<int>.filled(32, 64));
    final packed = await packMessage(
      plaintext: 'secret payload'.codeUnits,
      key: headerKey,
      dataKey: newDataKey,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
      rotationMaterial: List<int>.filled(32, 9),
    );

    // Decrypting the data portion with headerKey (wrong) must fail; with newDataKey must succeed.
    // Reassembler isn't used here on purpose -- this test checks packMessage's own key-selection
    // in isolation, via a hand-rolled partial decrypt mirroring what Task 2's Reassembler will do.
    // data_nonce is derived from headerKey (not dataKey) and the counter, same as header_nonce --
    // see this task's opening note on why the derivation key and the AEAD key can differ safely.
    final headerCiphertext = packed.fragments.first.sublist(0, 58); // base(26) + material(32)
    final headerPlain = await streamDecrypt(headerKey, await _testHeaderNonce(headerKey, 0), headerCiphertext);
    final dataTag = headerPlain.sublist(0, 16);
    final dataNonce = await _testDataNonce(headerKey, 0);
    final dataCiphertext = packed.fragments.first.sublist(58);

    expect(
      () => aeadDecrypt(headerKey, dataNonce, dataCiphertext, dataTag),
      throwsA(anything),
    );
    final plaintext = await aeadDecrypt(newDataKey, dataNonce, dataCiphertext, dataTag);
    expect(plaintext, equals('secret payload'.codeUnits));
  });
```

Add these helpers near the top of `protocol/test/envelope_pack_test.dart`, alongside the existing
`import` lines (they mirror `_headerNonceFor`/`_dataNonceFor`'s formulas from `envelope.dart`, kept
local to the test since those functions aren't exported):

```dart
Future<Uint8List> _testHeaderNonce(SecretKey key, int counter) async {
  final keyBytes = await key.extractBytes();
  final counterBytes = ByteData(4)..setUint32(0, counter);
  return deriveKey(
    [keyBytes, 'airwire-header-nonce'.codeUnits, counterBytes.buffer.asUint8List()],
    length: 24,
  );
}

Future<Uint8List> _testDataNonce(SecretKey key, int counter) async {
  final keyBytes = await key.extractBytes();
  final counterBytes = ByteData(4)..setUint32(0, counter);
  return deriveKey(
    [keyBytes, 'airwire-data-nonce'.codeUnits, counterBytes.buffer.asUint8List()],
    length: 24,
  );
}
```

Add to `protocol/test/envelope_reassemble_test.dart`:

```dart
  test('round-trips a rotation-carrying message, deriving the new key internally', () async {
    final rootKey = SecretKey(List<int>.filled(32, 71));
    final currentKey = SecretKey(List<int>.filled(32, 72));
    final material = List<int>.filled(32, 9);
    final newKeyBytes = await deriveKey(
      [await rootKey.extractBytes(), await currentKey.extractBytes(), material],
      length: 32,
    );
    final newKey = SecretKey(newKeyBytes);

    final plaintext = 'rotated'.codeUnits;
    final packed = await packMessage(
      plaintext: plaintext,
      key: currentKey,
      dataKey: newKey,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 5,
      rotationMaterial: material,
    );

    final reassembler = Reassembler(
      key: currentKey,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      messageCounter: 5,
      expectRotationMaterial: true,
      rootKey: rootKey,
    );
    final result = await reassembler.addFragment(packed.fragments.single);
    expect(result, equals(plaintext));
  });

  test('a tampered rotation material is caught by n_tag, same as a tampered N', () async {
    final rootKey = SecretKey(List<int>.filled(32, 73));
    final currentKey = SecretKey(List<int>.filled(32, 74));
    final material = List<int>.filled(32, 9);
    final newKeyBytes = await deriveKey(
      [await rootKey.extractBytes(), await currentKey.extractBytes(), material],
      length: 32,
    );
    final packed = await packMessage(
      plaintext: 'rotated'.codeUnits,
      key: currentKey,
      dataKey: SecretKey(newKeyBytes),
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      maxFragmentSize: 1000,
      messageCounter: 0,
      rotationMaterial: material,
    );

    // Flip a bit inside the material field (bytes 26-57 of the header plaintext, right after the
    // base 26-byte header).
    final tampered = Uint8List.fromList(packed.fragments.first);
    tampered[26] ^= 0xff;

    final reassembler = Reassembler(
      key: currentKey,
      headerEncoding: plainEncoding,
      dataEncoding: plainEncoding,
      messageCounter: 0,
      expectRotationMaterial: true,
      rootKey: rootKey,
    );
    expect(
      () => reassembler.addFragment(tampered),
      throwsA(isA<TamperedHeaderError>()),
    );
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/envelope_pack_test.dart test/envelope_reassemble_test.dart`
Expected: FAIL — `dataKey`/`rotationMaterial`/`expectRotationMaterial`/`rootKey` aren't recognized
parameters yet.

- [ ] **Step 3: Modify `packMessage`**

Replace the existing `packMessage` function in `protocol/lib/src/envelope.dart` (from the
handshake plan's Task 1 version) with:

```dart
/// Encrypts `plaintext` as a whole (protocol spec §4's data AEAD), disguises the result and a
/// preceding header describing it, and splits everything into `maxFragmentSize`-bounded wire
/// fragments. The first fragment always carries the header; a message that fits in one fragment
/// needs no others (`N = 0`) -- see protocol spec §4 for the full wire-shape rationale.
///
/// Exactly one of `messageCounter` or `transmitNonce: true` must be given (see the handshake
/// plan's Task 1 for why certificates need the latter). `dataKey`, when given, encrypts the data
/// portion instead of `key` -- `key` always encrypts the header regardless. `rotationMaterial`,
/// when given, must be exactly 32 bytes; it's embedded in the header and folded into `n_tag`'s
/// scope (protocol spec §4/§6) -- this function doesn't derive `dataKey` from it, that's the
/// caller's job (crypto-summary.md §4 explains why the derivation belongs on the caller's side
/// here specifically, unlike Reassembler).
Future<PackedMessage> packMessage({
  required List<int> plaintext,
  required SecretKey key,
  SecretKey? dataKey,
  required ChunkEncoding headerEncoding,
  required ChunkEncoding dataEncoding,
  required int maxFragmentSize,
  int? messageCounter,
  bool transmitNonce = false,
  List<int>? rotationMaterial,
}) async {
  assert(
    transmitNonce ? messageCounter == null : messageCounter != null,
    'Pass exactly one of messageCounter (data messages) or transmitNonce: true (certificates).',
  );
  assert(
    rotationMaterial == null || rotationMaterial.length == _rotationMaterialSize,
    'rotationMaterial must be exactly $_rotationMaterialSize bytes when given.',
  );

  final effectiveDataKey = dataKey ?? key;
  final effectiveRotationMaterial = rotationMaterial ?? const <int>[];

  final headerNonce =
      transmitNonce ? randomBytes(aeadNonceSize) : await _headerNonceFor(key, messageCounter!);
  // Both nonces always derive from `key` (the header key) and never from `dataKey` -- on a
  // rotation-carrying message `key` is still the pre-rotation key, exactly like `header_nonce`
  // itself (protocol spec §6: the header, and everything it's keyed from, stays on the old key).
  // Only the AEAD operation that uses `dataNonce` switches to `effectiveDataKey`; the derivation
  // rule for the nonce itself never changes. No collision risk: `effectiveDataKey`'s first-ever
  // use pairs it with a nonce derived from a different key, and future messages on that key derive
  // their own nonce from it directly, starting at counter 0.
  final dataNonce = transmitNonce
      ? await _dataNonceFromTransmittedNonce(key, headerNonce)
      : await _dataNonceFor(key, messageCounter!);
  final aead = await aeadEncrypt(effectiveDataKey, dataNonce, plaintext);
  final dataAtoms = dataEncoding.encodeAtoms(aead.ciphertext, dataNonce).toList();
  final headerPlainSize = _headerBaseSize + effectiveRotationMaterial.length;

  final nonceWire = transmitNonce
      ? headerEncoding.encodeAtoms(headerNonce, const []).expand((atom) => atom).toList()
      : const <int>[];

  final minimumBudget = (transmitNonce ? headerEncoding.minimumBudgetForHeader(aeadNonceSize) : 0) +
      headerEncoding.minimumBudgetForHeader(headerPlainSize);
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
    final nTag = await _computeNTag(key, dataNonce, nBytes, effectiveRotationMaterial);
    final headerPlain = <int>[
      ...aead.tag,
      ..._uint32be(aead.ciphertext.length),
      ...nBytes,
      ...nTag,
      ...effectiveRotationMaterial,
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

Also restore the `_rotationMaterialSize` constant this function now references (it was removed as
unused in the protocol-core plan's self-review; add it back alongside the other field-size
constants near the top of `envelope.dart`):

```dart
const int _rotationMaterialSize = 32;
```

- [ ] **Step 4: Modify `Reassembler`**

Replace the `Reassembler` class's constructor and `_parseFirstFragment` method in
`protocol/lib/src/envelope.dart` with:

```dart
class Reassembler {
  final SecretKey key;
  final ChunkEncoding headerEncoding;
  final ChunkEncoding dataEncoding;
  final int? messageCounter;
  final bool transmitNonce;
  final bool expectRotationMaterial;
  final SecretKey? rootKey;

  bool _headerParsed = false;
  int _expectedMoreFragments = 0;
  late Uint8List _dataNonce;
  late Uint8List _dataTag;
  late int _dataLength;
  late SecretKey _dataKey;
  final List<int> _dataWireBytes = [];

  Reassembler({
    required this.key,
    required this.headerEncoding,
    required this.dataEncoding,
    this.messageCounter,
    this.transmitNonce = false,
    this.expectRotationMaterial = false,
    this.rootKey,
  })  : assert(
          transmitNonce ? messageCounter == null : messageCounter != null,
          'Pass exactly one of messageCounter (data messages) or transmitNonce: true (certificates).',
        ),
        assert(
          !expectRotationMaterial || rootKey != null,
          'rootKey is required when expectRotationMaterial is true.',
        );

  /// The key actually used to decrypt the data portion -- [key] itself, unless rotation material
  /// was present, in which case the freshly-derived rotated key. Only meaningful after
  /// [addFragment] has returned non-null. Callers that need to persist a rotated key (Task 4 of
  /// the key-rotation plan) read it from here rather than re-deriving it a second time.
  SecretKey get resolvedDataKey => _dataKey;

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
    return aeadDecrypt(_dataKey, _dataNonce, dataResult.plaintext, _dataTag);
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
    // Always derived from `key` (the pre-rotation key on a rotation-carrying message) and the
    // same counter/transmitted-nonce input as `headerNonce` -- see packMessage's matching comment
    // for why this is safe even though the AEAD operation that ends up using it may switch keys.
    final dataNonce = transmitNonce
        ? await _dataNonceFromTransmittedNonce(key, headerNonce)
        : await _dataNonceFor(key, messageCounter!);

    final headerPlainSize = _headerBaseSize + (expectRotationMaterial ? _rotationMaterialSize : 0);
    final headerResult =
        headerEncoding.decode(wireBytes.sublist(offset), headerPlainSize, const []);
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
    final rotationMaterial = headerPlain.sublist(nTagOffset + _nTagSize);

    final expectedNTag = await _computeNTag(key, dataNonce, nBytes, rotationMaterial);
    if (!_bytesEqual(nTag, expectedNTag)) {
      throw TamperedHeaderError(
        'n_tag did not verify -- N or rotation material was tampered, or the key/counter/nonce is wrong!',
      );
    }

    _dataNonce = Uint8List.fromList(dataNonce);
    _dataTag = Uint8List.fromList(dataTag);
    _dataLength = dataLength;
    _expectedMoreFragments = n;
    _dataKey = rotationMaterial.isEmpty
        ? key
        : SecretKey(await deriveKey(
            [await rootKey!.extractBytes(), await key.extractBytes(), rotationMaterial],
            length: 32,
          ));
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
Expected: PASS (every test across every file, all three plans combined).

- [ ] **Step 7: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add rotation-material support to the envelope"
```

---

## Task 2: PeerRecord rotation helpers

**Files:**
- Modify: `protocol/lib/src/peer.dart`
- Modify: `protocol/test/peer_test.dart`

**Interfaces:**
- Consumes: nothing new.
- Produces: `bool get PeerRecord.outgoingRotationDue`, `bool get PeerRecord.incomingRotationDue` —
  pure computations from already-existing fields (protocol spec §6: "the message that reaches the
  interval").

- [ ] **Step 1: Write the failing tests**

Add to `protocol/test/peer_test.dart`:

```dart
  test('outgoingRotationDue is true exactly on the interval-reaching message', () async {
    final alice = await generateX25519KeyPair();
    final bob = await generateX25519KeyPair();
    final sharedSecret = await computeSharedSecret(alice.secretKeyPair, bob.publicKey);
    final record = await deriveSessionKeys(
      ourPublicKey: alice.publicKey,
      peerPublicKey: bob.publicKey,
      sharedSecret: sharedSecret,
      outgoingRotationInterval: 3,
      incomingRotationInterval: 5,
    );

    expect(record.outgoingRotationDue, isFalse); // counter=0, about to send message 1 of 3
    record.outgoingCounter = 1;
    expect(record.outgoingRotationDue, isFalse); // about to send message 2 of 3
    record.outgoingCounter = 2;
    expect(record.outgoingRotationDue, isTrue); // about to send message 3 of 3 -- triggers
  });

  test('incomingRotationDue tracks incomingCounter against incomingRotationInterval separately', () async {
    final alice = await generateX25519KeyPair();
    final bob = await generateX25519KeyPair();
    final sharedSecret = await computeSharedSecret(alice.secretKeyPair, bob.publicKey);
    final record = await deriveSessionKeys(
      ourPublicKey: alice.publicKey,
      peerPublicKey: bob.publicKey,
      sharedSecret: sharedSecret,
      outgoingRotationInterval: 3,
      incomingRotationInterval: 5,
    );

    record.incomingCounter = 4;
    expect(record.incomingRotationDue, isTrue);
    expect(record.outgoingRotationDue, isFalse);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd protocol && dart test test/peer_test.dart`
Expected: FAIL — `outgoingRotationDue`/`incomingRotationDue` don't exist yet.

- [ ] **Step 3: Write minimal implementation**

Add to the `PeerRecord` class in `protocol/lib/src/peer.dart`:

```dart
  /// True when the *next* message sent on [outgoingKey] is the one that reaches
  /// [outgoingRotationInterval] -- protocol spec §6's rotation trigger, checked before sending.
  bool get outgoingRotationDue => outgoingCounter + 1 == outgoingRotationInterval;

  /// True when the *next* message expected on [incomingKey] is the one the peer announced their
  /// own rotation would land on -- checked before parsing an incoming header, so the receiver
  /// knows to expect rotation material without any signal being transmitted (protocol spec §6).
  bool get incomingRotationDue => incomingCounter + 1 == incomingRotationInterval;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd protocol && dart test test/peer_test.dart`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: add PeerRecord rotation-due checks"
```

---

## Task 3: Rotation on send

**Files:**
- Modify: `protocol/lib/src/session.dart`
- Modify: `protocol/test/session_test.dart`

**Interfaces:**
- Consumes: `outgoingRotationDue` (Task 2, `peer.dart`); `randomBytes`, `deriveKey` (Task 2,
  `crypto.dart`); extended `packMessage` (Task 1, `envelope.dart`).
- Produces: `PeerSession.sendData` (existing method from the handshake plan, behavior extended —
  same signature, no interface change).

- [ ] **Step 1: Write the failing test**

Add to `protocol/test/session_test.dart`:

```dart
  test('sending enough messages triggers a rotation, and outgoing state resets', () async {
    final alice = _newSession('alice', 'bob', rotationInterval: 3);
    final bob = _newSession('bob', 'alice', rotationInterval: 100);
    await _completeHandshake(alice, bob);

    final keyBeforeRotation = await alice.record!.outgoingKey.extractBytes();

    // Messages 1 and 2 -- no rotation yet.
    await alice.sendData('one'.codeUnits);
    await alice.sendData('two'.codeUnits);
    expect(alice.record!.outgoingCounter, equals(2));
    expect(await alice.record!.outgoingKey.extractBytes(), equals(keyBeforeRotation));

    // Message 3 -- reaches the interval, rotates.
    await alice.sendData('three'.codeUnits);
    expect(alice.record!.outgoingCounter, equals(0));
    expect(await alice.record!.outgoingKey.extractBytes(), isNot(equals(keyBeforeRotation)));
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd protocol && dart test test/session_test.dart`
Expected: FAIL — `sendData` doesn't rotate yet, so the counter/key assertions after message 3 fail.

- [ ] **Step 3: Write minimal implementation**

Replace `PeerSession.sendData` in `protocol/lib/src/session.dart` with:

```dart
  /// Encrypts and packs `plaintext` under the current outgoing directional key. Requires a
  /// completed handshake ([record] non-null) -- protocol spec §5: "sending data to a peer requires
  /// having already received their certificate." If this is the message that reaches
  /// [PeerRecord.outgoingRotationInterval] (protocol spec §6), generates fresh rotation material,
  /// encrypts the data portion under the newly-derived key while the header still uses the current
  /// one, and switches [PeerRecord.outgoingKey] afterward.
  Future<PackedMessage> sendData(List<int> plaintext) async {
    final currentRecord = _record;
    if (currentRecord == null) {
      throw StateError('Cannot send data to $peerSenderId before a handshake has completed!');
    }

    final isRotating = currentRecord.outgoingRotationDue;
    List<int>? rotationMaterial;
    SecretKey? dataKey;
    if (isRotating) {
      rotationMaterial = randomBytes(32);
      final newKeyBytes = await deriveKey(
        [
          await currentRecord.rootKey.extractBytes(),
          await currentRecord.outgoingKey.extractBytes(),
          rotationMaterial,
        ],
        length: 32,
      );
      dataKey = SecretKey(newKeyBytes);
    }

    final packed = await packMessage(
      plaintext: plaintext,
      key: currentRecord.outgoingKey,
      dataKey: dataKey,
      headerEncoding: headerEncoding,
      dataEncoding: dataEncoding,
      maxFragmentSize: maxFragmentSize,
      messageCounter: currentRecord.outgoingCounter,
      rotationMaterial: rotationMaterial,
    );

    if (isRotating) {
      currentRecord.outgoingKey = dataKey!;
      currentRecord.outgoingCounter = 0;
    } else {
      currentRecord.outgoingCounter++;
    }
    return packed;
  }
```

Add the missing import at the top of `protocol/lib/src/session.dart`:

```dart
import 'package:cryptography/cryptography.dart';
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd protocol && dart test test/session_test.dart`
Expected: PASS. Re-run the full suite too, since this changes `sendData`'s behavior for existing
callers: `cd protocol && dart test` — expected: PASS (the earlier "data sent after the handshake
round-trips" test uses a `rotationInterval: 256` default, so it never rotates and is unaffected).

- [ ] **Step 5: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: trigger key rotation on send"
```

---

## Task 4: Rotation on receive

**Files:**
- Modify: `protocol/lib/src/session.dart`
- Modify: `protocol/test/session_test.dart`

**Interfaces:**
- Consumes: `incomingRotationDue` (Task 2, `peer.dart`); extended `Reassembler` (Task 1,
  `envelope.dart`).
- Produces: `PeerSession.receiveFragment` (existing method, behavior extended — same signature).

- [ ] **Step 1: Write the failing test**

Add to `protocol/test/session_test.dart`:

```dart
  test('the receiving side rotates in lockstep and keeps decrypting correctly after', () async {
    final alice = _newSession('alice', 'bob', rotationInterval: 3);
    final bob = _newSession('bob', 'alice', rotationInterval: 100);
    await _completeHandshake(alice, bob);

    final bobIncomingKeyBefore = await bob.record!.incomingKey.extractBytes();

    for (final message in ['one', 'two', 'three']) {
      final packed = await alice.sendData(message.codeUnits);
      SessionEvent? event;
      for (final fragment in packed.fragments) {
        event = await bob.receiveFragment(fragment);
      }
      expect(event, isA<DataReceived>());
      expect((event as DataReceived).plaintext, equals(message.codeUnits));
    }

    // Bob's incoming key must have rotated to match Alice's outgoing key, and a fourth message
    // (now under the new key on both sides) must still round-trip correctly.
    expect(await bob.record!.incomingKey.extractBytes(), isNot(equals(bobIncomingKeyBefore)));
    expect(bob.record!.incomingCounter, equals(0));

    final fourth = await alice.sendData('four'.codeUnits);
    SessionEvent? fourthEvent;
    for (final fragment in fourth.fragments) {
      fourthEvent = await bob.receiveFragment(fragment);
    }
    expect(fourthEvent, isA<DataReceived>());
    expect((fourthEvent as DataReceived).plaintext, equals('four'.codeUnits));
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd protocol && dart test test/session_test.dart`
Expected: FAIL — the receive side doesn't yet know to expect rotation material or derive the new
key, so the third message's header fails to parse against a fixed base-size assumption.

- [ ] **Step 3: Write minimal implementation**

In `protocol/lib/src/session.dart`, `_startReassembler` currently constructs a plain, non-rotation
`Reassembler` for the data-key attempt. Replace that construction:

```dart
      final dataReassembler = Reassembler(
        key: currentRecord.incomingKey,
        headerEncoding: headerEncoding,
        dataEncoding: dataEncoding,
        messageCounter: currentRecord.incomingCounter,
        expectRotationMaterial: currentRecord.incomingRotationDue,
        rootKey: currentRecord.incomingRotationDue ? currentRecord.rootKey : null,
      );
```

The same block's completion branch (where a short, single-fragment message finishes reassembling
immediately) currently just does `currentRecord.incomingCounter++;`. Replace it with logic that
also detects and applies a completed rotation, reading the resolved key straight off the
reassembler (Task 1's `resolvedDataKey`) rather than re-deriving it:

```dart
      try {
        final plaintext = await dataReassembler.addFragment(wireBytes);
        _activeReassembler = dataReassembler;
        _activeReassemblerIsBootstrap = false;
        if (plaintext != null) {
          if (currentRecord.incomingRotationDue) {
            currentRecord.incomingKey = dataReassembler.resolvedDataKey;
            currentRecord.incomingCounter = 0;
          } else {
            currentRecord.incomingCounter++;
          }
          _activeReassembler = null;
          _pendingResult = DataReceived(plaintext);
        }
        return true;
      } on TamperedHeaderError {
        // Falls through to the bootstrap-key attempt below -- protocol spec §5's recovery path.
      }
```

`_feedActive`'s non-bootstrap branch (the multi-fragment completion path) currently just does
`currentRecord.incomingCounter++;` too. Apply the identical logic there:

```dart
    if (_activeReassemblerIsBootstrap) {
      _pendingResult = await _completeFromCertificate(plaintext);
    } else {
      final currentRecord = _record!;
      if (currentRecord.incomingRotationDue) {
        currentRecord.incomingKey = _activeReassembler!.resolvedDataKey;
        currentRecord.incomingCounter = 0;
      } else {
        currentRecord.incomingCounter++;
      }
      _pendingResult = DataReceived(plaintext);
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd protocol && dart test test/session_test.dart`
Expected: PASS (all tests, including the new rotation-on-receive one).

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

Run: `cd protocol && dart test`
Expected: PASS (every test across every file, all three plans combined).

- [ ] **Step 6: Commit**

```bash
cd protocol && git add -A
git commit -m "feat: rotate the incoming key on receive, completing protocol spec §6"
```

---

## Task 5: Forward secrecy — document and verify key erasure

> **Why this is a task, not just a comment:** protocol spec §6 states forward secrecy "depends on
> erasure, not just derivation" as "an implementation requirement, not an implementation detail."
> Dart is garbage-collected, so there's no manual zeroing primitive to call the way there might be
> in a lower-level language -- what "erasure" concretely means here is *not retaining a reachable
> reference* to a superseded key anywhere, so the garbage collector is free to reclaim it. This
> task makes that check explicit rather than trusting it implicitly held from Tasks 3-4's code.

**Files:**
- Modify: `protocol/lib/src/peer.dart`
- Test: `protocol/test/peer_test.dart`

**Interfaces:**
- Consumes: nothing new.
- Produces: no new public API — this task audits and, if needed, fixes `PeerRecord`'s
  `outgoingKey`/`incomingKey` setters (Task 2 of the handshake plan) to guarantee the old
  `SecretKey` object isn't kept reachable through any other field once replaced.

- [ ] **Step 1: Write the failing test**

```dart
  test('rotating a key does not leave the old one reachable through any other field', () async {
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

    final oldOutgoingKeyBytes = await record.outgoingKey.extractBytes();
    final newOutgoingKey = SecretKey(List<int>.filled(32, 99));
    record.outgoingKey = newOutgoingKey;

    // The only fields PeerRecord exposes are outgoingKey/incomingKey/rootKey -- confirm none of
    // them still hold the superseded key's bytes.
    expect(await record.outgoingKey.extractBytes(), isNot(equals(oldOutgoingKeyBytes)));
    expect(await record.incomingKey.extractBytes(), isNot(equals(oldOutgoingKeyBytes)));
    expect(await record.rootKey.extractBytes(), isNot(equals(oldOutgoingKeyBytes)));
  });
```

- [ ] **Step 2: Run the test**

Run: `cd protocol && dart test test/peer_test.dart`
Expected: PASS already — `PeerRecord`'s setters (handshake plan Task 2) directly overwrite
`_keyMin2Max`/`_keyMax2Min` with no intermediate retained copy, and nothing else in `PeerRecord`
holds a separate reference. This test exists to make that guarantee explicit and regression-tested,
not because Task 2's code needs changing — no implementation step follows.

- [ ] **Step 3: Commit**

```bash
cd protocol && git add -A
git commit -m "test: verify PeerRecord never retains a superseded key"
```

---

## What's next (not part of this plan)

- **Peer-record persistence** across app restarts, and **medium-interface.md as Dart abstract
  classes, and the Odnoklassniki wrapper** — the same follow-on slices flagged at the end of the
  handshake plan, still unaffected by anything here. With this plan done, protocol spec §4–§6 are
  now fully implemented (text-only, no image steganography) — the next natural step is wiring a
  real medium underneath, per the original session plan.
