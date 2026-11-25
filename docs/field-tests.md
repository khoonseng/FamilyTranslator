# Field tests

How the app is tested outside, before the 19–23 Dec trip. Session 0 (the guide's Bluetooth
clip-on, the owner alone) ran on 5 Nov; its result is in the architecture doc ("Hub phone and
audio capture") and the Decisions log. This page is the plan for the **family field test**: one
outing that covers both phases (owner decision 2026-11-03).

## Goals

The family field test answers six questions. Each one feeds a decision that is still open.

| # | Question | Decides |
| --- | --- | --- |
| 1 | Does guide → family work in a noisy place: sentences complete, meaning right, Cantonese audio on every phone? | Whether phase 1 is trip-ready |
| 2 | How long from the end of a guide sentence to the Cantonese audio, and does it feel fast enough? (About 4.2 s in week 1, accepted.) | Whether any speed-up work is needed |
| 3 | Does family Cantonese chatter near the hub get through as "guide" bubbles, and are real guide sentences ever dropped? | The junk filter's provisional 15% (hard rule 8) |
| 4 | Can the family ask the guide in noise, and can the guide hear the hub's Mandarin at 1–2 m? | Whether phase 2 is trip-ready; the Mandarin voice |
| 5 | Session 0's leftovers: switching to WeChat and back, voice processing on vs off, an hour's battery, re-pairing the DJI on the wife's phone | The hub's default mic settings; the fallback hub drill |
| 6 | Anything that confuses the in-laws or siblings | The family briefing (weeks 8–10) |

What Singapore can't test: roaming from China (the route, the delay), the Great Firewall's
effect on a Singapore SIM, and a real Chongqing guide's accent and speed. The week-1 bake-off
covered the accent with real guide clips.

## People and devices

| Who | Device | Role |
| --- | --- | --- |
| Owner | iPhone 14 Pro: the hub page; a host tab (`/host`) for the provider labels | Carries the hub within about 10 m of the guide; takes notes |
| Stand-in guide (the wife, or a sibling who speaks Mandarin) | DJI Mic Mini 2 transmitter on the collar, 15–20 cm below the mouth, mic facing up | Reads the script below in Mandarin; judges whether replies are clear |
| Wife (if not the guide) | iPhone 15: host page | Fallback hub for part E4; takes notes |
| In-laws | Their iPhones, family join link, PIN entered (Ask the guide) | Listen with earphones; ask questions in Cantonese |
| Siblings | Their iPhones, join link, PIN entered | Listen; ask in Cantonese or English; one reads English text |

Rule for the day, as for the trip: listener phones near the hub use **earphones or Sound off**
(a phone on speaker near the hub's mic can loop).

## The day before

- [ ] Charge: both iPhones, the DJI transmitter, the family's phones; bring a power bank.
- [ ] The DJI is paired to the owner's iPhone by Bluetooth. No Bluetooth earbuds on the hub iPhone.
- [ ] On both hub iPhones, Safari: open the app, **aA › Website Settings › Microphone › Allow**.
- [ ] Every phone opens the join link from the family WhatsApp group in a **Safari tab**, and
      reloads twice to be on the latest version. In-laws and siblings tap **🙋 Ask the guide**
      and enter the hub PIN (the owner can do it for them).
- [ ] Tell the family that what is said near the hub with Guide on, and their replies, are kept
      as text and audio in the app's private storage for 30 days, as on the trip.
- [ ] Optional: retry the Groq Developer upgrade (Qwen has been carrying about a third of the
      sentences since 12 Nov, on the free plan's limits).
- [ ] Print or share this page; the owner keeps a notes sheet (see "Notes sheet").

## Script for the stand-in guide

Read at a normal guide's pace, pausing as a guide would. The first ten are the bake-off
narration sentences (`bakeoff/sentences.yaml`), so we know exactly what should appear.

1. 各位早上好，今天我们第一站先去解放碑，大概二十分钟就到了。
2. 洪崖洞晚上七点半以后开灯，那个时候人特别多，大家一定要跟紧我，不要走散了。
3. 等一下我们坐长江索道过江，排队可能要四十分钟左右，大家可以先去上个厕所。
4. 李子坝这个站很有名，轻轨是直接从楼中间穿过去的，我们在下面的观景台拍照。
5. 磁器口是一个千年古镇，里面有很多小吃，比如陈麻花、酸辣粉，但是周末人非常多。
6. 重庆火锅一般分微辣、中辣、特辣，老人家肠胃不好的话，建议点鸳鸯锅。
7. 中午我们在附近吃饭，吃完饭大概一点半在这个门口集合，车子就停在对面。
8. 重庆是山城，很多路都是上坡下坡，走路的时候慢一点，注意脚下的台阶。
9. 这个白象居以前是没有电梯的，住在上面的人每天都要爬好多层楼梯。
10. 明天去武隆，路上要开三个小时左右，早上七点在酒店大堂等，记得带好护照。

**Non-stop stretch (for part B3):** read sentences 1–10 again without pausing between them,
as a fast guide would, for about a minute.

## Plan (about 2 hours)

Note the **start time of each part** on the notes sheet: the server logs are matched to it
afterwards.

### A. Set up in a quiet spot (10 min)

1. Hub: Start, choose the DJI in **Mic settings**, tap **Guide**. The DJI's name and the level
   bar show. Host tab open on the owner's or wife's phone.
2. Every phone shows **Connected**. The guide says sentence 1: every phone shows the bubble and
   plays the Cantonese.
3. Each PIN phone types one short question. The hub plays the Mandarin after the guide's 2 s
   of quiet.
4. Note the **battery %** of the hub iPhone, the DJI transmitter and one listener phone: this
   starts part E3's hour.

### B. Guide → family in noise (25 min, e.g. a hawker centre)

1. The guide reads sentences 1–10, walking around within about 10 m of the owner. The family
   listens with earphones.
2. For each sentence the family notes: missing, wrong meaning, or fine; and whether the
   Cantonese sounds natural. Siblings also check the English text.
3. The **non-stop stretch**: does **跳到最新 · Jump to latest** appear on listener phones, and
   does it make sense to the in-laws?
4. **Speed:** for 3–4 sentences, one person counts or uses a stopwatch from the end of the
   guide's sentence to the start of the Cantonese. More important: ask the family whether it
   feels fast enough to follow a guide.
5. One listener locks the screen for a few sentences: audio keeps playing.

### C. Family chatter near the hub (15 min, same place)

The junk filter's check. Guide stays on.

1. **Chatter only:** the guide is silent; the family chats in Cantonese about anything, about
   1–2 m from the hub and the guide, for 5 minutes. Expect no bubbles. Every bubble that
   appears is chatter that got through: note its time.
2. **Chatter while the guide talks:** the guide reads sentences 1–5 while the family keeps
   chatting nearby. Expect the guide's five sentences, and nothing from the chatter.
3. Optional backup: someone records part C1 with Voice Memos on another phone, so the filter
   can be re-run on it later at other thresholds without another outing.

### D. Replies to the guide (20 min, same place)

1. Each in-law asks two spoken questions in Cantonese (hold **撳住講 · Hold to talk**), e.g.
   「我哋幾點食飯？」「洗手間喺邊度？」. Each sibling asks one in Cantonese and one in English, and
   types one.
2. **Can the guide hear?** The guide stands 1–2 m from the hub with the iPhone's volume at
   maximum, and says whether each Mandarin reply was clear and correct. Note any that weren't.
3. While the guide reads a sentence, someone tries Talk: it waits ("Guide is speaking…") and
   opens about 2 s after the guide stops. A typed reply waits for the pause before it plays.
4. Does the Mandarin voice (Kore) sound acceptable to the guide? Note any comments for the
   voice revisit in weeks 8–10.

### E. Session 0's leftovers (30 min, partly overlapping)

1. **WeChat app-switch:** with Guide on, the owner switches to WeChat for 30 s, then back to
   Safari. Note what the hub shows: listening again by itself, or **Tap to resume listening**.
   On the wife's host phone, note what it showed meanwhile (for example "Hub offline" after
   about 20 s). Speech during the switch is lost, as expected.
2. **Voice processing on vs off:** in the noisiest spot, the guide reads sentences 1–5 with
   **Phone voice processing** on, then again with it off (Mic settings). The family compares
   the bubbles: which version had fewer mistakes? Note the level bar in each case.
3. **Battery after an hour:** an hour after part A4, note the battery % of the hub iPhone, the
   DJI transmitter and the same listener phone.
4. **Fallback hub drill:** unpair the DJI from the owner's iPhone; pair it to the wife's iPhone;
   on her host page tap **Become hub**, start Guide, choose the DJI in Mic settings, and the
   guide says one sentence. Then hand the hub back the same way. Note how long it took and any
   step that was confusing: this becomes the briefing's drill.

### F. Wrap up (5 min)

Ask each family member: what was confusing, what they'd want different, and whether they'd
trust it with a real guide.

## Notes sheet

One line per event is enough: time, part, what happened, which phone. For example:

| Time | Part | What happened | Phone |
| --- | --- | --- | --- |
| 14:05 | B1 | Sentence 3 missing | All |
| 14:20 | C1 | Chatter bubble appeared | Hub |
| 14:32 | D2 | Reply not clear to the guide (noise) | Hub |
| 14:40 | E1 | "Tap to resume listening" after WeChat | Hub |

## Afterwards: analysis by hand

Codex pulls the server logs and the day's saved sentences for the times on the notes sheet;
no report tool is needed unless this turns up a lot to compare. Logs hold timings and labels
only, never text (hard rule 14); the text comes from the day's records in the private bucket.

| Question | From |
| --- | --- |
| 1. Sentences complete and right | The day's sentences in the bucket, compared with the script; the family's notes |
| 2. Time to first audio | `stt_final` (speech end to transcript) and `sentence` (`total_s`: transcript to clip) per sentence, plus about 0.4 s to download the clip; the stopwatch readings; the family's feel |
| 3. Junk filter | `sentence_dropped` counts by reason (`cantonese`, `short`, `filler`, `echo`) in parts C1 and C2; chatter that got through, from the bucket, with its Cantonese-character share worked out to see which threshold would have caught it; any script sentence missing in C2 |
| 4. Replies | `talk_start` / `reply_heard` / `sentence` (kind `reply`) per question; the guide's notes |
| 5. Leftovers | `hub_mic` events (interrupted, lost) around E1; part E2's bubbles, compared; the battery readings; the drill's notes |
| Also | Which translator handled each sentence (Gemini's deadline misses, Qwen 429s), safety-net use, any errors |

The decisions this feeds: keep or change the 15% share; the default for **Phone voice
processing**; whether speed-ups are needed; whether replies are loud enough from the hub, or
the owner reads the Mandarin aloud instead in loud places; the Mandarin voice; and the family
briefing.

## Results

To be filled in after the test, with the date and revision.
