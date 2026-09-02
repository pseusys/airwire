/// The required capability contract from docs/medium-interface.md — every
/// medium wrapper (Odnoklassniki first) implements this. `receive()` is a
/// general inbox across all known conversations, not scoped to one peer.
abstract class Medium {
  String get myId;
  int get maxMessageSize;
  Future<void> send(String peerId, String text);
  Stream<(String peerId, String text)> receive();
}
