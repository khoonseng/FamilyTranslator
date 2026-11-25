# Chongqing Family Translator

A voice-first mobile web app (PWA) that interprets between a Mandarin-speaking tour guide and a
Cantonese/English-speaking family group, for a family trip to Chongqing. A shared "hub" phone
captures speech; a single Cloud Run service transcribes, translates and synthesises it; listener
phones play Cantonese audio with large-font text. All phones use Singapore roaming data in China.

## Read first

- `docs/architecture.md` is the source of truth for the design (exported from the design doc).
  Read the section relevant to the current task before planning.
- `docs/decisions.md` is the Decisions log: every owner decision with its date and reason.
  Later entries supersede earlier ones. Check it before proposing anything the owner may
  already have decided or declined.
- `docs/handoff-claude-to-codex.md` explains the move from Claude Code to Codex (25 Nov 2026).
- If anything here or in the architecture doc conflicts with a request, stop and ask.

## Current status

- Phase: **Weeks 6–7 — Trip configuration and field tests** (update this line as phases
  complete; each phase starts with a plan for approval). Week 1 (bake-off) closed 2026-10-25, results in
  `docs/bakeoff-results.md`; weeks 2–3 (single-device MVP) closed 2026-10-26; weeks 4–5 (rooms,
  listener phones, replay) closed 2026-10-27. Weeks 6–7: trip configuration and session 0 done;
  phase 2 (family → guide) built and passed its device test 2026-11-13, live at
  https://chongqing-translator-408139569144.us-central1.run.app (revision 00017, the language
  profiles refactor; passed staging and a live check 2026-11-23; rollback 00016-6pb). Next:
  prepare the family field test (`docs/field-tests.md`). Side track (2026-11-23): language
  profiles, a second service `cantonese-guide-translator`
  (https://cantonese-guide-translator-408139569144.us-central1.run.app, bucket
  `familytranslator-cg-clips`, revision 00002) with the pair swapped; passed the owner's device
  test 2026-11-23. Open: its glossary, junk-filter layer 2, a translation-quality check (see
  "Language profiles" in the architecture doc).
- Trip: **19–23 Dec 2026** (5 days). Trip configuration incl. the always-on instance goes live 15 Dec.
- Tech stack: **Python/FastAPI backend, Vue 3 frontend** — see "Stack" below
- Primary translation model: **Gemini on Vertex AI** (bake-off winner; decided 2026-10-24,
  whatever Google answers on abuse monitoring), then Qwen and gpt-oss on Groq, then Cloud
  Translation
- ZDR: Google's abuse-monitoring logging for Gemini and Google's standard Text-to-Speech terms
  are accepted (owner, 2026-10-24); the two requests to Google are optional

## Users and channels

| Person | Speaks | Hears (audio) | Reads (text) |
| --- | --- | --- | --- |
| Guide | Mandarin | Mandarin from the hub speaker | Simplified Chinese on the hub |
| In-laws | Cantonese | Cantonese (must-have) | Colloquial Cantonese, Traditional, large font |
| Wife's siblings | Cantonese, English | Cantonese (must-have) | Cantonese or English |
| Owner and wife | Mandarin, English, Cantonese | None | Optional; they operate the hub |

Only two audio channels exist: Cantonese (listeners) and Mandarin (hub speaker).

## Architecture in brief

1. Hub = the owner's iPhone, carried by the owner (no spare phone; decided 2026-11-03); the
   wife's iPhone is the fallback hub. The guide wears a clip-on mic (DJI Mic Mini 2 transmitter)
   connected to the hub by Bluetooth and chosen in the hub's Mic settings. **Guide** latches
   into continuous listening; client-side VAD splits speech at pauses. Family replies (phase 2) come from family phones with the hub PIN
   (push-to-talk or typing); **Family** on the hub stays as an option.
2. The hub streams audio; Cloud Run opens one Chirp 3 stream per speech segment in the language
   set by the mode, with `gpt-transcribe` filling any gaps (hard rule 9).
3. ONE translation LLM call per sentence returns JSON with the target languages only (`yue`, `en`
   for guide speech; `zh_hans` added for family speech). The source language is the transcript
   itself, never regenerated. The field TTS needs comes first.
4. TTS only where audio is needed: guide spoke → Cantonese MP3 clip; family spoke → Mandarin clip.
5. Text goes to every screen; audio clips go out over WebSocket as binary frames and are saved
   to Cloud Storage (30 days) for backfill and replay.

Room and hub:
- One fixed room for the whole trip; its bubbles start fresh each trip-local morning (earlier
  days stay in the bucket). Listeners join by tapping its link (`…/join#<room token>`, shared in
  the family WhatsApp group) and stay joined; no QR code for now (decided 2026-10-26). Host
  phones can share the link and make a new one, which disconnects phones on the old link.
- One active hub at a time. Any phone that has entered the hub PIN can tap **Become hub** to take
  over (e.g. the hub iPhone's battery dies); the old hub stops listening, and bubble history
  carries on. Only a deliberate Start or Become hub takes over: a hub's automatic reconnect never
  takes the role back from a phone that took over meanwhile. If the hub is offline for more than
  about 20 s, listener phones show "Hub offline".

Build order:
- **Phase 1 (trip-critical):** guide → family. Mandarin speech or hub typing in; Cantonese audio
  and text out. English text next, if time permits.
- **Phase 2:** family → guide. Family members talk (push-to-talk, Cantonese or English) or type
  on their own phones (hub PIN required); the hub plays the Mandarin once the guide is quiet.
  The guide always has priority (hard rules 8 and 13). Built after the owner's Bluetooth
  clip-on check (session 0) and passed its device test on 2026-11-13; the family field test
  covers both phases (owner decision 2026-11-03).

## Hard rules (do not break without explicit approval)

The rules describe the Chongqing language profile (the default, `chongqing-translator`). The
`cantonese-guide` profile (a second service, owner decision 2026-11-23) follows them with the
roles swapped: rule 5's colloquial Cantonese applies to the text spoken to the guide; rule 8's
Guide-mode STT is `yue-Hant-HK` + `cmn-Hans-CN`, family speech `cmn-Hans-CN` + `en-US`, and
junk-filter layer 2 is off until measured. Everything else applies unchanged.

1. Provider API keys live server-side only (Secret Manager). Phones never call AI providers directly.
   Only a phone that has entered the hub PIN may send audio or text that triggers provider calls:
   the hub, and in phase 2 family phones that talk or type replies. Phones that only listen join
   with the room token in their join link and never need the PIN.
   - Host controls (owner decision 2026-10-26): the owner's and wife's phones sign in through a
     separate host link (`/host`) with the PIN and API token, which shows the spend figure,
     Pause / Resume Guide and Become hub. The family's join link has no host sign-in, and the
     server refuses those actions from any phone that didn't sign in as host.
   - The hub also sends the API token (owner decision 2026-10-25: both 8 digits, entered once
     per phone). The API token also guards `/openapi.json` and every API endpoint; the `/docs`
     page is an empty shell that asks for it and sends it as an `X-API-Token` header, never in
     a URL. Open without either: `/health` and the page's own files.
2. Cloud Run runs in `us-central1` with `max-instances=1` (room state lives in memory) and
   `--cpu 1`. Never go below 1 vCPU: Cloud Run then forces max concurrency to 1, which allows only
   one WebSocket. Keep concurrency high enough for every phone in the room (the default 80 is
   fine). `min-instances=1` only from 15 Dec to 23 Dec 2026; set it back to 0 on 24 Dec.
3. Nothing is hosted in mainland China. The app is reached over SG roaming; do not add
   China-specific CDNs, ICP-dependent services or VPN logic.
4. Cascade only: STT → translation → TTS. Translation is one LLM call per sentence (Gemini, then
   Qwen on Groq, then gpt-oss on Groq; decided 2026-11-03). Only if all three LLMs fail on a
   sentence does Google Cloud Translation translate it (two calls, `yue` and `en`, no context, literal wording). Do not use OpenAI
   GPT-Realtime-Translate or conversational realtime models (no Cantonese output).
5. `yue` is written as colloquial spoken Cantonese (粵語口語, e.g. 佢哋喺度等緊我哋) in Traditional
   characters, never formal written Chinese. The same string is displayed and sent to TTS.
6. Every provider (STT, LLM, TTS) sits behind an adapter interface with per-sentence failover to
   a standby provider. Business logic never imports a provider SDK directly.
   - The LLM adapter is ONE OpenAI-compatible chat client, configured per provider with
     `base_url`, `model` and key. Gemini, Groq and OpenAI are config entries, not new code.
   - Google Cloud Translation has its own small adapter, used only as the last-resort
     translation fallback (rule 4); it authenticates with the service account.
   - STT and TTS adapters are provider-specific (Google and OpenAI APIs differ).
   - Google speech APIs and Gemini on Vertex AI authenticate with the Cloud Run service account
     (no keys). Secret Manager holds only the Groq and OpenAI keys, the hub PIN and the API
     token. The join link's room token lives in the private bucket (`settings/join.json`), so
     host phones can renew it.
   - Model IDs live in config, never hard-coded: Groq's lineup changes within weeks.
   - Reasoning is switched off on the translation LLM, or set to the lowest level the model allows
     (`gpt-oss-120b`: low), as per-provider config. STT and TTS have no reasoning setting. The
     bake-off checks that this doesn't hurt translation quality; if it does, use the lowest
     setting that wins.
   - Sampling settings (temperature, top-p) are per-model config. Gemini runs at temperature 0.2:
     in the bake-off it made ~7 errors in 29 outputs at 1.0 (stray English words, wrong words)
     and 1 at 0.2. Qwen and gpt-oss also run at 0.2; their higher recommended settings produced
     a 36x repetition loop and a wrong time.
   - Vertex AI can refuse requests with 429 (busy shared pool) for long stretches: on Vertex,
     fail over to the other provider at once, never wait and retry.
   - Gemini also fails over to Qwen when its `yue` isn't complete within about 2.5 s (tuned in
     testing), or when `yue` contains Latin letters (junk words such as "goods"). Run 6: 24 of
     93 Gemini calls took over 4 s, up to 14 s; Qwen's slowest was 0.9 s.
7. All provider calls are stateless. Translation context = glossary + last 2–3 utterances, never
   the whole session.
8. Input language comes from the hub mode (Guide / Family) or, in phase 2, the Talk button on a
   family phone, which is always family speech. Never auto-detect Mandarin vs Cantonese to choose
   the pipeline.
   - Guide is a latch: one tap = continuous listening until Family is tapped or Guide is tapped off.
     A VAD pause ends a chunk, never the session.
   - Family is one mode for Cantonese and English: STT receives `yue-Hant-HK` and `en-US`. Both go
     through the same pipeline, so this is not routing.
   - Talk on a family phone (phase 2) is push-to-talk, never an open mic, capped at about 30 s.
     The guide has priority: Talk starts only after the guide has been quiet for 2 s (the hub
     reports guide speech from its VAD), and nothing a family member does blocks the guide's
     capture. Typing works any time; replies and guide sentences show in order of arrival.
   - Typed text (hub or listener) may be language-detected; this rule covers speech only.
   - In Guide mode, a four-layer junk filter drops speech that isn't the guide before translation.
     It is a filter, never a router: (1) the mic sits close to the guide (the guide's
     Bluetooth clip-on); (2) STT receives `cmn-Hans-CN` and `yue-Hant-HK` (with Mandarin alone, Chirp 3
     rewrites Cantonese speech as fluent Mandarin), the transcript is split into sentences, and a
     sentence is dropped when Cantonese-only characters (哋, 唔, 喺, 嘅, 咗, 冇, 佢, 嚟, 啲, 嘢, 嗰,
     乜, 囉, 喎, 咩, 咁) exceed 15% of its characters (provisional, decided 2026-10-25: check it
     against real family chatter, at the latest in the weeks 6–7 field tests); (3) very short
     transcripts and filler (嗯, 啊, 對) are dropped; (4) echo detection (owner decision
     2026-10-25): a sentence that nearly matches one of our own translations from the last
     60 s (mismatch below 0.6, after converting to Simplified) is our Cantonese overheard from
     a listener's speaker, and is dropped, so it can never loop. Layer 2 caught only 1–3 of 31
     such clips (Chirp 3 writes them as 系, 慨, 渠), so it may be weaker on real chatter too.
     Neither Chirp 3's language labels (it labelled Cantonese speech as Mandarin) nor
     confidence scores (it has none usable) are ever a filter.
   - Tint the whole hub screen per mode so the current mode is unmistakable.
   - Capture with `getUserMedia` from the input chosen in the hub's Mic settings (default: the
     phone's own mic). The guide's clip-on connects by **Bluetooth** (owner decision
     2026-11-03): iOS Safari ignores plug-in Lightning/USB-C mics (WebKit bug 211192), and
     "Phone default" still means the iPhone's own mic, so the DJI is chosen by name. Because
     iOS silently falls back to the built-in mic when the Bluetooth link drops, the hub must
     make a lost clip-on obvious. No Bluetooth-specific code: the phone pairs it, the app only
     picks the input.
9. Streaming STT with a safety net (decided 2026-10-24). Silence is never sent: Silero VAD runs
   in the browser (`@ricky0123/vad-web`).
   - **Hub:** while Guide is latched, streams speech audio to the server as it is spoken. The VAD
     holds back long silences; each segment's audio runs until the VAD has heard the pause that
     ends it (about 0.6–0.8 s), then the hub sends `segment_end`.
   - **Server:** one Chirp 3 stream per hub segment (owner decision 2026-10-25), opened at the
     segment's start and closed at its end, which makes Chirp 3 return the final transcript at
     once (Guide mode: `cmn-Hans-CN` + `yue-Hant-HK`, glossary hints, "standard" endpointing).
     A long-lived stream lost a whole 13.8 s segment of real guide speech in 3 of 3 runs; per
     segment, it came through in full, about 0.5 s sooner. It splits Chirp 3's final
     transcripts into sentences at punctuation, filters them (rule 8) and translates each one
     as soon as it is ready; a later segment's sentences wait for the earlier segment's.
   - **Half-sentence hold** (owner decision 2026-10-25): a sentence ends at punctuation, not at
     a pause. A segment's trailing words without sentence-ending punctuation are held; if the
     guide carries on within 1.5 s, the next segment's words are joined to them, otherwise
     they are translated as they are. Chirp 3 left 4 of 6 mid-sentence cut-offs unpunctuated.
   - **Safety net:** the hub's VAD also cuts the audio into segments at pauses (about 0.6–0.8 s,
     capped at 15 s), which the server keeps. When a segment ends, if Chirp 3's final
     transcripts don't reach to within 1 s of its end, the uncovered audio is sent to
     `gpt-transcribe` (Chirp 3 cut 4.6 s off one of 16 real clips in the bake-off). If the
     stream fails, whole segments go to `gpt-transcribe` until it recovers.
   - Units, never mixed up:
     - **Segment** (cut by the hub's VAD): pause to pause, at most 15 s. Kept for the safety
       net; never shown to users.
     - **Sentence** (one audio clip): split from the transcript at punctuation.
     - **Bubble** (one voice note): a new bubble starts after a pause longer than 2 s, or when
       the current one reaches 45 s of audio or 6 sentences. Sentences never wait for the 2 s
       pause.
10. Replays never call TTS again: clips are cached on the phone (IndexedDB) and in Cloud Storage.
11. Listener playback rules (see architecture doc, "Listener experience"):
    - Live (default): new clips auto-play in order and are marked `played`.
    - Tapping a bubble → Replaying: plays that bubble only, then stops in Paused. Never continues
      into later bubbles. Replays never change the `played` flag.
    - Paused: new clips arrive silently, marked unplayed, until the user taps "Play N new" or
      turns auto-play back on. Tapping another bubble mid-replay stops the current one; clips never overlap.
    - Clips play at normal speed (1.0×), never sped up. When 3 or more clips are waiting in Live
      (a fast guide talking non-stop), a large **跳到最新 / Jump to latest** button appears. Tapping
      it stops the current clip and plays the newest one; the skipped clips stay unplayed and
      marked, so they can be replayed later.
12. Mobile web constraints: HTTPS only; tap-to-start screen on join (unlocks iOS audio); Screen
    Wake Lock while in a room; reconnect + backfill from the last utterance id.
    - Silent keep-alive on listener phones: while in a room, a second audio element loops
      phone-made digital silence, because iOS freezes a locked page (and its WebSocket) about
      10 s after its audio stops. Clips still play on the main player. Restart the keep-alive if
      iOS pauses it, else show "Tap to resume audio"; pause it while Talk records; never run it
      on the hub (hard rule 13). No radio mode (tested: about 6 s more delay).
13. Half-duplex capture: any phone with an open mic (always the hub) pauses capture while it
    plays audio and resumes when playback ends, so it never re-captures its own output. Open the
    mic with `echoCancellation: true` as a second layer only. (Traverba looped forever without this.)
    Because of this, the hub plays Mandarin replies (phase 2) only after the guide has been quiet
    for 2 s, in order of arrival, and a tap on the hub screen stops a reply and reopens the mic.
    A family phone pauses its own playback while Talk records.
    The weeks 2–3 MVP-only "Earphones in" switch ends with weeks 4–5: from then on the hub
    never plays Cantonese, so it never pauses capture in phase 1.
    The hub's "Phone voice processing" switch may turn echo cancellation (with noise
    suppression and auto gain) off, e.g. for a plug-in clip-on mic (owner decision 2026-11-03):
    pausing capture during playback stays the defence against loops.
14. Zero data retention (ZDR) at every provider. No provider may keep conversation data, except
    the two Google exceptions below:
    - Google STT: sync (or streaming) requests only. Never call the async/batch endpoint and never
      opt into Speech-to-Text data logging.
    - Gemini: Vertex AI only, never the AI Studio / Gemini API free tier (it may train on prompts).
      In-memory caching disabled on the project. Exception (owner-approved 2026-10-24): Google may
      keep prompts and replies for abuse monitoring unless it grants the exception; accepted
      for Gemini only, so Google stays the main translator either way.
    - Google Text-to-Speech. Exception (owner-approved 2026-10-24): Google's standard terms are
      accepted even without written confirmation that it keeps no text (it receives only the
      Cantonese translation).
    - Groq: Zero Data Retention switched on in Data Controls.
    - OpenAI transcription and Google Cloud Translation: no retention by default; keep it so.
    - Logs: request IDs, timings and errors only. Never log transcripts, translations or audio.
    - Exception, our own storage (owner-approved 2026-10-13): the Cloud Storage bucket keeps clips
      and transcripts for 30 days so the owner can download them. Lifecycle rule deletes objects
      after 30 days; soft delete set to 0; no public access, clips are served only through the app
      with the room token. Listener phones keep their IndexedDB cache (no end-of-day clear).

## Stack

Decided:
- Backend: Python 3.12 + FastAPI on uvicorn, async throughout. FastAPI's native WebSocket
  support carries the room channel. Pydantic models define every WebSocket JSON message.
- Frontend: Vue 3 + Vite, built as a PWA.
- One container: a multi-stage Docker build (Node builds the Vue app, then a Python image serves
  `dist/` as static files alongside the API and WebSocket endpoints).
- GCP Cloud Run, Cloud Storage, Secret Manager, Vertex AI; IndexedDB cache on the phone.
- Audio clips are MP3: one non-streaming Chirp 3 HD request per sentence. MP3 plays on every
  iPhone; Ogg Opus support in iOS Safari is unconfirmed. All family phones are iPhone 14 Pro or
  later on iOS 26.6.2 or later.
- Hub upload: raw 16 kHz PCM, no client-side encoder (no roaming data cap: Singtel GOMO, 60 GB).
- Region: `us-central1` for everything (Cloud Run, Cloud Storage, Vertex AI, TTS). Chirp 3 STT runs
  only in the `us` and `eu` multi-regions, so Singapore would add a Pacific crossing per chunk
  anyway; `us-central1` also keeps the Cloud Storage free allowance. No two-region test.

Libraries (confirmed 2026-10-25):
- Python: `uv` for dependencies, `pytest` + `pytest-asyncio`, `ruff`.
- Frontend: plain JavaScript (no TypeScript: the owner reads JavaScript), `vite-plugin-pwa`,
  Pinia for room and player state, `@ricky0123/vad-web` (Silero VAD), Vitest for unit tests,
  Tailwind CSS for styling. `idb` for IndexedDB joins in weeks 4–5, with replay.

AI providers (all must meet hard rule 14; the week-1 bake-off confirms or promotes a fallback):

| Stage | Primary | Fallback (in order) |
| --- | --- | --- |
| STT | Google Speech-to-Text V2 `chirp_3`, **streaming**: `cmn-Hans-CN` + `yue-Hant-HK` in Guide mode, `yue-Hant-HK` + `en-US` in Family mode; glossary as phrase biasing | OpenAI `gpt-transcribe` on the saved audio segments, as both the safety net (gaps Chirp 3 left) and the fallback (stream down) |
| Translation | Gemini 3.6 Flash on Vertex AI (bake-off winner), reasoning minimal, temperature 0.2 | Groq `qwen/qwen3.8-27b` (Preview: re-check the ID before the trip), then Groq `openai/gpt-oss-120b` (reasoning low), then Google Cloud Translation v3 as last resort |
| TTS | Google Chirp 3 HD, Cantonese voice `yue-HK-Chirp3-HD-Despina` (in-laws' pick) | Older Google voice `yue-HK-Standard-A` |

Translation order (decided 2026-10-24):
- Gemini on Vertex AI is primary: it won the bake-off, and Google's abuse-monitoring logging
  is accepted if the exception isn't granted (hard rule 14).
- Qwen3.8-27B on Groq is the fallback; it clearly beat gpt-oss-120b. Re-check the Groq model ID
  before the trip.
- `openai/gpt-oss-120b` on Groq is the third translator (decided 2026-11-03): Groq's free-plan
  limits apply per model, so it gives a second allowance while the Developer upgrade is
  unavailable, and it beat Cloud Translation in the in-laws' blind test.
- Google Cloud Translation is the last resort when all three fail (hard rule 4).

Not used: Azure (one cloud only), self-hosted or on-device models (no wav2vec, no Hugging
Face weights), Groq TTS (no Chinese voices), the Gemini API / AI Studio free tier (fails ZDR),
Alibaba Model Studio incl. Qwen3-TTS (ZDR for enterprise customers only), Google Media
Translation API (shut down in 2024), the Google Translate app (no API), OpenAI
`gpt-live-transcribe` (Realtime API only, which keeps data 30 days for abuse monitoring unless
OpenAI approves ZDR; revisit only as a Chirp 3 replacement, never as a fallback).

## Billing and plans

No subscriptions: everything is pay-as-you-go with free allowances, except Groq's plan switch.

- Day one: billing enabled on the Google Cloud project with a budget alert of about US$20/month
  (alerts warn, they don't cap). Gemini via Vertex AI pay-as-you-go. Groq on the Free plan with
  ZDR on (about 220 translations/day; spread large bake-off runs over two days).
- Weeks 6–7 (owner decisions 2026-11-03):
  - **GCP:** budget alert raised to about US$80/month (owner, in Billing → Budgets & alerts).
  - **Groq:** the Developer plan is the goal, but upgrades were "temporarily unavailable due
    to high demand" (27 Oct). Retry weekly; when it works, upgrade and confirm ZDR stays on.
    Meanwhile gpt-oss-120b adds a second free allowance (hard rule 4).
  - **OpenAI:** no top-up and no auto-reload before the trip (US$0.04 used of US$5 by 27 Oct;
    auto-reload's minimum is US$5). The owner checks usage at the end of each trip day and
    tops up by hand if needed; a purchase may take a few minutes to show.
- 15 Dec 2026: Cloud Run `min-instances=1` (no cold starts); back to 0 on 24 Dec.
- Expected spend: about US$5–10 for development; the 5-day trip about US$40–45 with Gemini
  primary, US$20–25 with Groq primary (scaled from the earlier 7-day estimate).
- App-side spending alert: the server totals each day's STT minutes, LLM tokens and TTS
  characters, and shows an estimated cost on phones that have entered the hub PIN, with a warning
  banner above US$12 a day. It never pauses or stops translation (the owner may not have the hub).
  The guide's hub screen never shows it.
- Keep free allowances intact: Artifact Registry cleanup policy keeps only the last 2 images
  (0.5 GB free); Secret Manager stays within 6 active secret versions.

## Repo layout (proposed)

```
backend/
  app/
    main.py          # FastAPI app, static files, routes
    schemas.py       # Pydantic models for WebSocket messages
    ws/              # room WebSocket endpoint and fan-out
    rooms/           # room state, QR tokens, backfill
    pipeline/        # orchestrator: STT -> translate -> TTS, per sentence
    providers/       # adapters: stt/, llm/, tts/, plus failover
    storage/         # Cloud Storage clip store
  tests/
frontend/
  src/
    views/           # JoinView, HubView, ListenerView
    components/      # Bubble, TalkButtons, PlayerControls
    audio/           # capture + VAD, playback queue, player state machine
    stores/          # room and player state
    lib/             # WebSocket client, IndexedDB cache
bakeoff/             # week-1 scripts only; never shipped
docs/architecture.md
docs/decisions.md    # the Decisions log
Dockerfile
```

## Build phases

- [x] Week 1 — Bake-off (closed 2026-10-25; results in `docs/bakeoff-results.md`; the family chatter
      check is postponed, see weeks 6–7): scripts only, no app. Translate 10–15 Mandarin narration
      sentences with 2–3 LLMs × 2–3 Cantonese voices for a blind test; score Cantonese STT on the
      family's recordings; deploy a test service to `us-central1` and measure time-to-first-audio.
      Run each translation model with reasoning off and on its lowest setting, and Qwen and gpt-oss
      at two temperatures. Google Cloud Translation is tested alongside the LLMs. Score every
      model's `yue` output for colloquial markers (佢, 係, 嘅, 咗, 唔, 喺, 冇, 咩, 啲, 嘢) and confirm each
      voice is a true yue-HK voice, not a Mandarin voice reading Traditional text. Score Mandarin
      STT (Chirp 3 sync and streaming, `gpt-4o-transcribe`, `gpt-transcribe`) on 15–20
      Chongqing-accented, fast narration clips; measure streaming's end-of-speech-to-text delay; and
      set the junk filter's Cantonese-character share from how often it drops real guide sentences
      vs family chatter. Test on the family's iPhones whether listener audio keeps playing with the
      screen locked. Enable billing with a budget alert. (Google's two ZDR requests became optional
      on 2026-10-24: both outcomes are accepted.)
- [x] Weeks 2–3 — Single-device MVP, guide → family (closed 2026-10-26; tested on the owner's
      iPhone): hub records Mandarin (or takes typed Mandarin), shows Cantonese text and plays
      Cantonese audio on earphones; adapters in place.
- [x] Weeks 4–5 — Rooms, WebSocket fan-out, listener PWA, player states, cache, backfill;
      English text (closed 2026-10-27; tested on a laptop, an iPhone and an iPad: join link,
      host controls, takeover, locked screen, catch-up, replay offline, Sound off).
- [ ] Weeks 6–7 — Trip configuration and field tests, reordered (owner decision 2026-11-03):
      (1) trip configuration (gpt-oss, hub never deaf; done); (2) session 0, the owner's check
      of the guide's Bluetooth clip-on (range about 10 m, dropouts recovered; done 2026-11-05);
      (3) phase 2 (family → guide; done 2026-11-13, revision 00016); (4) one family field test
      in noisy places covering both phases: time-to-first-audio and whether it feels fast
      enough, the junk filter's provisional 15% against family chatter, replies to the guide,
      and session 0's leftovers (WeChat app-switch, voice processing on vs off, an hour's
      battery, re-pairing the DJI on the wife's phone).
- [ ] Weeks 8–10 (30 Nov–18 Dec) — Buffer, fixes, sessions and History (named sessions inside
      the one room, a History screen to revisit them within 30 days; decided 2026-10-27), family
      briefing (incl.: the hub phone runs only the hub page; earphones or Sound off near the
      hub; asking the guide; Safari's microphone set to Allow on both hub phones), a nicer
      Mandarin voice. 15 Dec: `min-instances=1` on. Trip 19–23 Dec; `min-instances=0` on 24 Dec.

## Working agreement

- Start each phase with a plan: read this file and the relevant architecture section, propose a
  written plan, and wait for the owner's approval before changing any code.
- Work one step at a time: the owner pauses between sessions and approves each step before the
  next one starts. The owner runs the device tests on real iPhones.
- Ask before adding a dependency, a provider, or a cloud service, or changing a hard rule.
- Ask before deploying or making any `gcloud` change (secrets, services, traffic, instances).
  The live service must not break: new code runs on a staging copy first.
- Never commit secrets. Keep a `.env.example` with variable names only.
- Make small commits after each working step, with tests green at every commit.
- When a decision is made, update `docs/architecture.md` and `docs/decisions.md` in the same
  change, and update "Current status" above when a phase step completes.
- Explain in plain language: the owner is technical but prefers plain words to jargon.
- Don't re-propose an option the owner has declined (e.g. stronger echo detection, 27 Oct)
  unless the owner raises it again.
## Commands

Proposed; verify and correct these when scaffolding.

- Backend dev: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
- Frontend dev: `cd frontend && npm run dev` (Vite proxies `/api` and `/ws` to port 8000)
- Tests: `cd backend && uv run pytest` · `cd frontend && npm run test`
- Lint: `cd backend && uv run ruff check .`
- Build image: `docker build -t chongqing-translator .`
- Deploy: `gcloud run deploy chongqing-translator --source . --region us-central1 --cpu 1 --max-instances 1 --timeout 3600`
  (add `--min-instances 1` from 15 Dec to 23 Dec 2026 only)
- Deploy script: `./deploy.sh` deploys the live Chongqing service as before. A second language
  profile: `SERVICE=cantonese-guide-translator BUCKET=<project>-cg-clips PROFILE=cantonese-guide ./deploy.sh`
  (`--bucket` once first). Local run of a profile: `PROFILE=cantonese-guide uv run uvicorn ...`

Microphone access needs a secure context. `localhost` works on the laptop; testing on real
phones needs HTTPS, so deploy a dev revision to Cloud Run for phone tests.
