import 'dart:io';

import 'package:airwire_medium/airwire_medium.dart';
import 'package:hive/hive.dart';
import 'package:test/test.dart';

void main() {
  late Directory tempDir;

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('airwire_auth_store_test');
    Hive.init(tempDir.path);
  });

  tearDown(() async {
    await Hive.deleteFromDisk();
    await tempDir.delete(recursive: true);
  });

  test('takePendingFlow returns null when nothing was saved', () async {
    final store = await AuthStore.open();
    expect(store.takePendingFlow(), isNull);
  });

  test('takePendingFlow returns and clears a saved flow', () async {
    final store = await AuthStore.open();
    await store.savePendingFlow(
      const PendingFlow(codeVerifier: 'verifier-1', state: 'state-1'),
    );

    final flow = store.takePendingFlow();
    expect(flow?.codeVerifier, equals('verifier-1'));
    expect(flow?.state, equals('state-1'));
    expect(store.takePendingFlow(), isNull);
  });

  test('loadTokens returns null when nothing was saved', () async {
    final store = await AuthStore.open();
    expect(store.loadTokens(), isNull);
  });

  test('saveTokens then loadTokens round-trips all fields', () async {
    final store = await AuthStore.open();
    await store.saveTokens(const VkTokens(
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      vkUserId: '12345',
      expiresInSeconds: 3600,
    ));

    final tokens = store.loadTokens();
    expect(tokens?.accessToken, equals('access-1'));
    expect(tokens?.refreshToken, equals('refresh-1'));
    expect(tokens?.vkUserId, equals('12345'));
    expect(tokens?.expiresInSeconds, equals(3600));
  });

  test('clearTokens removes saved tokens', () async {
    final store = await AuthStore.open();
    await store.saveTokens(const VkTokens(
      accessToken: 'access-1',
      refreshToken: null,
      vkUserId: '12345',
      expiresInSeconds: 3600,
    ));
    await store.clearTokens();
    expect(store.loadTokens(), isNull);
  });
}
