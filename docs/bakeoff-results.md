# Week-1 bake-off results

**Status: final (25 Oct 2026).** Week 1 is closed. One check is postponed: the junk filter's
provisional 15% share is still to be tested against real family chatter (section 2).

The bake-off ran from 12 to 24 Oct 2026 with scripts in `bakeoff/`, before any app code. It
tested the riskiest parts of the design: Mandarin speech-to-text on fast, accented guides,
colloquial Cantonese from each translator, the Cantonese voice, time-to-first-audio and iPhone
playback with the screen locked. This page holds metrics only. Recordings, transcripts and
translations stay in `bakeoff/out/` on the laptop and are never committed. The decisions
themselves live in `docs/architecture.md` and the Decisions log in `CLAUDE.md`.

## Summary

| Week-1 question | Result | Decision |
| --- | --- | --- |
| Which speech-to-text? | Chirp 3 streaming 13.4% error, about 2.0 s after speech ends; `gpt-transcribe` 12.7%, about 1.0 s | Chirp 3 streaming, `gpt-transcribe` as safety net and fallback (24 Oct) |
| Which translator, at which settings? | Gemini picked best for 7 of 10 sentences by the in-laws | Gemini 3.6 Flash, reasoning minimal, temperature 0.2; Qwen on Groq as fallback; Cloud Translation last resort (23–24 Oct) |
| Which voice? | Despina 2 votes, Standard-A 2, Zephyr 1, Iapetus 0 | Despina, Standard-A as fallback (24 Oct) |
| Is playback fast enough at normal speed? | Cantonese audio took 90% of the guides' speaking time | 1.0× with a "Jump to latest" button (24 Oct) |
| Time-to-first-audio | About 4.2 s median (3.8–6.5 s) against a 2–4 s target | Accepted; re-measured in the weeks 6–7 field tests (24 Oct) |
| Does audio play with the screen locked? | Only with audio playing continuously; a silent keep-alive works | Silent keep-alive on listener phones (24 Oct) |
| Junk-filter threshold | 0 of 17 real guide sentences dropped at any threshold; no chatter tested | 15%, provisional; chatter check postponed (25 Oct) |
| Translation prompt for live speech | Run-6 rules: no meaning flips (0 of 12), no Mandarin words or added times (0 of 93) | New prompt; Gemini fails over to Qwen past a ~2.5 s deadline or on junk words (24 Oct) |

## 1. Speech-to-text: guide Mandarin

**Data:** 16 chunks (about 2 minutes) cut at pauses from 10 WeChat recordings of local
Chongqing guides. The owner corrected the reference transcripts. The error rate is the
character error rate, with digits and Chinese numerals counted as equal (7点 = 七点).

| Run | Error rate | Median latency | p90 latency | Speech dropped |
| --- | --- | --- | --- | --- |
| Chirp 3 sync, Mandarin + glossary | 12.7% | 3.23 s | 5.26 s | – |
| Chirp 3 sync, Mandarin | 13.6% | 3.31 s | 5.65 s | – |
| Chirp 3 sync, Mandarin + Cantonese (Guide mode) | 15.6% | 3.42 s | 5.50 s | – |
| **Chirp 3 streaming, "standard" endpointing** | **18.4%** (13.4% without the clip it cut short) | **2.00 s** | **2.33 s** | 1 of 16 |
| Chirp 3 streaming, "short" endpointing | 21.1% | 1.81 s | 2.40 s | 2 of 16 |
| OpenAI `gpt-transcribe` | 12.7% | 1.02 s | 1.22 s | – |
| OpenAI `gpt-4o-transcribe` | 32.3% | 1.33 s | 1.85 s | – |

Latency for sync runs is the request time; the app would add about 0.7 s of pause detection
and the upload. For streaming it is the time from the end of speech to the final transcript,
which is all the app waits.

- **Streaming dropped speech:** Chirp 3 cut the last 4.6 s off one chunk, in 8 of 8 repeats.
  Levelling the audio to -20 dBFS didn't stop it and made transcripts worse, so it is off.
  Hence the `gpt-transcribe` safety net for audio Chirp 3 leaves uncovered (hard rule 9).
- **"Short" endpointing** split words in the synthetic test and dropped more speech here.
- **`gpt-4o-transcribe`** skipped content and is not used.
- **Chirp 3's language labels are unusable:** in the smoke test it labelled Cantonese speech
  as Mandarin in every language order. With Mandarin alone, it rewrote Cantonese speech as
  fluent Mandarin, so Guide mode sends both languages.

## 2. Junk filter (Guide mode, layer 2)

A sentence is dropped when Cantonese-only characters (哋, 唔, 喺, 嘅, 咗, 冇, 佢, 嚟, 啲, 嘢, 嗰, 乜,
囉, 喎, 咩, 咁) exceed a share of its characters.

| Transcripts from | Guide sentences wrongly dropped at 10% / 15% / 20% / 30% | Chatter dropped |
| --- | --- | --- |
| Chirp 3 sync, Guide mode | 0 of 17 at every threshold | Not tested |
| Chirp 3 streaming | 0 of 17 at every threshold | Not tested |
| `gpt-transcribe` | 0 of 22 at every threshold | Not tested |

**Decision (25 Oct):** 15%, provisionally; the chatter recording is postponed. A 10-character
guide sentence with one mis-heard 唔 (10%) still passes, while typical chatter (佢哋喺度等緊,
about 50%) is dropped.

**Still to check**, with forwarded family voice messages or at the latest in the weeks 6–7
field tests (put them in `bakeoff/recordings/family/chatter/`, then run `02_stt_bench.py` and
`02b_stt_streaming.py` on the chatter set):

- the threshold itself;
- the filter's premise, that Chirp 3 in Guide mode keeps chatter recognisably Cantonese. If it
  rewrites chatter as Mandarin, no threshold helps, and the mic's closeness to the guide is the
  only defence.

## 3. Translation

**Data:** 10 drafted narration sentences (owner-approved) and 21 real sentences from the
reviewed guide transcripts. Every configuration ran 2–3 repeats per sentence.

**Settings (runs 1–2, drafted sentences):**

- Temperature 0.2 won for every model. Gemini at 1.0 made about 7 errors in 29 outputs
  (stray English such as "四十 processing 分鐘", wrong words); at 0.2 it made 1.
- At their makers' recommended settings, gpt-oss (1.0) produced a 36-times repetition loop
  and Qwen (0.7) gave a wrong time.
- Gemini's lowest reasoning setting is `minimal` (it has no `none`); Qwen3.8-27B on Groq did no
  reasoning at any setting. The lowest setting won.

**Finalists (run 3, 21 real guide sentences):**

| Translator | Glitches | Colloquial share | First token | Total, median | Total, p90 |
| --- | --- | --- | --- | --- | --- |
| Gemini 3.6 Flash, minimal, 0.2 | 0 of 42 | 99% | 1.16 s | 1.49 s | 1.95 s |
| Qwen3.8-27B (Groq), 0.2 | 0 of 41 | 100% | 0.44 s | 0.44 s | 0.78 s |
| gpt-oss-120b (Groq), low, 0.2 | 0 of 42 | 100% | 0.93 s | 0.93 s | 1.41 s |
| Cloud Translation v3 | 0 of 42 | 99% | – | 0.18 s | 0.37 s |

Colloquial share = colloquial markers (佢, 係, 嘅 ...) / (colloquial + formal markers) in the
Cantonese. These scores don't catch wrong meaning; that is what the blind test and the
manual reviews were for. Reading the outputs, Gemini handled the guides' false starts best.

**Prompt rules for live speech (runs 4–5, 21 real sentences):** word swaps (第二天 → 第二日,
今天 → 今日 ...), no accidental repeats, and handling of false starts. Gemini's Mandarin-word
slips fell from 15 to 0; Qwen still doubled a word twice (返返).

**Meaning flips with the run-5 prompt (found 24 Oct):** on a drafted sentence run 5 never saw
(洪崖洞晚上七点半以后开灯), Gemini turned 開燈 ("lights on") into 熄燈 ("lights off") in 7 of 16
outputs, once followed by a spoken self-correction (熄燈……唔係，開燈), and garbled 晚上 (夜嘅,
夜舖) in 4 of 9. Five prompt variants were screened on that sentence; the one adopted says to
change only words Cantonese says differently, gives times of day as notes rather than arrows,
drops the invitation to fix "small recognition errors", and adds "never turn an action into its
opposite".

**Run 6 (new prompt, 10 drafted + 21 real sentences × 3 repeats):**

| | Gemini 3.6 Flash | Qwen3.8-27B |
| --- | --- | --- |
| 熄燈 flips on the Hongyadong sentence | 0 of 3 (0 of 12 with screening) | 0 of 3 |
| Mandarin words left in | 0 of 93 | 0 of 93 |
| Times the guide never said | 0 of 93 | 0 of 93 |
| Junk words | 4 of 93 (多 goods; 好多年夜食 ×3 on one sentence), none on real sentences | 0 of 93 |
| Doubled words (返返) | 0 | 6 of 93, on 2 sentences |
| Meaning errors on real sentences (read by hand) | 1 minor in 63 (重麻辣 adds "hot") | Not reviewed in detail |
| Calls that failed | 11 of 93 (7 refusals, 4 timeouts at 20 s) | 5 of 93 timeouts |
| Total time: median / slowest | 2.05 s / 14.1 s; 24 of 93 over 4 s | 0.50 s / 0.89 s |

- **Gemini's junk words are not caused by the prompt:** the same day, the original prompt
  (used in the blind test) produced junk on the snacks sentence in 3 of 5 tries, after 0 of 3
  on 23 Oct. Reasoning "low" made it worse (8 of 10) and slower.
- **Decision (24 Oct):** Gemini stays primary, but a sentence goes to Qwen when Gemini's `yue`
  isn't complete within about 2.5 s, or contains Latin letters. Gemini is to be re-measured on
  another day.

**Vertex AI availability:** 429 refusals on about 40% of requests in run 2, none in runs 3–5,
1 of 10 in the latency test, and 7 of 93 in run 6 plus 4 timeouts. Failover to Groq must be
immediate (hard rule 6).

## 4. Blind test with the in-laws

| Round | Result |
| --- | --- |
| A, voice (5 sentences, same text in each voice) | Despina 2, Standard-A 2, Zephyr 1, Iapetus 0 |
| B, translation (10 sentences, picked best and rated 1–3) | Gemini best 7 of 10, naturalness 2.5; Qwen 2 of 10, 2.0; gpt-oss 1 of 10, 1.7; Cloud Translation 0 of 10, 2.0 |
| C, speech at 1.2× | 2 easy, 1 a little hard, 0 couldn't follow |

Despina and Standard-A tied in round A. Despina was chosen as the Chirp 3 HD voice, with
Standard-A as the fallback.

## 5. Playback speed

On the 21 real guide sentences, Despina's Cantonese at 1.0× took 106 s against the guides'
119 s (90%), because Gemini drops false starts and filler; single sentences ran up to 1.6× the
guide's time. Listeners therefore keep up on average. A "Jump to latest" button covers long,
fast stretches.

## 6. Time-to-first-audio

**Setup:** a test service on Cloud Run in `us-central1` and an iPhone on Singapore mobile data
(Wi-Fi off), 10 runs on 24 Oct. Cloud Run streamed a stored Mandarin sentence (about 7 s,
synthetic voice) to Chirp 3 at speaking pace, translated it with Gemini and synthesised it
with Despina; the phone timed its own network.

| Step | Median | Range |
| --- | --- | --- |
| Chirp 3 final transcript after the end of speech | 1.79 s | 1.72–1.92 s |
| Gemini, until the Cantonese text is complete | 1.03 s | 0.82–3.47 s |
| Text-to-speech (Despina) | 0.91 s | 0.83–1.23 s |
| MP3 download to the phone | 0.37 s | 0.35–0.41 s |
| **Guide stops talking → audio starts (estimate)** | **4.16 s** | **3.84–6.54 s** |

- 9 of 10 runs completed; 1 failed on a Vertex 429 (the test had no failover).
- Round trip to `us-central1`: 0.26 s. Upload: about 195 KB/s, about 6 times what the hub
  needs to stream raw 16 kHz audio (32 KB/s).
- Not covered: China roaming (expected to add a few tenths of a second), a real guide's voice,
  and the phone's own time to start playback (about 0.1 s).

**Decision (24 Oct):** about 4.2 s is accepted. It is measured again on the real app in the
weeks 6–7 field tests with the family; speed-ups only if it feels too slow there.

## 7. Locked-screen playback

**Setup:** numbered Cantonese clips pushed to an iPhone, which was then locked for 2–3 minutes,
in a Safari tab and as a Home Screen app.

| Mode | Clips 15 s apart | Clips 60 s apart (about 50 s of silence) |
| --- | --- | --- |
| Separate clips, audio element | Kept playing | **Stopped:** iOS froze the page about 10 s after the audio ended, and the WebSocket died |
| Separate clips, Web Audio | **Stopped** at once | Not run |
| Radio: one continuous MP3 stream | Kept playing | Kept playing, but about 6 s more delay from Safari's buffering |
| Separate clips + silent keep-alive, one player | – | Kept playing |
| **Separate clips + silent keep-alive, two players** | – | **Kept playing,** in a Safari tab and as a Home Screen app |

- The keep-alive loops digital silence made on the phone: nothing to hear and no network
  traffic. Clips played the moment they arrived.
- Radio streams kept running on the server for 30 minutes after the phone stopped listening.
- After unlocking, the plain-clip page reconnected within 2 s.
- **To check in the weeks 6–7 field tests:** battery drain over a full day, and locks of an
  hour or more.

## Not covered in week 1

- **Family Cantonese and English questions** (speech-to-text and translation for phase 2):
  deferred to phase 2.
- **Cloud Translation with an uploaded glossary** (`04a_glossary.py`): not run, since Cloud
  Translation is only the last resort.
- **Continuous streaming of long narration** (`02b_stt_streaming.py --continuous`): optional,
  not run.
- **eSIM routing from China:** the latency page shows the phone's public IP, so the spare hub
  phone's line can be checked once it arrives.
