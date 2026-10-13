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
| `04a_glossary.py` | Uploads `glossary.yaml` to Cloud Translation (via a Cloud Storage file) | Setup |
| `04_translate_bench.py`, `05_translate_score.py` | LLM configurations and Cloud Translation; colloquial score, speed; picks blind-test finalists | `sentences.yaml`, reviewed references |
| `06_tts_bench.py`, `07_build_blind_test.py`, `08_blind_score.py` | Voices, the in-laws' blind test page, unblinding | Finalists (not written yet) |
| `probe/` | Tiny Cloud Run service: `/latency`, `/locktest` | Not written yet |

Every bench appends to a log in `out/` and skips calls it has already made, so after an error
or Groq's daily cap, just run it again. Try `--limit 2` first to check a step on a few items.

### Correcting transcripts (between steps 3 and 4)

`02_stt_bench.py` drafts `out/references.csv` from the best transcript of each chunk. Open it
in Excel or Numbers, listen to the chunk (`out/chunks/<set>/<chunk_id>.wav`), fix the
`reference` column, and put `y` in `reviewed`. Only reviewed rows are scored, and re-running
the bench never overwrites your corrections. Reviewed guide transcripts also supply real
sentences to the translation bench.

Run any script with `uv run python <script>`; `uv run python 00_smoke.py --only llm` runs one
group. Tests: `uv run pytest`. Lint: `uv run ruff check .`

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
