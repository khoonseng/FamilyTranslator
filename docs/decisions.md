# Decisions log

Every owner decision, with its date and reason, in date order. Later entries supersede earlier
ones and say so. Moved here from the end of `CLAUDE.md` (now `AGENTS.md`) on 2026-11-25. When a
decision is made, add it here and update `docs/architecture.md` in the same change.

- 2026-10-07 — Host outside China; reachability relies on SG roaming / non-local-breakout eSIM.
- 2026-10-07 — Single cascade pipeline for all channels; Cantonese audio is a must-have.
- 2026-10-07 — One LLM call returns all three languages; `yue` is colloquial Cantonese.
- 2026-10-07 — Listener UI = voice-note bubbles; per-bubble and per-sentence replay; replay stops
  at the end of the bubble; after a replay, new clips wait for the user (Paused).
- 2026-10-07 — GCP Cloud Run + Cloud Storage; region decided by latency test.
  (Region fixed on 2026-10-13, see below.)
- 2026-10-07 — Backend Python/FastAPI, frontend Vue 3; both ship in one container.
- 2026-10-07 — Cloud Run at 1 vCPU: below 1 vCPU, concurrency is forced to 1, which breaks WebSockets.
- 2026-10-07 — Hub is the owner's phone only; clip-on mic deferred to the weeks 6–7 field test.
  (Hub superseded on 2026-10-13, see below.)
- 2026-10-07 — Guide mode latches into continuous listening; Family is tapped for replies.
- 2026-10-11 — Off-the-shelf tools reviewed (see "Alternatives considered" in the architecture
  doc). None gives private Cantonese audio on each person's own phone, so the app is built.
  Google Translate and a WeChat group with the guide are the trip fallbacks.
- 2026-10-11 — Traverba tested and rejected: formal Traditional Chinese instead of spoken
  Cantonese, listening stopped at the first sentence end, and a speaker feedback loop.
- 2026-10-11 — Hub is half-duplex (no capture during playback); see hard rule 13.
- 2026-10-11 — Google Cloud first: Chirp 3 STT, Gemini 3.6 Flash, Chirp 3 HD TTS; fallbacks are
  OpenAI STT, Groq Qwen3.6-27B / gpt-oss-120b, Google older voices then Qwen3-TTS. Azure dropped.
  (Superseded on 2026-10-12, see below.)
- 2026-10-11 — LLM adapter is one OpenAI-compatible client; STT/TTS adapters provider-specific.
- 2026-10-11 — Pause detection: Silero VAD in the browser, 15 s chunk cap, server splits at punctuation.
- 2026-10-12 — Strict zero data retention for every provider and for the app itself (hard rule 14).
  Gemini moves to Vertex AI; Qwen3-TTS on Alibaba dropped; TTS fallback is Google's older voices only.
- 2026-10-12 — Groq and Vertex AI both configured as each other's fallback; primary chosen by
  15 Nov using the rule in "Stack". Groq Qwen model ID corrected to `qwen/qwen3.8-27b`.
- 2026-10-12 — Free allowances for development, trip configuration from week 6 (see "Billing and plans").
- 2026-10-13 — Build guide → family first (phase 1); family → guide is phase 2; English output
  if time permits. The LLM returns only target languages, never the source.
- 2026-10-13 — Hub is a spare phone carried by the guide, with its own eSIM or SIM (not the
  owner's hotspot, to spare battery and heat); the owner's phone is the fallback. Supersedes
  "Hub is the owner's phone only" (2026-10-07): iOS stops the mic when the owner switches apps.
- 2026-10-13 — One Family mode accepts Cantonese and English (STT gets both language codes).
- 2026-10-13 — Junk filter: mic close to the guide, drop STT results labelled Cantonese, drop
  short fragments. Chirp 3 has no usable confidence score.
- 2026-10-13 — Speech units: chunk (short pause or 15 s), sentence (one clip), bubble (pause
  over 2 s, or 45 s / 6 sentences).
- 2026-10-13 — Typing on the hub (phase 1) and on listener phones (phase 2).
- 2026-10-13 — MP3 clips instead of Opus, for iPhone compatibility. Hub uploads raw PCM (no data cap).
- 2026-10-13 — Cloud Storage keeps data for 30 days (exception to ZDR for our own storage, soft
  delete 0, private); no end-of-day cache clear. Save/export and history come after the trip.
- 2026-10-13 — Trip dates 19–23 Dec 2026. Build schedule unchanged; the extra weeks become
  buffer and a slot for phase 2. `min-instances=1` from 15 Dec, back to 0 on 24 Dec.
- 2026-10-13 — Region fixed to `us-central1`; no two-region test (Chirp 3 STT is US/EU only).
- 2026-10-13 — One fixed room; one active hub, with PIN-gated "Become hub" takeover.
- 2026-10-13 — Hub PIN gates every call that costs money. Daily spending is a warning banner
  only (above US$12/day, PIN phones only), never a pause.
- 2026-10-13 — Translation LLM reasoning off or at its lowest setting, checked in the bake-off.
- 2026-10-14 — Google Cloud Translation (text only, zero data retention by default) added as a
  bake-off candidate for the translation step. Its role is decided after the bake-off; hard
  rules 4 and 6 are unchanged unless it is adopted. The Google Translate app's early cut-off
  after short pauses is the app's own listening logic and doesn't affect the API.
- 2026-10-14 — Colloquial-marker list unified: 佢, 係, 嘅, 咗, 唔, 喺, 冇, 咩, 啲, 嘢.
- 2026-10-22 — Junk-filter layer 2 drops a chunk when more than half of its characters are
  labelled Cantonese. Owner approved the bake-off glossary and narration sentences.
  (Junk-filter rule superseded on 2026-10-23, see below.)
- 2026-10-22 — Smoke test passed on the new project. Gemini 3.6 Flash's lowest reasoning
  setting is `minimal` (no `none`). Qwen3.8-27B on Groq does no reasoning at either setting,
  so it runs once. Colloquial markers extended with common spoken words (哋, 嚟, 而家, 嗰, 畀,
  啱, 咁, 喇, 囉, 喎, 乜, 點解, 邊度, 晒); the original list missed 我哋而家嚟到.
- 2026-10-23 — Junk-filter layer 2 is a per-sentence share of Cantonese-only characters, set by
  the bake-off. Supersedes the 2026-10-22 label rule: Chirp 3 labelled Cantonese speech as
  Mandarin in any language order, and with Mandarin alone it rewrote Cantonese as Mandarin.
- 2026-10-23 — Chirp 3 streaming is the target STT design, confirmed by the week-1 streaming
  test before hard rule 9 changes. First synthetic test: final transcript ~0.8–1.0 s after each
  sentence's audio, ~1.7–2.0 s after the speaker stops; "short" endpointing split mid-word.
- 2026-10-23 — STT fallback is one OpenAI model on the saved audio, `gpt-4o-transcribe` or
  `gpt-transcribe` (bake-off decides). `gpt-live-transcribe` is not used: the Realtime API keeps
  data 30 days unless OpenAI approves ZDR, and a streaming fallback adds little for its cost.
- 2026-10-23 — Sampling per model: Gemini 3 at temperature 1.0 (Google's guidance); Qwen and
  gpt-oss tested at 0.2 and at their makers' recommended values. (Gemini superseded below.)
- 2026-10-23 — All translation LLMs run at temperature 0.2, Gemini included (owner-approved).
  Translation bench run 2 (10 sentences × 3 repeats): Gemini ~7/29 errors at 1.0 vs 1/29 at
  0.2 and faster; run 1: gpt-oss at 1.0 looped, Qwen at 0.7 gave a wrong time. Blind-test
  finalists: Cloud Translation, Gemini 0.2, gpt-oss 0.2, Qwen 0.2.
- 2026-10-23 — Vertex AI refused ~40% of requests (429, shared pool) during run 2, with none
  in run 1; Groq refused 1 of 61, Cloud Translation none. Gemini failover must be immediate;
  this weighs on the 15 Nov choice of main translator.
- 2026-10-24 — STT is Chirp 3 streaming, with OpenAI `gpt-transcribe` as both safety net and
  fallback (owner decision; hard rule 9 rewritten). Bake-off on 16 real WeChat clips from local
  guides: Chirp 3 streaming 13.4% error (excluding one clip where it cut off the last 4.6 s),
  ~2.0 s after speech ends; `gpt-transcribe` 12.7%, ~1.0 s per segment, never dropped speech;
  `gpt-4o-transcribe` 32.3% (dropped content), so it is not used. Streaming stays the main
  path because, for long non-stop narration, it delivers each sentence without waiting for a
  pause. Junk filter dropped 0 of 17 real guide sentences; family chatter still to test.
- 2026-10-24 — In-laws' blind test: Gemini picked as best for 7 of 10 sentences (naturalness
  2.5/3), Qwen 2, gpt-oss 1, Cloud Translation 0. On 21 real guide sentences Gemini also handled
  the guides' false starts best. Owner decisions: Gemini is the bake-off winner and main
  translator (subject to Google's abuse-monitoring exception); Qwen3.8-27B is the Groq model
  (gpt-oss-120b only if Groq withdraws the Qwen preview); Cloud Translation is the last-resort
  fallback when both LLM providers fail (hard rules 4 and 6 reworded).
- 2026-10-24 — Voice: `yue-HK-Chirp3-HD-Despina`, with the older `yue-HK-Standard-A` as the
  fallback voice (round A: Despina 2 votes, Standard-A 2, Zephyr 1, Iapetus 0).
- 2026-10-24 — Clips play at normal speed (1.0×) by default (owner decision): Despina's
  Cantonese took 90% of the guides' speaking time on 21 real sentences. For long fast stretches,
  a "Jump to latest" button (owner's choice over an automatic 1.1×: simpler, and the voice
  never changes); see hard rule 11.
- 2026-10-24 — Stick with Google regardless of its data-retention answers (owner decision):
  Google may keep Gemini prompts for abuse monitoring if the exception isn't granted, and
  Text-to-Speech runs on Google's standard terms; both are recorded exceptions in hard rule 14.
  Gemini is therefore the primary translator now, not "if granted by 15 Nov"; the requests to
  Google are optional.
- 2026-10-24 — Translation prompt rules for live speech (false starts, word swaps such as
  第二天 → 第二日 without changing the day or time, no repeats) adopted after runs 4–5: Gemini's
  Mandarin-word slips fell from 15 to 0 on 21 real sentences. (Rules revised in run 6, below.)
- 2026-10-24 — Family replies (phase 2) come from the family's own phones (owner decision):
  push-to-talk (Cantonese or English) or typing, on phones that have entered the hub PIN (hard
  rule 1; about 3 phones in the private vehicle); phones without it listen only. The guide
  always has priority: Talk starts only after 2 s of guide silence, and the hub plays Mandarin
  replies only after 2 s of guide silence, with a tap to stop one (hard rules 8 and 13). Typing
  works any time; everything shows in order of arrival. The hub's Family button stays optional.
- 2026-10-24 — Locked-screen playback: listener phones run a silent keep-alive (a second audio
  element looping phone-made silence) while in a room (owner decision; hard rule 12). Week-1
  probe on an iPhone: plain clips over WebSocket stopped about 10 s after the audio ended once
  locked (Safari tab and Home Screen alike), Web Audio failed at once; radio mode kept playing
  but added about 6 s of buffering; the two-player keep-alive played every clip on schedule
  after about 50 s of silence, with no added delay, in Safari and from the Home Screen.
- 2026-10-24 — Translation run 6 (31 sentences × 3, Gemini and Qwen): new prompt rules (change
  only words Cantonese says differently; times of day as notes; no "small recognition errors";
  never turn an action into its opposite). The run-5 rules made Gemini turn 開燈 into 熄燈 in 7
  of 16 outputs; now 0 of 12, with Mandarin words and added times still 0 of 93. Gemini still
  writes an occasional junk word under any prompt (多 goods, 年夜食; 4 of 93), and was slow that
  day (24 of 93 calls over 4 s, 11 failed). Owner decision: Gemini stays primary, but fails over
  to Qwen past a ~2.5 s deadline for `yue` or when `yue` contains Latin letters (hard rule 6).
  Re-measure Gemini on another day.
- 2026-10-24 — Time-to-first-audio of about 4.2 s is accepted (owner decision). Week-1 test
  service in `us-central1`, iPhone on Singapore mobile data, 10 runs: median 4.16 s (3.84–6.54
  s): Chirp 3 final 1.8 s, Gemini 1.0 s, TTS 0.9 s, MP3 download 0.4 s, slightly over the 2–4 s
  target. Re-measured on the real app in the weeks 6–7 field tests with the family; speed-ups
  only if it feels too slow there.
- 2026-10-25 — Junk-filter share set provisionally at 15% (owner decision); the family chatter
  recording is postponed. Week 1 dropped 0 of 17 real guide sentences at every threshold from
  10% to 30%. Still to confirm with real Cantonese chatter (forwarded family voice messages, or
  at the latest the weeks 6–7 field tests): the threshold, and that Chirp 3 in Guide mode keeps
  chatter recognisably Cantonese (if not, mic placement is the only defence). Week 1 closed.
- 2026-10-25 — Weeks 2–3 plan approved (single-device MVP, guide → family). Libraries confirmed:
  uv, pytest + pytest-asyncio, ruff; frontend in plain JavaScript (no TypeScript), Pinia,
  vite-plugin-pwa, Silero VAD, Vitest, and Tailwind CSS for styling. MVP-only exception to hard
  rule 13: an "Earphones in" switch keeps capture on while the hub plays Cantonese. The hard
  rule 9 safety net is built last in weeks 2–3. Rooms, listeners, Cloud Storage and replay
  follow in weeks 4–5.
- 2026-10-25 — API token alongside the hub PIN (owner decision): the hub sends both (8 digits
  each, entered once per phone); the token also guards `/openapi.json` and every API endpoint,
  so `/docs` stays on in the real app (an empty page that asks for the token and sends it as a
  header). Four secrets in Secret Manager: Groq key, OpenAI key, hub PIN, API token. No limit
  on failed attempts for now (owner decision).
- 2026-10-25 — One Chirp 3 stream per hub segment, opened at its start and closed at its end
  (owner decision; hard rule 9 rewritten). In the weeks 2–3 pipeline tests, one long-lived
  stream lost a whole 13.8 s segment of real guide speech (7-0010) in 3 of 3 runs, reproduced
  directly against Chirp 3; per segment it came through in full, with final transcripts
  0.5–1.6 s after the speech ended (about 1.8 s before). The hub sends no extra 1 s of
  silence: its VAD's own pause detection ends each segment. The safety net stays (6-0008 is
  still cut short).
- 2026-10-25 — Half-sentence hold and echo detection (owner decisions; hard rules 8 and 9).
  Hold: words a pause cut off before sentence-ending punctuation wait up to 1.5 s for the
  guide to carry on and are joined to the next segment's (Chirp 3 left 4 of 6 such cut-offs
  unpunctuated; both live tests came back whole). Echo detection, junk-filter layer 4: a
  sentence nearly matching one of our own translations from the last 60 s is dropped, so a
  listener phone on speaker can't loop (29 of 31 Despina clips caught, no false alarms in 930
  comparisons; layer 2 caught only 1–3, since Chirp 3 writes the Cantonese as 系, 慨, 渠).
  Adds `opencc-python-reimplemented` to the backend (owner approved). The hub's own iPhone
  test confirmed nothing is lost while it keeps listening (earphones switch on).
- 2026-10-26 — Weeks 2–3 closed (owner): the single-device MVP works on the owner's iPhone,
  with Cantonese text about 3 s and audio about 4 s after each sentence, translations judged
  80–90% accurate, and nothing lost while clips play on earphones. Still open, not decided:
  the family chatter check (now more urgent: layer 2 is weak), a loudness gate with automatic
  gain control off (proposed for the weeks 6–7 field tests), and pausing the hub from another
  PIN phone (could join weeks 4–5). Next: weeks 4–5, in plan mode.
- 2026-10-26 — Weeks 4–5 plan approved (rooms, listener phones, replay; still phase 1 only).
  Owner decisions: listeners join with a link carrying a room token (a 5th secret; changing it
  revokes old links), shared by WhatsApp, link only (no QR for now); host controls (spend
  figure, Pause / Resume Guide, Become hub) only on phones signed in through `/host` with the
  PIN and API token, refused by the server for anyone else, with a confirmation before Become
  hub and Pause; remote pause of the hub's Guide listening from host phones; the spending
  banner built now. Also settled: catch-up and missing clips travel over the listener's
  WebSocket (no new web address, so hard rule 1's API-token rule holds); listeners use the
  link in a Safari tab; a per-device "Sound off (text only)" switch, mainly for tablets in the
  car; the hub stops playing Cantonese, ending the earphones exception (hard rule 13).
- 2026-10-26 — One room for the whole trip, with an app-managed join link (owner decision;
  supersedes the room token as a 5th secret). Bubbles start fresh each trip-local morning
  (Asia/Shanghai) and sentence numbers restart, while earlier days stay in the bucket; a room
  per day was weighed and rejected, since the in-laws would need a new link every morning. The
  room token lives in the private bucket outside the 30-day rule; host phones can show and
  share the link, or make a new one (old link stops working, phones on it are disconnected).
  Host listeners sign in on `/host` with the PIN and API token alone. Cloud Storage bucket
  `familytranslator-cq-clips` created (private, 30-day delete on `days/`, soft delete 0) and
  `google-cloud-storage` added (owner approved).
- 2026-10-26 — The join link is `…/join#<room token>` (owner decision; was `…/join/<room
  token>`). A phone never sends what follows the `#`, so the token stays out of Cloud Run's
  request logs and out of WhatsApp's link-preview fetch; tapping it is unchanged for the family.
  The listener page keeps each day's sentences and clips in IndexedDB with `idb` 8.0.4.
- 2026-10-26 — Hub takeover only on a deliberate Start or Become hub: the hub's hello says
  whether it is a takeover, and an automatic reconnect never displaces a phone that took over
  meanwhile (e.g. the spare phone back from a dead zone); it shows "Another phone is now the
  hub", with "Listen on this phone" or "Make this phone the hub again". Become hub opens the hub
  page on the host phone (no separate message). The hub plays no audio and the earphones switch
  is gone (hard rule 13).
- 2026-10-27 — Host phones show which speech-to-text (Chirp 3, gpt-transcribe, both, or typed),
  which translator (Gemini, Qwen, Cloud Translation) and which voice (Despina, Standard-A)
  produced each sentence, in amber when a fallback was used; family phones never show it (owner
  request). Both are saved in each sentence's record in the bucket, and the log now says why a
  voice was skipped. Found in Part A: Despina refuses a single sentence that is too long (85
  characters with only commas: "This request contains sentences that are too long"), so
  Standard-A spoke it.
- 2026-10-27 — A sentence too long for Despina is split for the voice only (owner decision):
  at the comma nearest its middle, again if need be (at most 8 pieces), Despina speaks the
  pieces at once and the server joins their MP3s into the sentence's one clip (Google's MP3s
  are plain frames, so they join cleanly). The words are exactly the displayed `yue` (hard rule
  5 holds); Standard-A only if a piece has no comma left to split at. Normal sentences are
  unchanged; the Part A sentence took 1.9 s to speak instead of under 1 s. Long sentences are
  likely: during non-stop narration the hub's 15 s segment cap, not a pause, ends the segment.
- 2026-10-27 — Weeks 4–5 closed (owner). Revision 00007 tested on a laptop, an iPhone and an
  iPad: join link, live audio, 5 minutes locked, flight-mode catch-up, offline replay, Sound
  off, earphones out (auto-play off), remote pause and resume (the iPhone hub resumed without a
  tap), Become hub mid-speech, and an old hub back from flight mode not taking the role back.
  Owner decisions: no fix for English words in Mandarin (both LLMs keep them, the Latin-letter
  check sends the sentence to Cloud Translation, which handles them acceptably); no stronger
  echo detection for now. Still open, not decided: one iPhone disconnect while locked that
  stayed on "Reconnecting…" (not reproduced; monitor); echo loops whenever a device on speaker
  is near the hub (rule: earphones or Sound off near the hub; revisit if the weeks 6–7 field
  tests show family phones on speaker are realistic); Groq refused Qwen with 429 five times in
  7 days at 1–5 sentences a minute (free-plan limits; each fell to Cloud Translation); Android
  phones untested; the family chatter check; a loudness gate with automatic gain control off.
  The `cq-probe` test service and its images were deleted (owner, verified). Next: weeks 6–7,
  in plan mode.
- 2026-10-27 — Sessions and History move from "after the trip" to weeks 8–10 (owner decision;
  supersedes that part of 2026-10-13): host phones start optionally named sessions inside the
  one room (no new link for the family), and listener phones get a History screen of days,
  sessions and bubbles within the 30 days. Designed when weeks 8–10 start. Saving or exporting
  a bubble still comes after the trip.
- 2026-11-03 — Mic settings on the hub, built ahead of the rest of weeks 6–7 (owner decision).
  No spare phone: the owner's iPhone 14 Pro will be the hub, and the guide should wear a clip-on
  (a DJI Mic Mini 2, bought); the weeks 6–7 plan is still under review. With the transmitter on
  the speaker's collar, the app heard nothing beyond about 1 m from the phone, while Voice
  Memos recorded clearly through two doors at 3 m: the iPhone receives the DJI fine, so Safari
  with our capture settings doesn't use it. The hub gains a level bar, the name of the mic in
  use, a mic list (remembered per phone; a missing one falls back to the phone's default) and a
  "Phone voice processing" switch. Hard rule 13 amended: echo cancellation may be off on the
  hub; pausing capture during playback remains the defence. Defaults stay as before until the
  owner's test shows which combination works.
- 2026-11-03 — The guide's clip-on connects by Bluetooth (owner decision; hard rule 8 changed
  from "do not build Bluetooth mic support"). Tests on the owner's iPhone: with the DJI's
  plug-in receiver, Safari always captured the built-in mic, even when the stream was labelled
  "Wireless Mic Rx" (WebKit bug 211192, reopened April 2026, iOS 26.3+); the hub's mic settings
  and the /mictest page with the audio-session workaround (WebKit bug 282939) all failed. With
  the DJI transmitter paired directly by Bluetooth and chosen by name in Mic settings, Safari
  captured it clearly from the next room, with voice processing on or off, and the hub
  transcribed it. "Phone default" still captured the iPhone's mic. The owner's iPhone 14 Pro is
  the hub, carried by the owner (no spare phone; supersedes 2026-10-13), the wife's iPhone 15
  the fallback hub (the DJI pairs with one phone at a time, so Become hub means re-pairing it
  there). Still to check in the weeks 6–7 field tests: Bluetooth range (bodies and crowds cut
  it, the guide's own body most of all), what happens when the link drops (iOS falls back to
  the built-in mic silently), and the transmitter's battery. In phase 2, iOS may route the
  hub's Mandarin replies to the Bluetooth device. Chrome on iPhone is no alternative: every
  iOS browser uses WebKit.
- 2026-11-03 — Weeks 6–7 plan approved (owner): record the decisions; gpt-oss as the third
  translator; the hub never goes deaf without saying so (clip-on lost, back from another app,
  shown on host phones too); automatic time-to-first-audio from listener phones; a field
  report tool; a field-test protocol starting with a Bluetooth clip-on check. Owner decisions:
  `openai/gpt-oss-120b` on Groq after Qwen and before Cloud Translation (hard rule 4; Groq's
  free limits are per model and the Developer upgrade is unavailable for now); OpenAI: no
  top-up before the trip, daily checks during it; GCP budget alert US$80; host controls first
  tried on a host tab on the hub iPhone, the wife's phone if the hub stops listening.
- 2026-11-03 — Weeks 6–7 reordered (owner decision; supersedes "phase 2 only after phase 1
  passes its field test"): after the trip configuration, the owner runs session 0 (the
  Bluetooth clip-on's range, dropouts and battery, alone, no family); then phase 2 is built,
  starting in plan mode; then one family field test covers both phases. Reasons: one family
  outing instead of two; phase 2 changes the hub (it plays Mandarin, and with the Bluetooth
  clip-on connected iOS may route that sound to it), so testing the hub before it exists would
  test a setup about to change; about two weeks ahead of schedule, December still leaves room
  for fixes. Also skipped: phone reports of time-to-first-audio (estimated from existing
  server logs instead); the field report tool is built just before the family test, or the
  sessions are analysed by hand.
- 2026-11-05 — Session 0 (owner, revision 00010): the guide's Bluetooth clip-on works to about
  10 m, including with the speaker's back to the phone; beyond 10 m nothing is heard. Dropouts
  are caught: the hub's "Clip-on mic lost" banner appeared and it switched back to the clip-on
  by itself once in range (twice, 26–35 s after the drop; the server logged both). The rule for
  the trip: the hub iPhone stays within about 10 m of the guide. Not yet run, moved to the
  family field test: the WeChat app-switch, voice processing on vs off, an hour's battery, and
  re-pairing on the wife's phone. Next: phase 2, in plan mode.
- 2026-11-05 — Phase 2 plan approved (owner): replies from the in-laws' and siblings' phones
  (hub PIN on the family page, no host controls), spoken (hold to talk, 30 s) or typed, in
  Cantonese or English; the Mandarin plays from the hub iPhone so the guide is hands-free; voice
  `cmn-CN-Chirp3-HD-Kore` for now (fallback `cmn-CN-Standard-A`), to be revisited. Spike on the
  owner's iPhone (`/mictest`): while the Bluetooth clip-on is open as the mic, no sound plays
  at all (iOS routes it to the clip-on), even with capture paused; with the mic fully stopped,
  a Mandarin sample plays from the loudspeaker at normal volume, clear at 1–2 m, with no audio
  session switch, and the clip-on reopens fine afterwards. So the hub plays each reply by
  fully stopping the clip-on, playing, then reopening it (half-duplex, hard rule 13).
- 2026-11-05 — Phase 2 replies, owner decisions: Talk is checked against the guide only when it
  starts (2 s of guide quiet); once started it runs to its end or the 30 s cap, even if the
  guide speaks again (both are captured, in order). **One phone talks at a time**: while one
  holds Talk, the others show "Someone is asking…" and wait; typing stays open to everyone.
  Replies look **WhatsApp-style**: the guide's bubbles on the left, family replies on the right
  in green with a label, **"You"** on the asker's own phone (each phone sends an anonymous random
  id; no names) and "Family" on the others. A recording across midnight is kept and saved as
  the new day's first entry.
- 2026-11-12 — Phase 2 step 5 device test, fixes so far (from revision 00014): replies were
  silent from the hub with Guide off, because Guide off only paused the mic and the open
  Bluetooth clip-on took the sound; a quick release-and-press of Talk left a hidden recording
  running on the family phone, so every later reply had each word twice. Owner decision: the
  hub's mic is open only while Guide is on (Guide off, a remote pause or a takeover closes it
  completely; Guide on reopens it; iOS didn't ask for permission again in testing).
- 2026-11-13 — Phase 2 passed its device test (owner; revision 00016, laptop and iPad as family
  phones, the iPhone hub with the DJI clip-on): typed and spoken replies in Cantonese and
  English, played from the hub's loudspeaker with Guide on (after 2 s of quiet) and off (at
  once); Talk waits for the guide and for another phone; a typed reply waits for the pause; a
  tap stops a reply; no loop; bubbles in order; normal volume after Talk. Also fixed: only one
  hub mic may ever be open (switching Guide on twice quickly opened two, and the hidden one
  kept the clip-on held, so replies were silent and family phones saw "Guide is speaking" with
  Guide off); the server ignores the hub's speech for "guide is speaking" while Guide is off.
  Noted, no action yet: since 12 Nov Gemini missed its 2.5 s deadline on 32 of 98 sentences
  (31 went to Qwen, 1 to gpt-oss after a Qwen 429), so the Groq upgrade matters more. Next:
  prepare the family field test.
- 2026-11-14 — Part C rehearsal, a finding, not a decision (owner alone, 11:43–11:54 SGT; the
  hub on the iPhone's own mic, the DJI not connected, no family phones; recorded here on
  2026-11-25 from Claude's notes). Run 1: 6 VAD segments in 4 min; 4 chatter bubbles got
  through as fluent Mandarin with 0% Cantonese-only characters, and none was dropped, so
  junk-filter layer 2 could not have caught them at any threshold. Run 2: 0 segments in 3 min.
  The hub's input audio isn't saved, so the runs can't be replayed. This undermines layer 2's
  premise (that Chirp 3 in Guide mode keeps chatter recognisably Cantonese), as the week-1
  echo test already hinted, and leaves the close clip-on (layer 1) as the main defence. The
  family field test (part C, with the DJI in use) settles it; no change to the filter yet.
- 2026-11-23 — Language profiles (owner decisions): the language pair is a deploy-time setting
  (`PROFILE`), and a second Cloud Run service, `cantonese-guide-translator`, runs the pair
  swapped: a Cantonese guide; a family that hears Mandarin, reads Simplified Chinese and replies
  in Mandarin or English. It has its own bucket and shares the service account and secrets (same
  hub PIN and API token). Messages, records and caches keep their field names as role slots
  (`yue` holds the family's Mandarin there). The live service must not break: a golden test
  pins Chongqing's prompts, languages, voices and junk filter; Chongqing serves the built page
  byte for byte; the new code runs first on the second service with the Chongqing profile as a
  staging copy, and the live service is redeployed only after a phone test (rollback: traffic
  back to revision 00016). Hard rules 5 and 8 apply with the roles swapped in that profile;
  its junk-filter layer 2 is off until measured.
- 2026-11-23 — Language profiles deployed (owner): the live service runs the refactored code
  as revision 00017 after a staging copy passed the phone test and a live check passed
  (rollback: 00016-6pb). `cantonese-guide-translator` (revision 00002, bucket
  `familytranslator-cg-clips`) passed the owner's device test. Still open for that profile:
  its glossary, junk-filter layer 2 and a translation-quality check.
- 2026-11-25 — The coding assistant moves from Claude Code to OpenAI Codex (owner decision).
  `CLAUDE.md` becomes `AGENTS.md` (Codex reads that file, and by default only its first
  32 KiB), and this Decisions log moves out of it into `docs/decisions.md`; the handoff is
  `docs/handoff-claude-to-codex.md`. The app itself is unchanged (it never used Anthropic).
  Notes that lived only in Claude's private memory are now in the repo: the 14 Nov part C
  rehearsal (above); the working agreement's step-by-step approval, asking before deploys and
  `gcloud` changes, plain language, and not re-proposing declined options (e.g. stronger echo
  detection); the suspected cause of the one stuck "Reconnecting…" on a locked iPhone (27 Oct):
  a WebSocket left connecting with no timeout (not yet checked); and no native iOS app, since
  there is no Mac (it would need a cloud build and the US$99 developer fee).
- 2026-11-25 — Ship daily History first (owner decision). Listeners and hosts can open a past
  Chongqing date and replay saved bubbles through the existing room connection, with cached
  results available offline. Entering History pauses local live playback and leaves new live
  clips queued for the listener. Named sessions follow as a separate step inside the same room.
