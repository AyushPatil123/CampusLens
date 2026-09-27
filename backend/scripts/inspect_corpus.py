"""Check PDF extraction and empty pages before paying for embeddings."""

import argparse
from pathlib import Path

import httpx
import truststore

from app.documents import extract_pages
from scripts.ingest_corpus import DEFAULT_MANIFEST, download_pdf, load_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=str, default=str(DEFAULT_MANIFEST))
    parser.add_argument("--all", action="store_true", help="Inspect every manifest entry")
    args = parser.parse_args()
    entries = load_manifest(Path(args.manifest))
    selected = entries if args.all else [entries[i] for i in sorted({0, len(entries) // 4, len(entries) // 2, 3 * len(entries) // 4, len(entries) - 1})]
    truststore.inject_into_ssl()
    failures = 0
    with httpx.Client(timeout=60, headers={"User-Agent": "Mozilla/5.0 (compatible; CampusLens/0.1)"}) as source:
        for entry in selected:
            try:
                data = download_pdf(source, entry["source_url"])
                result = extract_pages("source.pdf", data)
                nonempty = [(number, text) for number, text in result.pages if text.strip()]
                if not nonempty:
                    raise ValueError("No extractable text")
                sample = " ".join(nonempty[0][1].split())[180:600]
                sample = sample.encode("ascii", "backslashreplace").decode("ascii")
                print(f"{entry['title']}: {len(result.pages)} pages, {len(nonempty)} with text, {len(data)} bytes")
                print(f"  first page text sample: {sample}")
                for warning in result.warnings:
                    print(f"  warning: {warning}")
            except (httpx.HTTPError, ValueError) as exc:
                failures += 1
                print(f"FAILED {entry['title']}: {exc}")
    print(f"Inspected {len(selected)} PDFs; {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
