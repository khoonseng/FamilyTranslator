# Week-1 bake-off

Scripts that test the riskiest parts of the design before the app is built: Mandarin STT on a
fast Chongqing-accented guide, colloquial Cantonese from each translator, the Cantonese voices,
time-to-first-audio, and iPhone playback with the screen locked. Never shipped with the app.
The plan and its questions come from `CLAUDE.md` ("Build phases") and `docs/architecture.md`.

## Setup

1. Google Cloud project with billing, a budget alert, and these APIs enabled: Speech-to-Text,
   Text-to-Speech, Vertex AI, Cloud Translation, Cloud Run, Cloud Build. Disable Vertex AI
   in-memory caching on the project (zero data retention).
2. `gcloud auth application-default login` (Google services use these credentials; no keys).
3. `cp .env.example .env` and fill in `GCP_PROJECT`, `GROQ_API_KEY` (Groq Data Controls: Zero
   Data Retention on), `OPENAI_API_KEY`.
4. `uv sync`

## Steps

| Script | What it does | Needs |
| --- | --- | --- |
| `00_smoke.py` | Calls every provider once: model IDs, reasoning switches, Chirp 3 language labels, real `yue-HK` voices, Cloud Translation pairs | Setup only |
| `01_prepare_clips.py` | Guide videos and voice memos → 16 kHz mono WAV chunks split at pauses (15 s cap) | Recordings |
| `02_stt_bench.py`, `03_stt_score.py` | STT configurations on every chunk; error rate against corrected transcripts, junk-filter drop rates | Chunks, corrected references |
| `02b_stt_streaming.py` | Chirp 3 streaming at real-time pace: delay from end of speech to final transcript, accuracy (scored by `03`); `--continuous` shows how whole narrations get split | Chunks, guide recordings |
| `04a_glossary.py` | Uploads `glossary.yaml` to Cloud Translation (via a Cloud Storage file) | Setup |
| `04_translate_bench.py`, `05_translate_score.py` | LLM configurations and Cloud Translation; colloquial score, speed; picks blind-test finalists | `sentences.yaml`, reviewed references |
| `06_tts_bench.py --shortlist` | All 34 Cantonese voices read the same two sentences on one page; tick 3 and paste the line into `config.yaml` | Setup |
| `06_tts_bench.py`, `07_build_blind_test.py`, `08_blind_score.py` | Blind-test clips, one self-contained page for the in-laws (voice, translation, speed), then unblinding | Shortlist, translation finalists |
| `probe/deploy.sh` | Tiny Cloud Run service: `/latency` (time-to-first-audio), `/locktest` (audio with the screen locked); see below | `PROBE_TOKEN` in `.env`, an iPhone |

Every bench appends to a log in `out/` and skips calls it has already made, so after an error
or Groq's daily cap, just run it again. Try `--limit 2` first to check a step on a few items.

Groq's Free plan allows about 1,000 requests and 200,000 tokens a day. The translation bench
has four Groq configurations (two models × two temperatures): with 3 repeats that is about 210
calls, close to the token cap, so expect it to finish on the second day, or use `--repeats 2`.

### Correcting transcripts (between steps 3 and 4)

`02_stt_bench.py` drafts `out/references.csv` from the best transcript of each chunk. Open it
in Excel or Numbers, listen to the chunk (`out/chunks/<set>/<chunk_id>.wav`), fix the
`reference` column, and put `y` in `reviewed`. Only reviewed rows are scored, and re-running
the bench never overwrites your corrections. Reviewed guide transcripts also supply real
sentences to the translation bench.

Run any script with `uv run python <script>`; `uv run python 00_smoke.py --only llm` runs one
group. Tests: `uv run pytest`. Lint: `uv run ruff check .`

### The Cloud Run test service (step 6)

`probe/deploy.sh` deploys `cq-probe` to `us-central1` with its own service account (Speech,
Vertex AI and Text-to-Speech only). It uses Google providers only, so no API keys go up; only
the files the probe needs are uploaded (never `recordings/`, `out/` or `.env`). The pages ask
for `PROBE_TOKEN` once and remember it; every `/api` and `/ws` call needs it. `/docs` lists the
endpoints ("Authorize" takes the token). Run it locally first with
`uv run uvicorn probe.app:app --port 8080` and open `http://localhost:8080/latency`.

- `/latency`: tap "Run 10 tests" on an iPhone with Wi-Fi off. Each run measures the phone's
  round trip, upload speed and MP3 download, while Cloud Run streams a stored Mandarin sentence
  to Chirp 3 at speaking pace, translates it with Gemini and synthesises it with Despina.
- `/locktest`: a numbered Cantonese clip every 15 s, as separate clips over a WebSocket (audio
  element or Web Audio) or as one continuous stream ("radio"). Lock the phone for about 2
  minutes and note the last number heard. Do each mode in a Safari tab and from the Home Screen.

Results are logged as timings only (no text or audio):
`gcloud logging read 'resource.labels.service_name="cq-probe" AND jsonPayload.event:*' --freshness 1d`.
Delete the service after week 1 with `probe/deploy.sh --delete`.

## Data

- Inputs go in `recordings/guide/` (Chongqing guide clips) and `recordings/family/` (voice
  memos). Outputs go in `out/`. Both folders are gitignored: family voices, transcripts and
  downloaded videos never get committed.
- Only metrics go into `docs/bakeoff-results.md`.

## Configuration

- `config.yaml`: every model ID, endpoint, reasoning setting and voice. Edit here, never in code.
- `glossary.yaml`: Chongqing places and dishes (Mandarin / Cantonese / English). A draft:
  review the Cantonese and English renderings and add places on the itinerary.
- `prompts/`: the translation instructions for each direction.
