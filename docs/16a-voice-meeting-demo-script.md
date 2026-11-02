# 16a · Demo script: autopilots in a Teams meeting

A 15-minute run of show for the options in [16 · Voice, meetings and avatars](16-voice-and-meetings.md). Part 1 is demoable **today** (in-meeting chat, option A, ❓ test first with checklist T1–T4). Part 2 needs the post-meeting recap (option B) and two tenant switches. Part 3 is a talk track for live transcripts (after 14 Nov 2026), calling a voice line (option D, preview) and a voice + avatar participant in the meeting (spike): **don't demo what isn't built**.

## Cast and prerequisites

| Who | Account | Role in the demo |
|---|---|---|
| Presenter | `sanjaytest@…` (manager of the instances) | Bid manager, then FinCrime L1 lead; meeting organizer |
| Colleague | A second licensed user, or a second browser profile | SME / L2 analyst |
| BankingBids | `bankingbids@…` (RFP Bid Desk instance) | Invited attendee |
| MiraRetail | `miraretail@…` (FinCrime instance) | Invited attendee |

| Prepare | Needed for | How |
|---|---|---|
| Profile photos for the instances (synthetic illustrations labelled AI) | All parts | Graph `PUT /users/{id}/photo/$value` as a User Administrator, a day ahead (photos take time to propagate) |
| Two scheduled meetings with an agenda in the body | All parts | Outlook: *"WB-2026-117 bid review"* (agenda: 4.2 data residency, 6.1 ISO 27001, pricing – human only) and *"ALR-2026-1043 huddle"* (internal attendees only) |
| Transcription allowed by meeting policy | Part 2 | Teams admin center > Meetings > Meeting policies |
| **Microsoft Graph access** to transcripts, Work IQ consent, Copilot Credits spending policy | Part 2 | Doc 16 §3a, checklist T5 |
| Fallback | All parts | Screenshots of a dry run; the bid desk 1:1 chat answers the same questions |

## Part 1 · Live in the meeting chat (6 min, today)

| Min | Do | Say |
|---|---|---|
| 0:00 | Open *WB-2026-117 bid review*; show BankingBids in the attendee list with its photo | *"BankingBids isn't a plug-in. It's a hired colleague with its own account, so I invite it like anyone else."* |
| 1:00 | In the meeting chat: `@BankingBids what did we commit on data residency to banks last year?` | *"It answers from the banking team's own library, with the source of each sentence."* |
| 2:30 | `@BankingBids /whoami` | *"Every call it makes is as itself. Here's the identity and the parent blueprint."* |
| 3:30 | Ask the same as **PublicSectorBids** (if also invited): banking library | *"Same container, different hire: Azure refuses the banking index with a 403. The isolation holds in a meeting too."* |
| 4:30 | Switch to *ALR-2026-1043 huddle*: `@MiraRetail summarise the indicators for ALR-2026-1043` | *"Same pattern for financial crime. It recommends; the L2 analyst decides."* |
| 5:30 | Ask MiraRetail to "draft a message telling the customer we're looking into this" | *"It refuses: that would be tipping-off. The guardrail is in code, not only in the prompt."* |

## Part 2 · After the meeting (5 min, needs phase 1)

| Min | Do | Say |
|---|---|---|
| 6:00 | In the bid review, start **transcription**; speak two decisions ("Anna owns 6.1 by Friday", "pricing stays with Sales") and one open question; end the meeting | *"Teams tells everyone transcription is on. BankingBids doesn't listen to the audio; it reads the transcript afterwards, with its own access."* |
| 8:00 | Show the recap in the meeting chat: decisions, owners, open items, reusable answers with sources, **Needs SME** items | *"Every claim links back to a quote in the transcript or a past bid."* |
| 9:30 | Show the follow-up email and the Word *action log (AI draft)* in BankingBids' OneDrive | *"It works where the team works: chat, mail, Word."* |
| 10:30 | Show Application Insights: the Work IQ read as the agent user, the Search call as the agent identity | *"Two identities, both the instance's own. No shared service account, no tokens in logs."* |

## Part 3 · What's next (4 min, talk track only)

| Min | Topic | Say | Status |
|---|---|---|---|
| 11:00 | Live transcript | *"From mid-November, Teams can give agents the transcript while the meeting runs. BankingBids will answer 'BankingBids, check 6.1' in the chat within seconds."* | 🗺️ GA Nov 2026 |
| 12:30 | Voice | *"Today you can phone an autopilot from Teams: a Foundry voice agent behind a Teams Phone number, with our bid desk logic behind it. Speaking inside the meeting needs a separate voice participant that shows as external or as a bot, so we scope its identity per team like the rest."* | Phone line 🧪 preview · in-meeting voice: DIY spike |
| 13:30 | Avatar | *"The photo you saw is live. A talking avatar uses Azure Speech avatars, available in our region, and must always be clearly labelled as AI."* | Photo ✅, avatar spike |
| 14:30 | Close | *"Start where the risk is lowest: chat and post-meeting recaps. Add live and voice when they're GA and you need them."* | — |

## Tough questions

| Question | Answer |
|---|---|
| "Is it recording us?" | No. Humans start transcription, Teams shows the notice, and the agent reads only transcripts of meetings it was invited to. |
| "Can it hear a meeting it wasn't invited to?" | No. It uses its own delegated access; invitation is the boundary. |
| "Can it talk?" | Not as the hired account: Microsoft documents no way for an agent user to join call audio. A Teams Phone voice line can (doc 16 option D, preview); a voice participant in the meeting is a spike (options F and G). |
| "Will FinCrime speak about a case aloud?" | We don't recommend it: tipping-off and recording risk. Text in an internal chat, human decides. |
| "Is the face a real person?" | No. Synthetic, labelled AI. Custom look-alike avatars are a Limited Access feature requiring the person's written consent. |
