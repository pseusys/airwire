/// The required capability contract from docs/medium-interface.md — every
/// medium wrapper (Odnoklassniki first) implements this. `receive()` is a
/// general inbox across all known conversations, not scoped to one peer.
abstract class Medium {
  String get myId;
  int get maxMessageSize;
  Future<void> send(String peerId, String text);
  Stream<(String peerId, String text)> receive();

  /// Releases any resources held for `receive()` (poll timers, stream
  /// controllers, ...). Callers that use `receive()` must call this when
  /// they're done with the medium (e.g. on logout) or background polling
  /// keeps running indefinitely against a possibly-stale credential.
  void dispose();
}
