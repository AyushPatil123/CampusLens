# PDF ingestion validation

Checked on 2026-09-27 with the current `pypdf` extractor. The PDFs were downloaded to the ignored `backend/data/validation/` directory for this check; they are not committed to the repository.

| Source | Shape | Result |
| --- | --- | --- |
| [UC Berkeley exam proctoring policy](https://asc.berkeley.edu/sites/default/files/proctoring_guidlines_2024-10-08.pdf) | 4-page text PDF | 12,978 extracted characters; all pages contained text. Page numbers remained 1–4. |
| [UC Berkeley student information release matrix](https://asc.berkeley.edu/sites/default/files/ferpareleasegrid.pdf) | 1-page table-heavy PDF | 1,619 extracted characters. Text is present, but table cell relationships are not reliably preserved by plain extraction. Do not treat table answers as verified without manual review. |
| [University of Pennsylvania 1825 catalogue](https://archives.upenn.edu/media/2017/10/catalogue-1825.pdf) | 7-page historical scan, including university regulations | 6,134 extracted characters; all pages contained an OCR text layer. Being scanned does not always mean `extract_text()` is empty. |

The [Penn Archives catalogue index](https://archives.upenn.edu/digitized-resources/docs-pubs/catalogues/) describes its copies as scanned. A separate generated image-only PDF was used in automated tests to verify the no-text/OCR rejection path. At that baseline no OCR engine was bundled; the optional upgrade below adds one.

## Baseline behavior (2026-09-27)

- Each extracted page keeps its 1-based PDF page number for citations.
- Pages with no extractable text create a warning in the upload response and `GET /documents`.
- A PDF with no extractable text on any page is rejected with an OCR message.
- Chunking is configured by `CAMPUSLENS_CHUNK_SIZE` and `CAMPUSLENS_CHUNK_OVERLAP`; defaults are approximately 900 and 120 characters, at word boundaries, within each page.
- A replacement upload embeds the full new document before its chunks are swapped into SQLite. The document ID and omitted source metadata are retained. A failed embedding call or database write leaves the old document searchable.

## Known limit

Plain PDF extraction does not reconstruct tables. Evaluation questions based on the release matrix should be checked against the original page, and table-aware parsing can be considered if those questions become part of the corpus.

## Extraction upgrade (2026-10-03)

New ingestion now applies conservative Unicode/whitespace cleanup, retaining line and paragraph breaks. It removes soft hyphens and zero-width spaces without guessing broken words or joining ordinary hyphenated line endings. Warnings flag replacement/control characters and unusually fragmented text. Chunking prefers paragraph, sentence, and word boundaries within each original page, with a hard 900-character maximum and up to 120 characters of whole-word overlap. Long tokens are split to respect the bound.

Optional OCR renders textless PDF pages at 200 DPI with PDFium, then invokes local Tesseract. Existing text-layer pages are left alone. Warnings identify OCR pages and advise reviewing names, dates, amounts, and table relationships. Limits default to ten OCR pages per upload, ten seconds of recognition per page, and twelve million rendered pixels per page. Recognition failures reject ingestion before any embedding or database replacement; rendering bounds and timeouts are not a total HTTP deadline. See the README for setup and language configuration. No provider requests are used by OCR.

### Matched cached-corpus check

Run from `backend/` with the previously downloaded snapshot PDFs in `data/corpus`:

```powershell
uv run --no-sync python -m scripts.evaluate_extraction
```

The command checks all 33 PDF hashes against the fixed M3 snapshot, reconstructs the frozen original chunking algorithm and the new algorithm into separate temporary keyword indexes, and scores the same 50 answerable questions against the same page labels. It does not use or change the existing database, call providers, or update the saved M3/M4 baseline. [Raw results](../eval/extraction_results.json) contain per-question scores without source excerpts.

| Setting/result | Original | New cleanup/chunking |
| --- | ---: | ---: |
| Documents | 33 | 33 |
| Indexed PDF pages | 57 | 57 |
| Chunks | 189 | 228 |
| Keyword Hit@5 | 50/50 | 50/50 |
| Keyword MRR@10 | 0.9133 | 0.9167 |
| Both required documents at 5 | 7/8 | 8/8 |

All originally indexed pages remained indexed, and the new corpus emitted no quality warnings. That means the heuristics found no flagged patterns, not that extraction is perfect. Keyword ranking improved slightly and coverage improved on this fixed sample; the higher chunk count is a cost, not itself evidence of better answers. Dense/hybrid and answer support have not been re-evaluated for these chunks because that needs new embeddings. Existing databases retain the old chunks until an explicit replacement or `--force` manifest rebuild; preserve a separate baseline database before rebuilding. M4 remains on hold.

### Automated checks and remaining limits

Local validation passed 50 tests, with one real-recognition test skipped. Tests cover cleanup preserving policy codes/dates/amounts, paragraph and sentence boundaries, page identity, overlap/content coverage and oversized tokens, mixed PDF OCR selection, rendering/pixel bounds, missing engine/dependencies, recognition failures/timeouts, OCR warnings in document listings, blank OCR output, and rollback before embeddings. Fresh local server startup also passed. The Python rendering dependencies are installed locally; Tesseract itself is absent, so real recognition is skipped on this machine. CI is configured to install English Tesseract and run the generated image-only PDF recognition case; that updated workflow has not been executed here. Docker includes the same engine and Python extra but remains unverified locally because Docker is unavailable.

OCR does not reconstruct tables, correct a bad existing text layer, or guarantee reading order/recognition accuracy. The previously excluded corpus documents are not silently added to the fixed manifest or evaluation snapshot. They can be inspected separately with OCR later without changing baseline claims.
