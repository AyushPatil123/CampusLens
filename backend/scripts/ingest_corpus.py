"""Download and index the pinned public corpus through the running API."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx
import truststore


DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "corpus" / "berkeley_graduate_memos.json"
MAX_BYTES = 10 * 1024 * 1024


def load_manifest(path: Path) -> list[dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("Manifest must be a nonempty JSON list")
    urls = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {index} is not an object")
        for key in ("title", "source_url", "institution", "published_or_updated_date", "file_type", "retrieved_at"):
            if key not in entry:
                raise ValueError(f"Entry {index} is missing {key}")
        url = urlparse(entry["source_url"])
        if url.scheme != "https" or url.hostname != "grad.berkeley.edu" or not url.path.lower().endswith(".pdf"):
            raise ValueError(f"Entry {index} must use an official Berkeley Graduate Division PDF URL")
        if entry["file_type"] != "pdf" or entry["institution"] != "University of California, Berkeley":
            raise ValueError(f"Entry {index} has unexpected file type or institution")
        if not isinstance(entry["title"], str) or not entry["title"].strip():
            raise ValueError(f"Entry {index} needs a title")
        if entry["published_or_updated_date"] is not None:
            date.fromisoformat(entry["published_or_updated_date"])
        date.fromisoformat(entry["retrieved_at"])
        if entry["source_url"] in urls:
            raise ValueError(f"Duplicate source URL in entry {index}")
        urls.add(entry["source_url"])
    return entries


def download_pdf(client: httpx.Client, url: str) -> bytes:
    with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        if urlparse(str(response.url)).hostname != "grad.berkeley.edu":
            raise ValueError(f"Download redirected outside the official host: {url}")
        data = bytearray()
        for part in response.iter_bytes():
            data.extend(part)
            if len(data) > MAX_BYTES:
                raise ValueError(f"PDF exceeds the API's 10 MB limit: {url}")
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"Download is not a PDF: {url}")
    return bytes(data)


def sync_corpus(entries: list[dict], api: httpx.Client, source: httpx.Client, cache_dir: Path) -> dict:
    response = api.get("/documents")
    response.raise_for_status()
    indexed = {document["source_url"]: document for document in response.json() if document["source_url"]}
    counts = {"added": 0, "replaced": 0, "unchanged": 0, "failed": 0}
    for entry in entries:
        url = entry["source_url"]
        try:
            data = download_pdf(source, url)
            digest = hashlib.sha256(data).hexdigest()
            old = indexed.get(url)
            if old and all((
                old["sha256"] == digest,
                old["title"] == entry["title"],
                old["institution"] == entry["institution"],
                old["published_or_updated_date"] == entry["published_or_updated_date"],
            )):
                counts["unchanged"] += 1
                print(f"unchanged {entry['title']}")
                continue
            cache_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{digest}.pdf"
            cached = cache_dir / filename
            if not cached.exists():
                cached.write_bytes(data)
            form = {
                "title": entry["title"], "source_url": url,
                "institution": entry["institution"],
            }
            if entry["published_or_updated_date"]:
                form["published_or_updated_date"] = entry["published_or_updated_date"]
            endpoint = f"/documents/{old['id']}" if old else "/documents"
            method = api.put if old else api.post
            result = method(endpoint, data=form, files={"file": (filename, data, "application/pdf")})
            result.raise_for_status()
            action = "replaced" if old else "added"
            counts[action] += 1
            indexed[url] = result.json()
            print(f"{action} {entry['title']} ({result.json()['chunk_count']} chunks)")
            for warning in result.json()["extraction_warnings"]:
                print(f"  warning: {warning}")
        except (httpx.HTTPError, ValueError, OSError) as exc:
            counts["failed"] += 1
            print(f"failed {entry['title']}: {exc}")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/corpus"))
    parser.add_argument("--limit", type=int, help="Index only the first N entries for a smoke test")
    parser.add_argument("--check", action="store_true", help="Validate the manifest without downloading")
    args = parser.parse_args()
    entries = load_manifest(args.manifest)
    print(f"Manifest valid: {len(entries)} official PDF entries")
    if args.check:
        return 0
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        entries = entries[:args.limit]
    truststore.inject_into_ssl()
    with httpx.Client(base_url=args.api_url, timeout=120) as api, httpx.Client(
        timeout=60, headers={"User-Agent": "Mozilla/5.0 (compatible; CampusLens/0.1)"}
    ) as source:
        counts = sync_corpus(entries, api, source, args.cache_dir)
    print(json.dumps(counts, sort_keys=True))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
