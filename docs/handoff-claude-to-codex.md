# Handoff: Claude Code → Codex (25 Nov 2026)

The owner built this project with Claude Code from 7 Oct to 23 Nov 2026 and is moving it to
Codex. Nothing in the app depends on Claude: the backend calls Google (Chirp 3, Gemini on
Vertex AI, TTS, Cloud Translation), Groq and OpenAI, never Anthropic. This page covers what
Codex needs to carry on without losing decisions, including a few facts that lived only in
Claude's private memory (outside the repo) until now.

## Read in this order

1. `AGENTS.md` (was `CLAUDE.md`): users, the 14 hard rules, stack, billing, working agreement,
   commands, current status. **The hard rules override any request; if a request conflicts
   with them or with the architecture doc, stop and ask the owner.**
2. `docs/decisions.md` (was the "Decisions log" at the end of `CLAUDE.md`): every owner
   decision with date and reason, 7 Oct–23 Nov. Later entries supersede earlier ones; the
   entry says so.
3. `docs/architecture.md`: the design's source of truth. Read the section for the task
   before planning.
4. `docs/field-tests.md`: the next task (see below).
5. `docs/bakeoff-results.md`: week-1 measurements behind the model and voice choices.

## Where things stand (25 Nov 2026)

- **Live service** `chongqing-translator`, revision **00017** (language-profiles refactor;
  passed staging and a live check 23 Nov). Rollback: traffic back to **00016-6pb**.
  URL: https://chongqing-translator-408139569144.us-central1.run.app
- **Second service** `cantonese-guide-translator`, revision 00002, bucket
  `familytranslator-cg-clips`, the same code with `PROFILE=cantonese-guide` (the language pair
  swapped). Passed the owner's device test 23 Nov. Open: its glossary, junk-filter layer 2
  (off until measured), a translation-quality check.
- Phases: week 1 bake-off, weeks 2–3 MVP, weeks 4–5 rooms/listeners/replay, weeks 6–7 trip
  configuration, session 0 (Bluetooth clip-on) and phase 2 (family → guide replies) are all
  done and device-tested.
- `docs/field-tests.md` is a draft (committed 25 Nov) that the owner is still reviewing.
  Don't rewrite it unless asked.

## Next task

**Prepare the family field test** (`docs/field-tests.md`): one outing covering both phases.
It tests time-to-first-audio, the junk filter against family chatter, replies to the guide in
noise, and session 0's leftovers (WeChat app-switch, voice processing on/off, an hour's
battery, re-pairing the DJI on the wife's phone). Analysis is by hand from server logs (timings
and labels only) plus the day's records in the private bucket. That analysis was Claude's
job and is now Codex's.

Then weeks 8–10 (30 Nov–18 Dec): fixes, sessions and a History screen (design them when that
phase starts), family briefing, a nicer Mandarin voice.

**Fixed dates:** 15 Dec set `min-instances=1` on the live service · trip **19–23 Dec 2026** ·
24 Dec set `min-instances=0` again.

## Key decisions not to undo

Full text in the hard rules and `docs/decisions.md`. In short:

- **Cascade only:** Chirp 3 streaming STT → one translation LLM call per sentence → TTS. No
  realtime or speech-to-speech models.
- **Translation order:** Gemini 3.6 Flash on Vertex AI (temperature 0.2, reasoning minimal) →
  Groq `qwen/qwen3.8-27b` → Groq `openai/gpt-oss-120b` (reasoning low) → Google Cloud
  Translation as the last resort. Gemini fails over to Qwen **at once** on a 429, when `yue` isn't
  complete within about 2.5 s, or when `yue` contains Latin letters. Model IDs live in config.
- **One OpenAI-compatible LLM client** configured per provider; every provider sits behind an
  adapter with per-sentence failover; business logic never imports a provider SDK.
- **STT:** one Chirp 3 stream per hub VAD segment; `gpt-transcribe` covers gaps and stream
  failures; the half-sentence hold is 1.5 s. Never the async/batch STT endpoint.
- **`yue` is colloquial spoken Cantonese in Traditional characters**, the same string shown
  and spoken. Voice `yue-HK-Chirp3-HD-Despina`, fallback `yue-HK-Standard-A`; long sentences
  are split at commas for the voice only. Mandarin replies: `cmn-CN-Chirp3-HD-Kore` (to revisit).
- **Input language comes from the mode** (Guide / Family / a family phone's Talk button), never
  from auto-detecting the speech.
- **Four-layer junk filter in Guide mode** (a filter, not a router): close mic, a 15%
  Cantonese-character share (provisional), short/filler drop, echo detection (mismatch below 0.6
  against our last 60 s of output).
- **Half-duplex hub:** the hub's mic is open only while Guide is on; to play a Mandarin reply
  it fully stops the Bluetooth clip-on, plays from the loudspeaker after 2 s of guide quiet,
  then reopens it. Only one hub mic may ever be open.
- **Listener playback rules** (hard rule 11): Live, Replaying, Paused; 1.0× speed only; "Jump
  to latest" at 3 or more waiting clips. Silent keep-alive on listener phones only.
- **Security:** provider keys server-side only; hub PIN + API token (8 digits each); host
  controls only via `/host`; the join link is `/join#<room token>` (the token stays out of logs).
- **Infra:** Cloud Run `us-central1`, `--cpu 1`, `max-instances=1` (room state is in memory).
  Nothing hosted in China, no China CDNs or VPN logic.
- **Data retention:** zero retention at every provider except two accepted Google exceptions;
  our bucket keeps clips and transcripts 30 days. **Logs never contain transcripts,
  translations or audio.**
- **Language profiles:** the pair is a deploy-time `PROFILE`. A golden test pins Chongqing's
  prompts, languages, voices and junk filter; the live service must stay byte-for-byte
  unchanged unless the owner approves a change. New code goes to a staging copy first.

## Facts that were only in Claude's private memory

These weren't in the repo before this handoff. Items 1–3 are now recorded in
`docs/decisions.md` (entries 2026-11-14 and 2026-11-25) and item 1 also in
`docs/architecture.md`; item 4 is in the working agreement in `AGENTS.md`.

1. **14 Nov, part C rehearsal (owner alone, 11:43–11:54 SGT):** the hub used the iPhone's own mic,
   with no DJI and no family phones. Run 1: 6 VAD segments in 4 min; **4 chatter bubbles got
   through as fluent Mandarin with 0% Cantonese characters**, so junk-filter layer 2 can't catch
   them at any threshold, and 0 were dropped. Run 2: 0 segments in 3 min. The hub's input audio
   isn't saved, so it can't be replayed. Chirp 3 in Guide mode turned chatter into Mandarin,
   which undermines layer 2's premise and leaves the close clip-on mic (layer 1) as the main
   defence. The family field test should confirm this with the DJI in use.
2. **Stuck "Reconnecting…" on a locked iPhone** (seen once, not reproduced): the suspected
   cause is a WebSocket stuck in CONNECTING with no timeout.
3. **No Mac**, so a native iOS app isn't feasible (it would need a cloud build plus the
   US$99 developer fee).
4. **Don't re-propose stronger echo detection** unless the owner raises it (declined 27 Oct).
5. **Old notes now superseded**, in case they turn up in a memory import: "turn on OpenAI
   auto-recharge before the trip" was replaced on 3 Nov by "no top-up, no auto-reload; the owner
   checks daily". "gpt-oss only if Qwen is withdrawn" was replaced on 3 Nov: gpt-oss is the
   third translator.

## How the owner works

- **Plan first, every phase:** read `AGENTS.md` and the architecture section, write a plan,
  and **wait for approval before changing code**. (Claude Code had a "plan mode" for this;
  in Codex it is just the rule.)
- **One step at a time.** The owner pauses between sessions and approves each step. Small
  commits after each working step, tests green at every commit.
- **Ask first** before: adding a dependency, provider or cloud service; changing a hard rule;
  deploying; any `gcloud` change (secrets, services, traffic, min-instances). The owner runs
  the device tests on real iPhones.
- **Record decisions:** when a decision is made, update `docs/architecture.md` and
  `docs/decisions.md` in the same change, and update the "Current status" line in `AGENTS.md`
  when a phase step completes.
- **Plain language:** the owner is technical but prefers plain explanations over jargon. The
  frontend is plain JavaScript on purpose (no TypeScript).
- Never commit secrets; `backend/.env.example` holds variable names only.

## Commands

```bash
# Full check (backend tests, lint, format; frontend tests and build)
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . \
  && cd ../frontend && npx vitest run && npm run build

# Local run
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev            # proxies /api and /ws to :8000

# Deploy (ask the owner first)
./deploy.sh                                                   # live Chongqing service
SERVICE=cantonese-guide-translator BUCKET=<project>-cg-clips PROFILE=cantonese-guide ./deploy.sh
```

Phone tests need HTTPS, so they run against a Cloud Run revision, not localhost. The
`gcloud`, `uv` and `npm` commands need network access in Codex's sandbox.

## Earlier plans (outside the repo)

Claude kept its approved plans in `~/.claude/plans/`. The two for this project are done and
recorded in the docs: `curried-stargazing-fern.md` (phase 2) and `happy-marinating-teacup.md`
(language profiles). They're useful history only. The language-profiles plan left these out
of scope: renaming wire/storage fields, a host-panel switch, tuning the swapped junk filter,
fixing the stale `backend/tools/smoke_providers.py`, and Gemini deadline tuning for Mandarin
output.
