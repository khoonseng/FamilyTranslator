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
- Trip date: TBC (the plan assumes departure on 7 Dec 2026)
- Tech stack: **Python/FastAPI backend, Vue 3 frontend** — see "Stack" below

## Users and channels

| Person | Speaks | Hears (audio) | Reads (text) |
| --- | --- | --- | --- |
| Guide | Mandarin | Mandarin from the hub speaker | Simplified Chinese on the hub |
| In-laws | Cantonese | Cantonese (must-have) | Colloquial Cantonese, Traditional, large font |
| Wife's siblings | Cantonese, English | Cantonese (must-have) | Cantonese or English |
| Owner and wife | Mandarin, English, Cantonese | None | Optional; they operate the hub |

Only two audio channels exist: Cantonese (listeners) and Mandarin (hub speaker).

## Architecture in brief

1. Hub = the owner's own phone, no extra hardware. **Guide** latches into continuous listening;
   client-side VAD splits speech at pauses. **Family** is tapped for replies, then back to Guide.
2. Cloud Run receives audio → STT in the language set by the button.
3. ONE translation LLM call per sentence returns JSON `{ "yue": ..., "zh_hans": ..., "en": ... }`, streamed.
4. TTS only where audio is needed: guide spoke → Cantonese clip; family spoke → Mandarin clip.
5. Text goes to every screen; audio clips go out over WebSocket as binary frames and are saved
   to Cloud Storage for backfill and replay.

## Hard rules (do not break without explicit approval)

1. Provider API keys live server-side only (Secret Manager). Phones never call AI providers directly.
2. Cloud Run runs with `max-instances=1` (room state lives in memory) and `--cpu 1`. Never go
   below 1 vCPU: Cloud Run then forces max concurrency to 1, which allows only one WebSocket.
   Keep concurrency high enough for every phone in the room (the default 80 is fine).
3. Nothing is hosted in mainland China. The app is reached over SG roaming; do not add
   China-specific CDNs, ICP-dependent services or VPN logic.
4. Cascade only: STT → one LLM call → TTS. Do not use OpenAI GPT-Realtime-Translate or
   conversational realtime models (no Cantonese output).
5. `yue` is written as colloquial spoken Cantonese (粵語口語, e.g. 佢哋喺度等緊我哋) in Traditional
   characters, never formal written Chinese. The same string is displayed and sent to TTS.
6. Every provider (STT, LLM, TTS) sits behind an adapter interface with per-sentence failover to
   a standby provider. Business logic never imports a provider SDK directly.
7. All provider calls are stateless. Translation context = glossary + last 2–3 utterances, never
   the whole session.
8. Input language comes from the hub mode (Guide / Family). Never auto-detect Mandarin vs
   Cantonese to choose the pipeline.
   - Guide is a latch: one tap = continuous listening until Family is tapped or Guide is tapped off.
   - In Guide mode, drop segments the STT flags as not Mandarin or low confidence. This is a junk
     filter for family chatter, never a router.
   - Tint the whole hub screen per mode so the current mode is unmistakable.
   - Capture from the phone's default audio input (`getUserMedia`), so a wired/USB-C clip-on mic
     works if one is added later. Do not build Bluetooth mic support.
9. Silence is never sent: VAD runs on the phone; chunks are sentence-sized, not fixed windows.
10. Replays never call TTS again: clips are cached on the phone (IndexedDB) and in Cloud Storage.
11. Listener playback rules (see architecture doc, "Listener experience"):
    - Live (default): new clips auto-play in order and are marked `played`.
    - Tapping a bubble → Replaying: plays that bubble only, then stops in Paused. Never continues
      into later bubbles. Replays never change the `played` flag.
    - Paused: new clips arrive silently, marked unplayed, until the user taps "Play N new" or
      turns auto-play back on. Tapping another bubble mid-replay stops the current one; clips never overlap.
12. Mobile web constraints: HTTPS only; tap-to-start screen on join (unlocks iOS audio); Screen
    Wake Lock while in a room; reconnect + backfill from the last utterance id.

## Stack

Decided:
- Backend: Python 3.12 + FastAPI on uvicorn, async throughout. FastAPI's native WebSocket
  support carries the room channel. Pydantic models define every WebSocket JSON message.
- Frontend: Vue 3 + Vite, built as a PWA.
- One container: a multi-stage Docker build (Node builds the Vue app, then a Python image serves
  `dist/` as static files alongside the API and WebSocket endpoints).
- GCP Cloud Run, Cloud Storage, Secret Manager; Opus audio clips; IndexedDB cache on the phone.
- Region: `us-central1` or `asia-southeast1`, chosen by the week-1 latency test.

Proposed defaults (confirm in plan mode before adding):
- Python: `uv` for dependencies, `pytest` + `pytest-asyncio`, `ruff`.
- Frontend: TypeScript, `vite-plugin-pwa`, Pinia for room and player state, `idb` for IndexedDB,
  Vitest for unit tests. Styling library: ask.

Not decided — ask before choosing:
- STT, translation LLM and Cantonese/Mandarin TTS providers (chosen by the week-1 bake-off).
  Candidates are listed in `docs/architecture.md` under "Model and provider choices".

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
      recordings; deploy a test service to both regions and measure time-to-first-audio.
- [ ] Weeks 2–3 — Single-device MVP: hub records, shows text, plays audio; adapters in place.
- [ ] Weeks 4–5 — Rooms (QR join), WebSocket fan-out, listener PWA, player states, cache, backfill.
- [ ] Weeks 6–7 — Field tests in Singapore with the family's own phones in noisy places. Compare
      transcripts from the hub phone held at 1 m against a clip-on worn by the "guide" to decide
      whether to buy a mic.
- [ ] Week 8 — Buffer, fixes, family briefing.

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
- Deploy: `gcloud run deploy chongqing-translator --source . --region <REGION> --cpu 1 --max-instances 1 --timeout 3600`

Microphone access needs a secure context. `localhost` works on the laptop; testing on real
phones needs HTTPS, so deploy a dev revision to Cloud Run for phone tests.

## Decisions log

- 2026-10-07 — Host outside China; reachability relies on SG roaming / non-local-breakout eSIM.
- 2026-10-07 — Single cascade pipeline for all channels; Cantonese audio is a must-have.
- 2026-10-07 — One LLM call returns all three languages; `yue` is colloquial Cantonese.
- 2026-10-07 — Listener UI = voice-note bubbles; per-bubble and per-sentence replay; replay stops
  at the end of the bubble; after a replay, new clips wait for the user (Paused).
- 2026-10-07 — GCP Cloud Run + Cloud Storage; region decided by latency test.
- 2026-10-07 — Backend Python/FastAPI, frontend Vue 3; both ship in one container.
- 2026-10-07 — Cloud Run at 1 vCPU: below 1 vCPU, concurrency is forced to 1, which breaks WebSockets.
- 2026-10-07 — Hub is the owner's phone only; clip-on mic deferred to the weeks 6–7 field test.
- 2026-10-07 — Guide mode latches into continuous listening; Family is tapped for replies.
