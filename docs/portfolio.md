# Portfolio notes

## Resume bullet

Built CampusLens, a FastAPI/React document assistant indexing 33 university PDFs into 189 page-aware chunks; evaluated hybrid retrieval on a fixed 60-question set (50 answerable), achieving 50/50 Hit@5 and 0.9367 MRR@10 versus 0.9133 for keyword search, with 58.590 ms local retrieval p50.

These are the September 27, 2026 baseline results. Retrieval timing excludes query embedding, HTTP, and answer generation. The production diversity change has a separate matched run; do not attach this baseline latency to that version. Do not claim complete answer/citation accuracy while M4 is unfinished.

## Two-minute explanation

CampusLens addresses a practical problem: university information is spread across PDFs, and an answer is useful only when someone can check its source. I started with 33 historical UC Berkeley Graduate Division memos, keeping document URLs and PDF page numbers attached to every chunk. The UI shows numbered citations, excerpts, and a link to the original source page. These memos are historical evidence, so the app tells users to check current policy before acting.

I used SQLite for both document storage and an FTS5 keyword index, with embeddings stored alongside the chunks. Keyword search handles exact codes, dates, and policy vocabulary. Dense retrieval handles paraphrases. Hybrid retrieval combines their rankings with reciprocal rank fusion rather than trying to compare incompatible raw scores.

To test whether that helped, I wrote 60 fixed questions and labeled relevant source pages separately from model output. Fifty were answerable, including eight requiring two documents; ten had no answer in the corpus. I compared keyword, dense, and hybrid against the same snapshot and questions. Every mode found some relevant evidence in the top five for all 50 answerable questions. Hybrid improved first-hit ranking: MRR@10 was 0.9367, compared with keyword's 0.9133 and dense retrieval's 0.9290. It also cost more: local p50 retrieval was about 58.6 milliseconds versus 4.0 for keyword, excluding model and network calls.

That improvement was modest, and Hit@5 hid a problem. All modes included both required documents for only seven of eight multi-document questions. Reviewing an actual answer revealed repeated chunks crowding out a second memo. Capping hybrid context at two chunks per document improved two-document coverage to eight of eight on a matched rerun, without changing Hit@5 or MRR. That evidence justified a small retrieval change before adding a reranker.

The limits matter: this is a small corpus, the questions were written from known sources, and retrieval relevance does not prove answer support. The answer review has 26 of 30 responses saved and reviewed; the remaining quota-limited calls and same-sample comparison are on hold. I publish those limits alongside the measurements. Reviewers can see screenshots and run the app locally with their own provider key.

## Five-minute repository tour

1. Read the README preview and architecture diagram.
2. Open the desktop screenshot, source-page illustration, and mobile screenshot.
3. Compare the retrieval table and read its latency/answer-quality caveats.
4. Open `docs/evaluation.md` for per-mode results and reviewed weak cases.
5. Use the README local setup instructions; optionally use Compose for persistent storage.
