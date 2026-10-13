"""Step 4 prep: upload glossary.yaml to Cloud Translation as an equivalent-term glossary.

Cloud Translation reads glossaries only from a Cloud Storage file, so:
  1. uv run python 04a_glossary.py            writes out/glossary.csv, prints upload commands
  2. run the printed gcloud commands           (bucket in us-central1, soft delete off)
  3. uv run python 04a_glossary.py --gcs-uri gs://.../glossary.csv
  4. set mt.google.glossary_id in config.yaml to the printed id

The glossary holds place and dish names only, never conversation data.
"""

import argparse
import csv

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import translate_v3 as tr

from lib import config
from lib.config import OUT

LANGUAGES = {"zh": "zh-CN", "yue": "yue", "en": "en"}  # glossary.yaml field -> language code


def write_csv() -> None:
    OUT.mkdir(exist_ok=True)
    path = OUT / "glossary.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(LANGUAGES.values())
        for term in config.glossary():
            writer.writerow(term[field] for field in LANGUAGES)
    print(f"Wrote {path} ({len(config.glossary())} terms)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gcs-uri", help="gs:// URI of the uploaded glossary.csv")
    parser.add_argument("--id", default="chongqing-v1", help="glossary id")
    parser.add_argument("--replace", action="store_true", help="delete an existing glossary first")
    args = parser.parse_args()

    write_csv()
    project = config.project()
    location = config.load()["mt"]["google"]["location"]
    if not args.gcs_uri:
        bucket = f"gs://{project}-bakeoff"
        print("\nUpload it, then re-run with --gcs-uri:")
        print(
            f"  gcloud storage buckets create {bucket} --location={location} "
            "--soft-delete-duration=0 --uniform-bucket-level-access"
        )
        print(f"  gcloud storage cp {OUT / 'glossary.csv'} {bucket}/glossary.csv")
        print(f"  uv run python 04a_glossary.py --gcs-uri {bucket}/glossary.csv")
        return

    client = tr.TranslationServiceClient()
    parent = f"projects/{project}/locations/{location}"
    name = f"{parent}/glossaries/{args.id}"
    if args.replace:
        try:
            client.delete_glossary(name=name).result(timeout=300)
            print(f"Deleted {args.id}")
        except NotFound:
            pass
    glossary = tr.Glossary(
        name=name,
        language_codes_set=tr.Glossary.LanguageCodesSet(language_codes=list(LANGUAGES.values())),
        input_config=tr.GlossaryInputConfig(gcs_source=tr.GcsSource(input_uri=args.gcs_uri)),
    )
    try:
        result = client.create_glossary(parent=parent, glossary=glossary).result(timeout=300)
    except AlreadyExists:
        raise SystemExit(f"Glossary {args.id} exists: use --replace or a new --id.") from None
    print(f"Created {result.name} with {result.entry_count} entries")
    print(f"Now set in config.yaml:  mt.google.glossary_id: {args.id}")


if __name__ == "__main__":
    main()
