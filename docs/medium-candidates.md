# Medium candidates — high-reach, low-privacy platforms as transport

> **Status:** research notes, exploratory — not a design decision. Feeds into eventually picking a
> concrete first `medium` implementation for the [messaging protocol
> spec](superpowers/specs/2026-08-27-messaging-protocol-design.md), but nothing here is binding.
> See [medium-interface.md](medium-interface.md) for the required/optional capability list a
> candidate wrapper is checked against.
> **Framing:** these platforms' own privacy properties don't matter to us — the protocol supplies
> its own confidentiality and disguise entirely on top (see the protocol spec's §4–§6). All that
> matters here is whether each one satisfies the protocol's medium contract (§3: stable per-user ID,
> send/receive between arbitrary users, a workable size budget, reasonable delivery reliability) and
> a few practical extras that spec didn't need to cover.

## Two corrections to the starting assumptions, upfront

Worth surfacing before the table, since they materially change the picture:

1. **"Open API" and "allowed to use as we like" aren't always the same claim.** For platforms with an
   official bot/app registration flow (Odnoklassniki's OAuth apps, MAX's bots, VK's community
   tokens, Telegram's Bot API), using the documented API within its terms is exactly as sanctioned as
   it sounds. But **Telegram's MTProto client protocol used to automate a real personal account
   ("userbot"/"selfbot") is explicitly against Telegram's Terms of Service** and is actively enforced
   — real, documented account bans, including bans that follow the phone number to a freshly
   registered replacement account. MTProto itself is open (that's how every official Telegram app is
   built), but *using it to script a personal account instead of a hand-operated client* is the part
   that's against the rules, not the protocol's openness. Flagging this because it directly bears on
   the "control an actual user profile" preference below.
2. **Two of your four candidates are no longer operating.** ICQ shut down June 26, 2024 (VK's own
   shutdown notice pointed users to VK Messenger/VK WorkSpace). TamTam — VK's *earlier* WhatsApp-style
   messenger, once promoted by Russia's Ministry of Digital Development as a foreign-app alternative —
   was itself shut down February 27, 2026, superseded by MAX. Neither has an API left to evaluate;
   noted below for completeness, not as live candidates. This also illustrates a real pattern worth
   keeping in mind: VK has rolled up and discontinued its own messenger products twice in under two
   years (TamTam → VK Messenger → MAX), so platform churn risk isn't hypothetical for this specific
   family.

## Three different meanings of "acting as a real user," worth telling apart

Since you specifically prioritized this, it's worth being precise about what "control an actual user
profile" can mean in practice — these are not equivalent, either technically or in terms of risk:

| Model | What it is | ToS-compliant? | Example here |
| --- | --- | --- | --- |
| **OAuth delegation** | The real user authorizes your app via the platform's own consent screen; your app gets a token scoped to that user's account, through an officially sanctioned flow. | Yes — this is exactly what the flow is for. | Odnoklassniki `graph.user.messages` |
| **Userbot / selfbot** | Your app logs into a real personal account's own client protocol directly (phone number + session), impersonating a hand-operated app. | No, on platforms that document this as prohibited. | Telegram MTProto as a personal account |
| **Labeled bot/community identity** | A clearly-marked bot, group, or community account — official, fully supported, but visibly not a person in the platform's own UI. | Yes | MAX bots, VK community tokens, Telegram Bot API |

Only the first genuinely gets you "real account, no ToS risk" at the same time. The third is safest
but weakest for disguise plausibility (a "BOT" tag or community icon undermines the whole point of
looking like an ordinary person); the second gets you the appearance of a real account but at real,
demonstrated risk to that account.

## Comparison table

Telegram dropped per your call below (own opt-in E2E already reasonably good — less value in building
on top of it) rather than left in the main comparison; findings kept in the per-platform notes for the
record.

| Capability | MAX | VKontakte (vk.com) | Odnoklassniki | Yandex Messenger |
| --- | --- | --- | --- | --- |
| Send/receive text | ✅ | ✅ | ✅ (`graph.user.messages`, `graph.chat.messages`) | ✅, but org-internal only (see note) |
| List/read chats | Undocumented in what I could find | ✅ (LongPoll/history methods) | ✅ (Graph API) | ✅, org-internal only |
| Voice notes | Supported per docs, specifics thin | ✅ (audio attachment, `vk_as_voice`) | ✅ (AUDIO attachment type) | Consumer app supports it; not confirmed for Bot API |
| Other attachments | "Media files ✅" (generic) | ✅ (photo, video, document — some upload-token restrictions on community tokens) | ✅ (image/video/file/location/contact, max 5/message) | Consumer app supports it; not confirmed for Bot API |
| Voice calls | Not documented | Not documented | Not documented | Consumer app supports it; not documented for Bot API |
| Contacts list | Not documented | ✅ (`friends.get`) | Not confirmed | Org address book only, not general contacts |
| User ID / name / photo | Not documented | ✅ (`users.get`, `photo_100`/`photo_max_orig`) | Partial (`users.getCurrentUser` confirmed; broader lookup not confirmed) | Not confirmed |
| Can act as a real profile? | No — labeled bot only | No — community token only (user-token `messages.send` blocked since 2019-03-01) | **Yes** — OAuth token scoped to a consenting real user | No — org bot identity only |
| Can reach an arbitrary external user? | Likely, once contact is established | **No** — community can't message first | Requires target user's consent/permission step | **No — hard blocker**, bots confined to their own organization's members |
| Developer access barrier | **Verified Russian legal entity only**, since Sept 2025; 1–7 day review; 1 bot/org | Self-serve community/app creation | Self-serve OAuth app registration | Self-serve within a Yandex 360 Business org |
| Global app-store reach | Removed from Google Play July 2026 (EU sanctions on parent co.); still on RuStore/Huawei/Samsung/Xiaomi stores; installed apps keep working | Same removal, same date, same reason (same parent company) | Not affected by the above (separate parent) | Not affected |

*(ICQ and TamTam omitted — both fully shut down, no API to evaluate. Telegram omitted from the table —
deprioritized per your call; see the note below instead.)*

## Per-platform notes

### MAX (VK's current flagship, launched March 2025)

Genuinely huge and growing fast — 70M+ daily active users by March 2026, 85–100M registered. But the
**Russian-legal-entity-only developer gate (Sept 2025+)** is a hard structural blocker, independent
of your "users create their own accounts" plan — that plan solves *end-user* onboarding, not *our
own* ability to register a bot in the first place, since bot registration itself requires us (the
developer) to be a verified Russian legal entity. Worth confirming directly against
[maxmessengerapi.ru](https://maxmessengerapi.ru/) and `dev.max.ru` before ruling it out entirely (the
pages are JS-rendered and didn't yield full detail to automated fetching — a manual look, or a
Russian-entity-held account doing the registration, would get further than I could here), but as
documented, this isn't a "make an account" problem, it's a "who's allowed to be a developer" problem.

### VKontakte (vk.com — distinct from MAX)

Still a live, separate product with its own API (`api.vk.com`) despite MAX now being VK's flagship
consumer app — don't conflate the two. The 2019 lockdown of `messages.send` for user tokens means
**every bot-sent message on VK is visibly from a community, never a person** — this is the sharpest
mismatch against your stated preference among the four original candidates. The "community can't
message first" rule is also a real protocol-shape problem: our spec's §2 assumes either side can
initiate a chat by ID alone; VK requires the human to contact the bot's community first (or
explicitly opt in) before the community can reply — workable with onboarding instructions, but not
symmetric the way the protocol currently assumes.

### Odnoklassniki

The most interesting result of this pass, and the one I'd suggest prioritizing a closer look at:
`graph.user.messages` genuinely appears to be OAuth-delegated, real-user-scoped messaging — exactly
the "ask the user to authorize our app" model you described, and (per the taxonomy above) the only
one of the four original candidates offering that without a ToS conflict. Attachment support is the
richest of the four (up to 5 per message across image/video/audio/file/location/contact). Two things
I couldn't fully confirm and would want verified hands-on before relying on it: a general
`users.get`-equivalent for looking up an *arbitrary* other user's profile (only
`users.getCurrentUser` was confirmed), and whether `graph.user.messages` truly permits messaging a
user cold or requires the same kind of prior-contact/permission step VK enforces
(`group.isMessagesAllowed`-style checks appear elsewhere in the API, suggesting some consent gate
likely applies here too).

### Telegram — deprioritized (2026-08-30)

Not on the original list, but turned up as a strong fit for the framing during research: not
Russian-headquartered today but founded by Russians, frequently criticized for weak-by-default
privacy (regular chats aren't end-to-end encrypted, stored server-side — only opt-in "Secret Chats"
are E2E), broadest global reach and best-documented API of anything researched here. **Dropped per
your call:** Telegram already offers reasonably good opt-in privacy of its own, so there's less value
in building this project's disguise/encryption layer on top of it specifically — the platforms where
that layer adds the most (MAX, VK, OK.ru, none of which offer any E2E option at all) are a better use
of effort. This also conveniently sidesteps the one candidate whose "real profile" path carried actual
ToS/ban risk (kept below for the record, not as a live option):

- **Bot API** (fully open registration via @BotFather, no entity requirement, rich attachment/voice
  support): safe, labeled-bot identity only.
- **MTProto-as-a-personal-account** ("userbot"): gets a real profile's appearance, but is explicitly
  against Telegram's ToS and actively enforced with real, documented account bans.

### Yandex Messenger — researched, not viable

The consumer app itself does support personal, non-business use (an individual Yandex ID user can 1:1
or group-chat, up to 3000 people) — but the **only documented programmatic Bot API is confined to
Yandex 360 Business organizations, and bots can only reach members of their own organization**
(`Бот не может отправлять личные сообщения пользователям за пределами своей организации` — a bot
cannot send private messages to users outside its own organization, confirmed directly against
Yandex's own docs). No OAuth-delegation equivalent to Odnoklassniki's was found for personal-mode
accounts. This is a harder blocker than MAX's entity gate or VK's community-only restriction: it's
not about who's allowed to register, it's that the API structurally cannot reach an arbitrary external
user at all. Registering a shared "organization" and adding every one of our users to it as fake
"employees" is a theoretical workaround, but it's an awkward, likely ToS-straining hack rather than a
real fit — not recommending it. Ruling this one out unless a personal-account API surfaces that this
pass didn't find.

## Suggested next step

Odnoklassniki's OAuth-delegated user messaging remains the strongest match for what you actually asked
for (real-profile control, sanctioned, attachment-rich) and deserves a hands-on registration +
test-send pass before going further. MAX is worth a direct look at the primary docs regardless of the
entity-gate finding above, since it's the fastest-growing platform in this set by a wide margin and
that constraint is worth confirming firsthand rather than taking secondhand research as final. VK
remains a fallback if the community-only/message-first restrictions turn out to be workable in
practice. Yandex Messenger and Telegram are both set aside for now, per the above.
