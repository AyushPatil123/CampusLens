# CampusLens build plan

CampusLens is a university document assistant. A visitor asks a question about published policies or course information and receives an answer tied to specific document pages. The portfolio goal is to show that the system retrieves the right evidence, handles missing evidence, and has measured quality and latency.

## How to use this plan

- Work through the milestones in order. Check a box only after its completion check passes.
- Keep the app runnable after each milestone. Commit a milestone when it is complete.
- Record measured results in `docs/evaluation.md`; do not put estimated metrics on the resume.
- The immediate next task is to verify a full live M2 rebuild, then begin M3 evaluation.

## Current state

- [x] Cloned GitHub repository and named the project CampusLens.
- [x] Created a FastAPI backend with `GET /health`, `POST /documents`, `GET /documents`, `DELETE /documents/{id}`, and `POST /ask`.
- [x] Added PDF/text extraction, page-aware chunks, SQLite storage, dense retrieval plus SQLite FTS5 keyword retrieval, and Gemini/OpenAI-backed answers.
- [x] Added a local `.env.example`, ignored secrets/database files, and documented how to run the API.
- [x] Added tests covering the API flow, search, source metadata, PDF extraction, upload limits, replacement, rollback, provider selection, error handling, CORS, and response schemas. They pass without an API key.
- [x] Checked extraction on three university PDFs; results and limitations are in `docs/ingestion-validation.md`.
- [x] Ran a live Gemini request using the Berkeley exam proctoring PDF in a temporary database. The answerable question cited page 1; the unrelated question was refused without citations.

## M1 — Make the backend dependable

### M1.1 Source metadata and stable citations — complete

**Why:** A filename and page number are useful, but a portfolio demo should let someone open the original public source.

- [x] Add document fields for `title`, `source_url`, `institution`, and `published_or_updated_date` where known. Keep them optional for manual uploads.
- [x] Validate `source_url` as an HTTP(S) URL when supplied. Store it as data; do not fetch arbitrary URLs from the API yet.
- [x] Include these fields in `GET /documents` and in each citation returned by `POST /ask`.
- [x] Include the source title and page number in the model context so the displayed citation refers to the same passage.
- [x] Add a schema migration for existing SQLite databases instead of requiring users to delete their data.
- [x] Add a test that uploads a document with metadata and checks its citation and document listing.

**Done when:** A question response contains a usable title, page, excerpt, and original URL (when one was supplied); older databases still start.

### M1.2 Ingestion reliability — complete

- [x] Test extraction on at least three real university PDFs, including a multi-page file, a table-heavy file, and a scanned historical catalogue containing university regulations.
- [x] Add tests for PDF page numbers, UTF-8 failures, empty documents, and the 10 MB upload limit.
- [x] Record extraction warnings for pages with no text. Reject a fully image-only PDF with a clear message.
- [x] Make chunk size and overlap explicit settings, and document the values used in evaluation.
- [x] Handle a failed embedding request without saving a partial document or index entry.
- [x] Define the update flow: replace a document when its source has changed, then remove old chunks from both indexes.

**Done when:** Ingestion either creates a complete searchable document or leaves the database unchanged, and citations retain correct page numbers.

### M1.3 API behavior and local smoke test — complete

- [x] Add response models so `/docs` shows the shape of document, answer, and error responses.
- [x] Return clear API errors for provider failures and invalid configuration without exposing API keys or internal traces.
- [x] Add local development CORS configuration for the frontend origin.
- [x] With an API key set only in local `.env`, upload one real PDF and ask one answerable and one unanswerable question.
- [x] Save a short manual smoke-test recipe in the README. Never commit the API key or real user data.

**Done when:** All tests pass and the two live questions return a supported citation or an explicit refusal.

## M2 — Build a useful university corpus (workflow built; live full rebuild pending)

- [x] Choose one university and one document scope first: UC Berkeley Graduate Division historical policy and procedure memos. Avoid mixing institutions until source metadata and filtering work.
- [x] Collect roughly 30–50 public documents from official pages. The manifest has 33 PDFs with title, URL, institution, date, file type, and retrieval date.
- [x] Check whether documents can be redistributed. Rights are unclear, so keep only the manifest and ingestion scripts in the repo; downloaded PDFs are ignored.
- [x] Add a repeatable ingestion command that reads the manifest, downloads official documents, and skips unchanged files by hash.
- [x] Add institution/document filters to search and `/ask` before expanding to multiple universities.
- [x] Manually inspect extracted text for a sample of documents and record any skipped pages in `docs/corpus-validation.md`.

**Done when:** A clean checkout can recreate the index from the manifest and every citation points to its source page or document URL.

**Remaining check:** Run the full 33-document command with a live provider in a fresh database and verify citations. A fresh temporary database indexed all 33 PDFs with a fake provider, with zero failures and a page/URL citation; no full paid embedding run has been claimed.

## M3 — Evaluate retrieval before tuning it

- [ ] Create `eval/questions.jsonl` with 50–100 realistic questions: direct lookups, paraphrases, exact codes/dates, multi-document questions, and questions with no answer in the corpus.
- [ ] For each answerable question, label the relevant document and page or chunk. Keep labels separate from model output.
- [ ] Add an evaluation command for retrieval `Hit@5` and `MRR@10`; report the number of labeled questions.
- [ ] Compare keyword-only, embedding-only, and current hybrid retrieval on the same questions.
- [ ] Record p50 and p95 retrieval latency, corpus size, model names, chunk settings, and test date.
- [ ] Inspect at least ten failures and group them by cause: extraction, chunking, exact-term matching, semantic matching, or missing source.
- [ ] Try a reranker only if the measured failure cases suggest it will help; compare quality and latency before keeping it.

**Done when:** `docs/evaluation.md` contains a reproducible baseline table and explains at least one measured retrieval change.

## M4 — Evaluate answers and citations

- [ ] Define the answer rubric: factually supported, complete enough, correct citation, and appropriate refusal.
- [ ] Review a fixed sample of at least 30 answers by hand. Include all unanswerable cases in that review.
- [ ] Measure citation correctness and refusal behavior separately; a citation marker alone does not prove the cited passage supports the claim.
- [ ] Add regression cases for wrong source numbers, unsupported claims, and prompt instructions embedded in documents.
- [ ] Adjust prompts or retrieval based on failures, then rerun the same sample and document both versions.

**Done when:** The report includes examples of successes and failures, with before/after counts from the same question set.

## M5 — Build the demo interface

- [ ] Create a small React interface with a question box, answer panel, and clickable numbered citations.
- [ ] Show source title, page, and a short excerpt for each citation. Open the original URL when available.
- [ ] Add document list/upload/delete views for local demo use.
- [ ] Show loading, empty, error, and unanswerable states clearly.
- [ ] Test the main flow on desktop and mobile widths and with keyboard navigation.

**Done when:** A new visitor can understand the project and verify an answer's source without using Swagger or reading code.

## M6 — Package and deploy

- [ ] Add a repeatable setup path, preferably Docker Compose or equivalent, with a persistent database volume.
- [ ] Add CI for backend tests and frontend build/lint checks.
- [ ] Before a public deployment, protect uploads and `/ask` with authentication or another access control, plus request and file limits.
- [ ] Put secrets in deployment environment variables, never in Git or the browser bundle.
- [ ] Add health checks, structured error logs, and a simple way to rebuild the index.
- [ ] Test a fresh deployment from the README instructions.

**Done when:** The demo URL works, a fresh setup succeeds, and public visitors cannot spend API credits through unprotected endpoints.

## M7 — Make it resume-ready

- [ ] Add a short architecture diagram: source documents → extraction/chunking → indexes → retrieval → answer/citations.
- [ ] Add screenshots or a short GIF showing an answer and its source page.
- [ ] Put the problem, design choices, evaluation method, measured results, limitations, and setup steps in the README.
- [ ] Write one resume bullet using actual numbers: corpus size, question-set size, retrieval or citation metric, and latency or improvement.
- [ ] Prepare a two-minute explanation of why hybrid search helped or did not help on this corpus.

**Done when:** Someone can review the repository and demo in five minutes and see evidence for the claims on the resume.

## Scope guardrails

The initial target is a strong single-user document assistant for one university. OCR, multiple institutions, conversation memory, agent workflows, and a dedicated vector database are optional follow-ups. Add them only after the measured baseline shows a need. SQLite plus FTS5 and stored embeddings are adequate for the first corpus; reassess when retrieval latency or corpus size becomes a real constraint.
