# Chongqing Family Translator

A voice-first mobile web app (PWA) that interprets between a Mandarin-speaking tour guide and a
Cantonese/English-speaking family group, for a family trip to Chongqing. A shared "hub" phone
captures speech; a single Cloud Run service transcribes, translates and synthesises it; listener
phones play Cantonese audio with large-font text. All phones use Singapore roaming data in China.

## Read first

- `docs/architecture.md` is the source of truth for the design (exported from the design doc).
  Read the section relevant to the current task before planning.
- If anything here or in the architecture doc conflicts with a request, stop and ask.

## Current status

- Phase: **Weeks 4–5 — Rooms, listener phones and replay** (update this line as phases
  complete; starts in plan mode). Week 1 (bake-off) closed 2026-10-25, results in
  `docs/bakeoff-results.md`; weeks 2–3 (single-device MVP) closed 2026-10-26, deployed at
  https://chongqing-translator-408139569144.us-central1.run.app.
- Trip: **19–23 Dec 2026** (5 days). Trip configuration incl. the always-on instance goes live 15 Dec.
- Tech stack: **Python/FastAPI backend, Vue 3 frontend** — see "Stack" below
- Primary translation model: **Gemini on Vertex AI** (bake-off winner; decided 2026-10-24,
  whatever Google answers on abuse monitoring), then Qwen on Groq, then Cloud Translation
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

1. Hub = a spare phone the guide carries on a lanyard, with its own eSIM or SIM; the owner's
   phone is the fallback hub. **Guide** latches into continuous listening; client-side VAD splits
   speech at pauses. Family replies (phase 2) come from family phones with the hub PIN
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
  days stay in the bucket). Listeners join by tapping its link (`…/join/<room token>`, shared in
  the family WhatsApp group) and stay joined; no QR code for now (decided 2026-10-26). Host
  phones can share the link and make a new one, which disconnects phones on the old link.
- One active hub at a time. Any phone that has entered the hub PIN can tap **Become hub** to take
  over (e.g. the spare phone's battery dies); the old hub drops to listener, and bubble history
  carries on. If the hub is offline for more than about 20 s, listener phones show "Hub offline".

Build order:
- **Phase 1 (trip-critical):** guide → family. Mandarin speech or hub typing in; Cantonese audio
  and text out. English text next, if time permits.
- **Phase 2:** family → guide. Family members talk (push-to-talk, Cantonese or English) or type
  on their own phones (hub PIN required); the hub plays the Mandarin once the guide is quiet.
  The guide always has priority (hard rules 8 and 13). Built only after phase 1 passes its
  field test; if it slips, the owner and wife interpret replies.

## Hard rules (do not break without explicit approval)

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
   Qwen on Groq). Only if both LLM providers fail on a sentence does Google Cloud Translation
   translate it (two calls, `yue` and `en`, no context, literal wording). Do not use OpenAI
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
     It is a filter, never a router: (1) the mic sits close to the guide (spare hub phone or
     clip-on); (2) STT receives `cmn-Hans-CN` and `yue-Hant-HK` (with Mandarin alone, Chirp 3
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
   - Capture from the phone's default audio input (`getUserMedia`), so a wired/USB-C clip-on mic
     works if one is added later. Do not build Bluetooth mic support.
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
| Translation | Gemini 3.6 Flash on Vertex AI (bake-off winner), reasoning minimal, temperature 0.2 | Groq `qwen/qwen3.8-27b` (Preview: re-check the ID before the trip), then Google Cloud Translation v3 as last resort |
| TTS | Google Chirp 3 HD, Cantonese voice `yue-HK-Chirp3-HD-Despina` (in-laws' pick) | Older Google voice `yue-HK-Standard-A` |

Translation order (decided 2026-10-24):
- Gemini on Vertex AI is primary: it won the bake-off, and Google's abuse-monitoring logging
  is accepted if the exception isn't granted (hard rule 14).
- Qwen3.8-27B on Groq is the fallback; it clearly beat gpt-oss-120b. If Groq withdraws the
  Qwen preview, `openai/gpt-oss-120b` takes its place. Re-check the Groq model ID before the trip.
- Google Cloud Translation is the last resort when both fail (hard rule 4).

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
- Start of week 6: Groq Developer plan, OpenAI prepaid credit topped up, budget alert raised to
  about US$80, so field tests run on the exact trip configuration.
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
- [ ] Weeks 4–5 — Rooms (QR join), WebSocket fan-out, listener PWA, player states, cache, backfill;
      English text if time permits. (Primary translation model already decided: Gemini.)
- [ ] Weeks 6–7 — Switch to the trip configuration first (see "Billing and plans"). Then field
      tests in Singapore with the family's own phones in noisy places. Compare transcripts from
      the spare hub phone on the "guide's" lanyard against a clip-on to decide whether to buy a
      mic. Measure time-to-first-audio on the real app (about 4.2 s in week 1, accepted) and
      ask the family whether it feels fast enough. Check the junk filter's provisional 15%
      against family chatter near the hub, if not done earlier. Phase 2 (family → guide) starts
      only once guide → family passes.
- [ ] Weeks 8–10 (30 Nov–18 Dec) — Buffer, fixes, phase 2 if guide → family has passed, family
      briefing. 15 Dec: `min-instances=1` on. Trip 19–23 Dec; `min-instances=0` on 24 Dec.

## Working agreement

- Start each phase in plan mode: read this file and the relevant architecture section, propose a
  plan, and wait for approval before writing code.
- Ask before adding a dependency, a provider, or a cloud service, or changing a hard rule.
- Never commit secrets. Keep a `.env.example` with variable names only.
- Make small commits after each working step.
- When a decision is made, update `docs/architecture.md` and the "Decisions log" below in the same change.

## Commands

Proposed; verify and correct these when scaffolding.

- Backend dev: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
- Frontend dev: `cd frontend && npm run dev` (Vite proxies `/api` and `/ws` to port 8000)
- Tests: `cd backend && uv run pytest` · `cd frontend && npm run test`
- Lint: `cd backend && uv run ruff check .`
- Build image: `docker build -t chongqing-translator .`
- Deploy: `gcloud run deploy chongqing-translator --source . --region us-central1 --cpu 1 --max-instances 1 --timeout 3600`
  (add `--min-instances 1` from 15 Dec to 23 Dec 2026 only)

Microphone access needs a secure context. `localhost` works on the laptop; testing on real
phones needs HTTPS, so deploy a dev revision to Cloud Run for phone tests.

## Decisions log

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
