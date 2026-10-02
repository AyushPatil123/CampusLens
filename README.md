# CampusLens

A citation-backed university document assistant. The backend ingests text PDFs and UTF-8 text files, searches page-aware chunks with semantic and keyword retrieval, and answers with numbered source excerpts. The React demo lets visitors ask questions and open the cited page evidence.

M3 uses a fixed [retrieval question set](eval/questions.jsonl) and separate [page labels](eval/labels.jsonl). On 50 answerable questions from the 33-document Berkeley memo corpus, hybrid search measured Hit@5 of 50/50 and MRR@10 of 0.9367, versus keyword MRR@10 of 0.9133. These are retrieval metrics, not answer or citation accuracy. See [the evaluation record](docs/evaluation.md) for the full comparison and limits.

## Backend layout

`app/main.py` creates the FastAPI app and wires dependencies. `app/routes.py` declares HTTP endpoints and `app/schemas.py` defines their request and response shapes. `app/services.py` coordinates ingestion and cited answers; `app/model_gateway.py` selects the model provider and translates its failures. `app/documents.py` extracts and chunks files, `app/store.py` owns SQLite document storage, and `app/retrieval.py` ranks embedding and FTS5 results. This keeps the retrieval logic in one place for the M3 comparisons.

## Run the backend

Requires Python 3.10+, [uv](https://docs.astral.sh/uv/), and a Gemini API key (or an OpenAI API key if you select that provider). From `backend/`:

```powershell
uv sync --extra dev --native-tls
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set GEMINI_API_KEY; keep CAMPUSLENS_PROVIDER=gemini
uv run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the interactive API and its response schemas. The SQLite database is created at `backend/data/campuslens.sqlite3` by default. `.env`, downloaded PDFs, and the database are ignored by Git. To use OpenAI, set `CAMPUSLENS_PROVIDER=openai` and `OPENAI_API_KEY` in `.env` instead. Changing the embedding provider or model requires replacing or re-uploading documents; `/ask` returns 409 for an index built with a different embedding profile. The local frontend origins default to `http://localhost:5173` and `http://127.0.0.1:5173`; override them with the comma-separated `CAMPUSLENS_CORS_ORIGINS` setting.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Health check |
| `POST /documents` | Upload a `.pdf` or `.txt` file (multipart field `file`, max 10 MB) |
| `PUT /documents/{id}` | Replace a document's file and index, keeping its ID and omitted source metadata |
| `GET /documents` | List uploaded documents |
| `DELETE /documents/{id}` | Delete a document and its search index entries |
| `POST /ask` | Ask `{ "question": "When is tuition due?" }` |

Run tests with `uv run --no-sync pytest`. Scanned PDFs need OCR and are rejected if no text can be extracted. This is a local single-user prototype; public deployment needs authentication and request limits.

`POST /ask` also accepts optional exact-match `institution` and `document_ids` filters. They constrain both keyword and embedding retrieval before the answer is generated. `GET /documents` includes each file's SHA-256 so the corpus command can skip unchanged files.

## Berkeley Graduate Division memo corpus (M2)

The [manifest](corpus/berkeley_graduate_memos.json) lists 33 public PDFs linked from UC Berkeley's [Guide to Graduate Policy](https://grad.berkeley.edu/academics/policy/). The scope is **historical Graduate Division policy and procedure memos from 2013–2022**, not current policy advice. Some memos amend or supersede others; users should check the current guide before acting on an answer. The manifest records title, original PDF URL, institution, publication date, file type, and the date the source list was checked. Two image only PDFs were excluded because the current extractor cannot read them. [Corpus extraction notes](docs/corpus-validation.md) record the check.

PDF redistribution rights are unclear, so the repository contains the manifest and scripts, not the PDFs. Downloads go to ignored `backend/data/corpus/`. To recreate the index from a clean checkout, first configure the provider as above and start the API. Then, in another terminal from `backend/`, run:

```powershell
uv sync --extra dev --native-tls
uv run --no-sync python -m scripts.ingest_corpus --check
uv run --no-sync python -m scripts.inspect_corpus
uv run --no-sync python -m scripts.ingest_corpus
```

The command downloads only the 33 listed official PDFs, rejects redirects to other hosts and files above the API's 10 MB limit, and uploads each with source metadata. It compares downloaded SHA-256 values with `GET /documents`: unchanged files skip embedding, changed files replace their existing document ID. Uploads are spaced four seconds apart by default, and HTTP 429 responses receive two bounded retries. A repeated rate limit stops the run; rerun later to resume from indexed hashes. Override pacing with `--upload-delay` and retries with `--rate-limit-retries`. Other failed downloads or uploads are reported and make the command exit nonzero. For a small paid smoke test, use `--limit 1`. `scripts.inspect_corpus --all` checks every PDF's extractable pages without calling the model. Public sources may change after the manifest's retrieval date; the command records the bytes it receives at run time through their indexed hashes.

## Retrieval evaluation (M3)

After recreating the corpus with the M2 ingestion workflow, run from `backend/` against the default database:

```powershell
uv run --no-sync python -m scripts.validate_eval --db data/campuslens.sqlite3
uv run --no-sync python -m scripts.evaluate_retrieval --db data/campuslens.sqlite3
```

The evaluation checks document hashes against [the fixed snapshot](eval/corpus_snapshot.json), compares keyword, dense, and hybrid rankings, and writes [detailed results](eval/baseline_results.json). It embeds 60 questions on the first run and caches the vectors in ignored `backend/data/`; later runs reuse them. The [evaluation record](docs/evaluation.md) defines the metrics, reports local retrieval latency, and reviews weaker cases. Rebuilding from changed public PDFs or a different embedding profile requires a new snapshot and labels before comparing scores.

## Answer and citation evaluation (M4)

The [fixed answer sample](eval/answer_sample.json) has 30 questions, including all ten no-answer cases. [The rubric](docs/answer-evaluation.md) scores factual support, completeness, citation correctness, and refusal separately. After rebuilding the matching index, run from `backend/`:

```powershell
uv run --no-sync python -m scripts.evaluate_answers --db data/campuslens.sqlite3
uv run --no-sync python -m scripts.summarize_answer_review
```

The first command uses cached M3 query embeddings and the production answer service. It resumes completed IDs from ignored `backend/data/answer_baseline.jsonl`. Full cited excerpts stay in that ignored local file; [manual judgments](eval/answer_review.jsonl) contain concise reasons without redistributing source text. The baseline run saved and reviewed 26 of 30 answers across September 27 and October 2. All 20 answerable cases have been reviewed; four no-answer cases remain because of the selected Gemini model's daily free-tier generation limit. `/ask` now caps hybrid context at two chunks per document after a measured two-document coverage failure. The baseline runner stays on the original `hybrid` mode; pass `--retrieval-mode hybrid_diverse --output data/answer_diverse.jsonl` to evaluate the revised mode into a separate file. See [the answer evaluation record](docs/answer-evaluation.md) for measured retrieval changes, partial answer counts, and remaining work.

## Demo interface (M5)

The [React and TypeScript frontend](frontend/) shows answers with clickable citation numbers, source title, PDF page, excerpt, and original URL. It also supports document upload, selection, listing, and deletion. Empty, loading, error, and unsupported-answer states are shown in the interface. The initial corpus is historical Berkeley memos; the interface and API accept documents from other institutions.

Use Node.js 22.12+ and npm. Start the backend as described above, then run this in a second terminal from `frontend/`:

```powershell
npm ci
npm run dev
```

Open <http://127.0.0.1:5173/>. Vite proxies `/api` to the FastAPI server at `http://127.0.0.1:8000`, so no frontend API key is needed. If you host the frontend separately, set `VITE_API_BASE_URL` to the backend's public base URL and configure backend CORS accordingly. Do not put provider keys in frontend environment variables. Uploading and asking live questions use the selected provider's quota.

If npm on this Windows machine reports `UNABLE_TO_VERIFY_LEAF_SIGNATURE`, the local ignored `backend/data/npm-ca-bundle.pem` generated from Windows trusted roots can be used in that terminal before `npm ci`: `$env:NODE_EXTRA_CA_CERTS=(Resolve-Path ../backend/data/npm-ca-bundle.pem).Path`. Keep certificate verification enabled.

Run `npm run build` for a production bundle and `npm run smoke` for a browser smoke test using Microsoft Edge. The smoke test mocks API responses so it does not spend model quota; it checks desktop and mobile widths, keyboard navigation, citation links, document filters and management, refusal, loading, error, and empty states. Set `CAMPUSLENS_BROWSER` to another Chromium executable path if Edge is unavailable. A local proxy check also returned `ok` from `/api/health` and loaded all 33 indexed documents from the existing backend without calling the model.

## Live PDF smoke test

After setting your selected provider's key in `backend/.env`, run this from `backend/` to download a public Berkeley policy PDF into the ignored `data/` directory and test upload plus two questions against a temporary SQLite database:

```powershell
New-Item -ItemType Directory -Force data/validation | Out-Null
curl.exe -L --fail --output data/validation/berkeley-exam-proctoring.pdf https://asc.berkeley.edu/sites/default/files/proctoring_guidlines_2024-10-08.pdf
uv run --no-sync python -m scripts.smoke_test data/validation/berkeley-exam-proctoring.pdf
```

The script asks when student athletes must meet professors about exam conflicts and asks an unrelated pet iguana question. Check that the first answer cites the policy page and the second explicitly says the uploaded document has no answer. It prints the answers and citation metadata; it never prints the API key. Live requests use API quota. If a provider rejects authentication, model configuration, or rate limits, the API returns a short 503 or 429 error rather than provider internals.

An upload can also include optional form fields: `title`, `source_url`, `institution`, and `published_or_updated_date` (ISO date such as `2026-07-01`). `source_url` must use HTTP or HTTPS and is stored for citations; the API does not fetch it. When `title` is omitted, citations use the filename. Existing SQLite databases are migrated automatically on startup.

The upload response and `GET /documents` include `extraction_warnings` for PDF pages without extractable text. Chunk size and overlap can be set with `CAMPUSLENS_CHUNK_SIZE` and `CAMPUSLENS_CHUNK_OVERLAP` (defaults: 900 and 120 approximate characters). See [PDF ingestion validation](docs/ingestion-validation.md) for observed results and limits on three university PDFs.
