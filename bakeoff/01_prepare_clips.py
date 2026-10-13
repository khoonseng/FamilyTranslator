"""Step 2: cut recordings into hub-like chunks (16 kHz mono WAV, split at pauses, 15 s cap).

Put files in (any of mp4, m4a, mp3, wav, mov, webm, aac, flac, ogg):
  recordings/guide/           Chongqing guide narration (Mandarin)
  recordings/family/yue/      the in-laws' questions in Cantonese
  recordings/family/en/       the siblings' questions in English
  recordings/family/chatter/  ordinary family chatter in Cantonese (junk-filter test)

Writes out/chunks/<set>/*.wav and out/chunks/manifest.csv. Re-running rebuilds both.

Run: uv run python 01_prepare_clips.py [--max-seconds-per-source 120]
"""

import argparse
import shutil

from lib import audio
from lib.config import OUT, RECORDINGS
from lib.records import write_csv

SETS = {
    "guide": RECORDINGS / "guide",
    "yue": RECORDINGS / "family" / "yue",
    "en": RECORDINGS / "family" / "en",
    "chatter": RECORDINGS / "family" / "chatter",
}
EXTENSIONS = {".mp4", ".m4a", ".mp3", ".wav", ".mov", ".webm", ".aac", ".flac", ".ogg", ".opus"}
CHUNKS = OUT / "chunks"
MANIFEST_FIELDS = ["chunk_id", "set", "source", "start_s", "end_s", "duration_s", "path"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-pause", type=float, default=0.7, help="pause that ends a chunk (s)")
    parser.add_argument("--max-chunk", type=float, default=15.0, help="chunk cap (s)")
    parser.add_argument(
        "--max-seconds-per-source",
        type=float,
        default=120.0,
        help="keep at most this much speech from each file, to bound STT cost (0 = no limit)",
    )
    parser.add_argument("--skip-start", type=float, default=0.0, help="skip intro (s) per file")
    args = parser.parse_args()

    if CHUNKS.exists():
        shutil.rmtree(CHUNKS)
    rows = []
    for set_name, folder in SETS.items():
        files = sorted(p for p in folder.glob("*") if p.suffix.lower() in EXTENSIONS)
        if not files:
            print(f"{set_name}: no files in {folder}")
            continue
        (CHUNKS / set_name).mkdir(parents=True, exist_ok=True)
        set_seconds = 0.0
        for path in files:
            try:
                pcm = audio.decode(path)
            except Exception as exc:  # noqa: BLE001 - one unreadable file shouldn't stop the run
                print(f"  skipped {path.name}: {exc}")
                continue
            pcm = pcm[int(args.skip_start * audio.RATE) :]
            kept = 0.0
            for start, end in audio.split_at_pauses(
                pcm, min_pause_s=args.min_pause, max_chunk_s=args.max_chunk
            ):
                duration = (end - start) / audio.RATE
                if args.max_seconds_per_source and kept + duration > args.max_seconds_per_source:
                    break
                chunk_id = f"{set_name}-{path.stem}-{len(rows):04d}"
                out_path = CHUNKS / set_name / f"{chunk_id}.wav"
                audio.write_wav(out_path, pcm[start:end])
                kept += duration
                rows.append(
                    {
                        "chunk_id": chunk_id,
                        "set": set_name,
                        "source": path.name,
                        "start_s": round(args.skip_start + start / audio.RATE, 2),
                        "end_s": round(args.skip_start + end / audio.RATE, 2),
                        "duration_s": round(duration, 2),
                        "path": str(out_path.relative_to(OUT.parent)),
                    }
                )
            set_seconds += kept
            print(f"  {path.name}: {kept:.0f}s of speech kept")
        count = sum(r["set"] == set_name for r in rows)
        print(f"{set_name}: {count} chunks, {set_seconds / 60:.1f} min")

    write_csv(CHUNKS / "manifest.csv", rows, MANIFEST_FIELDS)
    total = sum(r["duration_s"] for r in rows) / 60
    print(f"\n{len(rows)} chunks, {total:.1f} min of speech -> {CHUNKS / 'manifest.csv'}")


if __name__ == "__main__":
    main()
