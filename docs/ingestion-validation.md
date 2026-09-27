# PDF ingestion validation

Checked on 2026-09-27 with the current `pypdf` extractor. The PDFs were downloaded to the ignored `backend/data/validation/` directory for this check; they are not committed to the repository.

| Source | Shape | Result |
| --- | --- | --- |
| [UC Berkeley exam proctoring policy](https://asc.berkeley.edu/sites/default/files/proctoring_guidlines_2024-10-08.pdf) | 4-page text PDF | 12,978 extracted characters; all pages contained text. Page numbers remained 1–4. |
| [UC Berkeley student information release matrix](https://asc.berkeley.edu/sites/default/files/ferpareleasegrid.pdf) | 1-page table-heavy PDF | 1,619 extracted characters. Text is present, but table cell relationships are not reliably preserved by plain extraction. Do not treat table answers as verified without manual review. |
| [University of Pennsylvania 1825 catalogue](https://archives.upenn.edu/media/2017/10/catalogue-1825.pdf) | 7-page historical scan, including university regulations | 6,134 extracted characters; all pages contained an OCR text layer. Being scanned does not always mean `extract_text()` is empty. |

The [Penn Archives catalogue index](https://archives.upenn.edu/digitized-resources/docs-pubs/catalogues/) describes its copies as scanned. A separate generated image-only PDF was used in automated tests to verify the no-text/OCR rejection path; no OCR engine is bundled yet.

## Current behavior

- Each extracted page keeps its 1-based PDF page number for citations.
- Pages with no extractable text create a warning in the upload response and `GET /documents`.
- A PDF with no extractable text on any page is rejected with an OCR message.
- Chunking is configured by `CAMPUSLENS_CHUNK_SIZE` and `CAMPUSLENS_CHUNK_OVERLAP`; defaults are approximately 900 and 120 characters, at word boundaries, within each page.
- A replacement upload embeds the full new document before its chunks are swapped into SQLite. The document ID and omitted source metadata are retained. A failed embedding call or database write leaves the old document searchable.

## Known limit

Plain PDF extraction does not reconstruct tables. Evaluation questions based on the release matrix should be checked against the original page, and table-aware parsing can be considered if those questions become part of the corpus.
