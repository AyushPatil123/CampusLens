# Berkeley Graduate Division corpus validation

Checked 2026-09-27. The source list comes from the [official Guide to Graduate Policy's memo section](https://grad.berkeley.edu/academics/policy/). The retained corpus is 33 policy and procedure PDFs from 2013–2022. It is an archival question answering scope: several documents revise earlier ones, so results must carry the memo title and date and should not be treated as current advice.

The initial screening downloaded and tested 35 candidates with `scripts.inspect_corpus --all`. Two PDFs had no extractable text and were removed from the manifest:

| Excluded PDF | Reason |
| --- | --- |
| [Parenting Leave for Graduate Students with Re-Enrollment](https://grad.berkeley.edu/wp-content/uploads/archive/Parenting-Leave-for-Graduate-Students-with-Re-Enrollment_MEMO-2016-April-14.pdf) | No extractable text; OCR needed |
| [ASEs in Self-Supporting Degree Programs](https://grad.berkeley.edu/wp-content/uploads/archive/ASEs-in-Self-Supporting-Degree-Programs-Memo-2014-Dec-19.pdf) | No extractable text; OCR needed |

The other 33 candidates downloaded as PDFs below 10 MB and had text on every page; no individual pages were skipped. A separate five document spot check inspected first page text from admissions evaluation, UGSI appointments, filing fee clarification, summer filing fees, and academic progress reporting. The extracted text retained substantive policy sentences and page boundaries. Older PDFs showed split words (for example, “Confer r al”) and occasional stray characters or zero width spaces, which may hurt exact-term retrieval. The script prints page counts, a text sample, and empty-page warnings without using a model key.

The full ingestion command was also exercised against a fresh temporary SQLite database with a fake embedding and answer provider: 33 PDFs added, zero failures, and `/ask` returned a citation with an original PDF URL and page. This verifies the download, extraction, indexing, and citation path without consuming API quota. A full Gemini rebuild remains a separate completion check.

No PDFs are stored in Git because redistribution permission has not been confirmed. The manifest records when links were checked, but does not pin source bytes. If Berkeley edits a PDF at the same URL, the ingestion command replaces the indexed copy based on SHA-256. A future evaluation should record the indexed hashes and query labels to make results comparable across source revisions.
