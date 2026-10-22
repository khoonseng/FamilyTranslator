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

- Phase: **Week 1 — Cantonese bake-off** (update this line as phases complete)
- Trip: **19–23 Dec 2026** (5 days). Trip configuration incl. the always-on instance goes live 15 Dec.
- Tech stack: **Python/FastAPI backend, Vue 3 frontend** — see "Stack" below
- Primary translation model: **not yet chosen** — decided by 15 Nov 2026 (see "Stack")
- ZDR: waiting on Google for (a) the Vertex AI abuse-monitoring exception and (b) written
  confirmation that Text-to-Speech doesn't retain text

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
   speech at pauses. **Family** (phase 2) is tapped for replies, then back to Guide.
2. Cloud Run receives audio → STT in the language set by the mode.
3. ONE translation LLM call per sentence returns JSON with the target languages only (`yue`, `en`
   for guide speech; `zh_hans` added for family speech). The source language is the transcript
   itself, never regenerated. The field TTS needs comes first.
4. TTS only where audio is needed: guide spoke → Cantonese MP3 clip; family spoke → Mandarin clip.
5. Text goes to every screen; audio clips go out over WebSocket as binary frames and are saved
   to Cloud Storage (30 days) for backfill and replay.

Room and hub:
- One fixed room. Listeners join by scanning its QR code and stay joined.
- One active hub at a time. Any phone that has entered the hub PIN can tap **Become hub** to take
  over (e.g. the spare phone's battery dies); the old hub drops to listener, and bubble history
  carries on. If the hub is offline for more than about 20 s, listener phones show "Hub offline".

Build order:
- **Phase 1 (trip-critical):** guide → family. Mandarin speech or hub typing in; Cantonese audio
  and text out. English text next, if time permits.
- **Phase 2:** family → guide. Family mode (Cantonese or English), Mandarin audio from the hub,
  half-duplex, typing on listener phones. Built only after phase 1 passes its field test; if it
  slips, the owner and wife interpret replies.

## Hard rules (do not break without explicit approval)

1. Provider API keys live server-side only (Secret Manager). Phones never call AI providers directly.
   Only a phone that has entered the hub PIN may send audio or text that triggers provider calls;
   listeners join with the QR room token and never need the PIN.
2. Cloud Run runs in `us-central1` with `max-instances=1` (room state lives in memory) and
   `--cpu 1`. Never go below 1 vCPU: Cloud Run then forces max concurrency to 1, which allows only
   one WebSocket. Keep concurrency high enough for every phone in the room (the default 80 is
   fine). `min-instances=1` only from 15 Dec to 23 Dec 2026; set it back to 0 on 24 Dec.
3. Nothing is hosted in mainland China. The app is reached over SG roaming; do not add
   China-specific CDNs, ICP-dependent services or VPN logic.
4. Cascade only: STT → one LLM call → TTS. Do not use OpenAI GPT-Realtime-Translate or
   conversational realtime models (no Cantonese output).
5. `yue` is written as colloquial spoken Cantonese (粵語口語, e.g. 佢哋喺度等緊我哋) in Traditional
   characters, never formal written Chinese. The same string is displayed and sent to TTS.
6. Every provider (STT, LLM, TTS) sits behind an adapter interface with per-sentence failover to
   a standby provider. Business logic never imports a provider SDK directly.
   - The LLM adapter is ONE OpenAI-compatible chat client, configured per provider with
     `base_url`, `model` and key. Gemini, Groq and OpenAI are config entries, not new code.
   - STT and TTS adapters are provider-specific (Google and OpenAI APIs differ).
   - Google speech APIs and Gemini on Vertex AI authenticate with the Cloud Run service account
     (no keys). Only the Groq and OpenAI keys live in Secret Manager.
   - Model IDs live in config, never hard-coded: Groq's lineup changes within weeks.
   - Reasoning is switched off on the translation LLM, or set to the lowest level the model allows
     (`gpt-oss-120b`: low), as per-provider config. STT and TTS have no reasoning setting. The
     bake-off checks that this doesn't hurt translation quality; if it does, use the lowest
     setting that wins.
7. All provider calls are stateless. Translation context = glossary + last 2–3 utterances, never
   the whole session.
8. Input language comes from the hub mode (Guide / Family). Never auto-detect Mandarin vs
   Cantonese to choose the pipeline.
   - Guide is a latch: one tap = continuous listening until Family is tapped or Guide is tapped off.
     A VAD pause ends a chunk, never the session.
   - Family is one mode for Cantonese and English: STT receives `yue-Hant-HK` and `en-US`. Both go
     through the same pipeline, so this is not routing.
   - Typed text (hub or listener) may be language-detected; this rule covers speech only.
   - In Guide mode, a three-layer junk filter drops speech that isn't the guide before translation.
     It is a filter, never a router: (1) the mic sits close to the guide (spare hub phone or
     clip-on); (2) STT receives `cmn-Hans-CN` and `yue-Hant-HK`, and a chunk is dropped when more
     than half of its characters are labelled Cantonese; (3) very short transcripts and filler (嗯, 啊, 對) are dropped. Chirp 3 has no
     usable confidence score, so confidence is never a filter.
   - Tint the whole hub screen per mode so the current mode is unmistakable.
   - Capture from the phone's default audio input (`getUserMedia`), so a wired/USB-C clip-on mic
     works if one is added later. Do not build Bluetooth mic support.
9. Silence is never sent: Silero VAD runs in the browser (`@ricky0123/vad-web`); chunks end at
   short pauses (about 0.6–0.8 s, tuned in testing), not fixed windows, and are capped at 15
   seconds so non-stop speech is still sent. The server splits long transcripts at punctuation
   and translates each sentence as it is ready. Three units, never mixed up:
   - **Chunk** (sent by the hub): ends at a short pause or the 15 s cap. Never shown to users.
   - **Sentence** (one audio clip): split from the transcript at punctuation.
   - **Bubble** (one voice note): a new bubble starts after a pause longer than 2 s, or when the
     current one reaches 45 s of audio or 6 sentences. Chunks never wait for the 2 s pause.
10. Replays never call TTS again: clips are cached on the phone (IndexedDB) and in Cloud Storage.
11. Listener playback rules (see architecture doc, "Listener experience"):
    - Live (default): new clips auto-play in order and are marked `played`.
    - Tapping a bubble → Replaying: plays that bubble only, then stops in Paused. Never continues
      into later bubbles. Replays never change the `played` flag.
    - Paused: new clips arrive silently, marked unplayed, until the user taps "Play N new" or
      turns auto-play back on. Tapping another bubble mid-replay stops the current one; clips never overlap.
12. Mobile web constraints: HTTPS only; tap-to-start screen on join (unlocks iOS audio); Screen
    Wake Lock while in a room; reconnect + backfill from the last utterance id.
13. Half-duplex capture: any phone with an open mic (always the hub) pauses capture while it
    plays audio and resumes when playback ends, so it never re-captures its own output. Open the
    mic with `echoCancellation: true` as a second layer only. (Traverba looped forever without this.)
14. Zero data retention (ZDR) at every provider. No provider may keep conversation data:
    - Google STT: sync (or streaming) requests only. Never call the async/batch endpoint and never
      opt into Speech-to-Text data logging.
    - Gemini: Vertex AI only, never the AI Studio / Gemini API free tier (it may train on prompts).
      In-memory caching disabled on the project; abuse-monitoring exception requested.
    - Groq: Zero Data Retention switched on in Data Controls.
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

Proposed defaults (confirm in plan mode before adding):
- Python: `uv` for dependencies, `pytest` + `pytest-asyncio`, `ruff`.
- Frontend: TypeScript, `vite-plugin-pwa`, Pinia for room and player state, `idb` for IndexedDB,
  `@ricky0123/vad-web` (Silero VAD), Vitest for unit tests. Styling library: ask.

AI providers (all must meet hard rule 14; the week-1 bake-off confirms or promotes a fallback):

| Stage | Primary | Fallback (in order) |
| --- | --- | --- |
| STT | Google Speech-to-Text V2 `chirp_3` (sync): `cmn-Hans-CN`, `yue-Hant-HK`, `en-US`; glossary as phrase biasing | OpenAI `gpt-4o-mini-transcribe` (bake-off also tries `gpt-4o-transcribe` on accented Mandarin) |
| Translation LLM | Chosen by 15 Nov (rule below): Gemini 3.6 Flash on Vertex AI, or Groq | The other one. Groq candidates: `qwen/qwen3.8-27b` (Preview), `openai/gpt-oss-120b` (Production) |
| Translation, bake-off candidate | Google Cloud Translation v3 (NMT, text only; `yue` supported) | Role decided after the bake-off: none, last-resort fallback, or main. Adopting it means rewording hard rules 4 and 6 (owner approval) |
| TTS | Google Chirp 3 HD voices, Cantonese and Mandarin | Google's older non-Chirp voices |

Primary translation model rule (both providers stay configured, each the other's fallback):
- Gemini on Vertex AI is primary if Google grants the abuse-monitoring exception AND Gemini wins
  the bake-off.
- Otherwise Groq is primary with the bake-off winner; if Qwen and gpt-oss are close, use
  `openai/gpt-oss-120b` (Production, not Preview).
- Deadline 15 Nov 2026 (end of week 5). Whatever stands then is the trip configuration.

Not used: Azure (one cloud only), self-hosted or on-device models (no wav2vec, no Hugging
Face weights), Groq TTS (no Chinese voices), the Gemini API / AI Studio free tier (fails ZDR),
Alibaba Model Studio incl. Qwen3-TTS (ZDR for enterprise customers only), Google Media
Translation API (shut down in 2024), the Google Translate app (no API).

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

- [ ] Week 1 — Bake-off: scripts only, no app. Translate 10–15 Mandarin narration sentences with
      2–3 LLMs × 2–3 Cantonese voices for a blind test; score Cantonese STT on the family's
      recordings; deploy a test service to `us-central1` and measure time-to-first-audio.
      Run each translation model with reasoning off and on its lowest setting.
      Google Cloud Translation is tested alongside the LLMs as a candidate.
      Score every model's `yue` output for colloquial markers (佢, 係, 嘅, 咗, 唔, 喺, 冇, 咩, 啲, 嘢) and
      confirm each voice is a true yue-HK voice, not a Mandarin voice reading Traditional text.
      Score Mandarin STT (Chirp 3, `gpt-4o-mini-transcribe`, `gpt-4o-transcribe`) on 15–20
      Chongqing-accented, fast narration clips, and measure how often the Cantonese-label junk
      filter drops real guide speech. Test on the family's iPhones whether listener audio keeps
      playing with the screen locked. Enable billing with a budget alert; send Google both ZDR
      requests (Vertex AI abuse-monitoring exception; written confirmation of Text-to-Speech retention).
- [ ] Weeks 2–3 — Single-device MVP, guide → family: hub records Mandarin (or takes typed
      Mandarin), shows Cantonese text and plays Cantonese audio on earphones; adapters in place.
- [ ] Weeks 4–5 — Rooms (QR join), WebSocket fan-out, listener PWA, player states, cache, backfill;
      English text if time permits. Lock the primary translation model by 15 Nov.
- [ ] Weeks 6–7 — Switch to the trip configuration first (see "Billing and plans"). Then field
      tests in Singapore with the family's own phones in noisy places. Compare transcripts from
      the spare hub phone on the "guide's" lanyard against a clip-on to decide whether to buy a
      mic. Phase 2 (family → guide) starts only once guide → family passes.
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
- 2026-10-22 — Smoke test passed on the new project. Gemini 3.6 Flash's lowest reasoning
  setting is `minimal` (no `none`). Qwen3.8-27B on Groq does no reasoning at either setting,
  so it runs once. Colloquial markers extended with common spoken words (哋, 嚟, 而家, 嗰, 畀,
  啱, 咁, 喇, 囉, 喎, 乜, 點解, 邊度, 晒); the original list missed 我哋而家嚟到.
