# Medium interface — what a wrapper must and should provide

> **Status:** draft interface definition, documentation only — no code yet.
> **Relationship to other docs:** the **required** section below is exactly the medium contract
> already defined in the [messaging protocol spec](superpowers/specs/2026-08-27-messaging-protocol-design.md#3-layering-and-the-medium-contract)
> §3, restated here alongside everything else a real wrapper might expose. The **optional** section
> is new — it formalizes the capability wishlist from
> [medium-candidates.md](medium-candidates.md) so a candidate medium (Odnoklassniki first) can be
> checked against a fixed list instead of judged ad hoc.
> **Scope:** this is an application-facing interface a medium *wrapper* implements — broader than
> what the core wire protocol strictly needs. A wrapper that only implements the required section is
> a fully valid, complete medium as far as the protocol is concerned; everything optional exists to
> support the app built on top of it.

## Required

A candidate medium must provide all of these **natively** — there's no substitute for any of them,
because the wire protocol (§4–§6 of the protocol spec) cannot function without them at all.

| Method | Signature | Why required |
| --- | --- | --- |
| Own identity | `my_id` | Without a stable address for this account, nothing can address it back. |
| Send text | `send(peer_id, text) -> ()` | The floor every disguise mode needs — plain, base64, and both Markov modes all produce plain text output; nothing works without this. |
| Receive text | `receive() -> (peer_id, text)` | Symmetric counterpart to send. |
| Size budget | `max_message_size` | The fragmentation/compaction logic (protocol spec §4) needs to know its budget to operate at all. |

**Required properties of send/receive, not separate methods** (protocol spec §2, constraint 4):
lossless delivery, in-order delivery *per peer* (no ordering guaranteed across different peers'
streams), and no silent corruption. A medium that can't promise these isn't disqualified outright,
but the protocol's whole "no ack/retry layer" simplification (§2, §7) stops holding, and that's a
bigger conversation than this document — flag it rather than assume it away if a candidate is shaky
here.

## Optional

For each of these: what it unlocks, and — per your framing — what a "reasonable substitute" looks
like when the medium doesn't provide it natively.

### Attachments

| Method | Unlocks | If absent, substitute |
| --- | --- | --- |
| `sendImage`/`receiveImage` | The image-steganography disguise modes (`SYNTHESIS_*`) | Fall back to text-only disguise modes (plain/base64/Markov) on this medium — nothing else changes. |
| `sendVoiceNote`/`receiveVoiceNote` | Nothing *yet* — no voice disguise mode exists in the protocol today; cataloged because it was on the original wishlist and may connect to future work (possibly the separate [airwave](research-proposal.md) track) | None needed right now; revisit if a voice-carrying disguise mode is ever designed. |
| `sendFile`/`receiveFile` (generic attachment) | A potential future "opaque file" disguise carrier, a third option alongside text and image — not designed yet | Base64-encode into a text message — this already exists (`Base64Encoding`). |

### Discovery (all pure UX conveniences — none of these affect protocol correctness)

| Method | Unlocks | If absent, substitute |
| --- | --- | --- |
| `listChats() -> [peer_id]` | Showing existing conversation threads in the app | Rely entirely on local peer records (protocol spec §5) — the protocol never trusts medium-side history for correctness anyway (§2: local storage is authoritative; see also medium-candidates.md and protocol spec §10 on why carrier-retained history is unreliable *and* a disguise-persistence risk, not something to lean on). |
| `getChatHistory(peer_id) -> [messages]` | Same as above | Same as above. |
| `getContacts() -> [peer_id]` | Picking a chat partner from an existing list instead of typing/pasting a raw ID | User enters the peer's ID manually, or the app builds its own "known peers" list locally from message history over time. |
| `getProfile(peer_id) -> {display_name, photo}` | A human-friendly label/avatar in the UI | Show the raw `peer_id` as an opaque handle. |
| `resolvePeerId(query) -> peer_id` | Onboarding by username/handle instead of a raw ID | User must already know and provide the exact `peer_id`. |

### Hygiene

| Method | Unlocks | If absent, substitute |
| --- | --- | --- |
| `deleteMessage(message_ref) -> ()` | Directly implements the protocol spec's §10 recommendation — deleting our own processed messages from the medium's own store shrinks the disguise-persistence exposure window carrier-side retention creates | **None.** If a medium can't delete, that mitigation just isn't available there — worth being upfront about rather than implying every medium can close this gap. |

### Explicitly out of scope for this version

- **Voice calls** — on your list as "for later." Not specified here at all; a placeholder for future
  work, not an oversight.
- **Presence/online status** — came to mind while drafting this (not on your original list). No
  current use in the protocol (delivery is already assumed reliable regardless of real-time
  presence, §2), so leaving it out rather than speculatively designing for it — flag if you want it
  added.
- **Delivery/read receipts** — same reasoning as presence: possible future UX nicety, no protocol
  dependency, not included now.

## Checking a candidate against this list

Once a wrapper is being built (Odnoklassniki first), the natural next step is running its confirmed
and unconfirmed capabilities from medium-candidates.md against this table directly — required section
first (already looks solid for Odnoklassniki: text send/receive, generous size budget implied by
attachment support), then optional, to see exactly which substitutes actually get exercised versus
which capabilities land natively.
