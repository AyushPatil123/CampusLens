# Evaluation record

## Corpus snapshot for M3

Measured 2026-09-27 after the M2 live rebuild:

| Setting or count | Observed value |
| --- | --- |
| Scope | UC Berkeley Graduate Division historical policy memos |
| Manifest documents indexed | 33 of 33 |
| Indexed chunks | 189 |
| Distinct document pages with indexed text | 57 |
| Embedding profile | `gemini:gemini-embedding-001:768` |
| Chunk size / overlap | 900 / 120 approximate characters |
| Storage | SQLite chunks and FTS5 keyword index |

## Fixed retrieval question set

The [questions](../eval/questions.jsonl) and [gold labels](../eval/labels.jsonl) contain 60 fixed questions: 15 direct lookups, 15 paraphrases, 12 exact terms or dates, 8 questions requiring two documents, and 10 questions with no answer in this corpus. The 50 answerable questions label pages across 29 of the 33 PDFs, using one-based PDF page numbers and original source URLs. Each evidence group requires one page; a group can list alternative pages supporting the same fact. Multi-document questions require all their groups. Labels were assigned from extracted source text, not from model answers. The [corpus snapshot](../eval/corpus_snapshot.json) records the SHA-256 of every indexed PDF and the embedding profile, so later runs can detect changed sources.

Validation command from `backend/`:

```powershell
uv run --no-sync python -m scripts.validate_eval --db data/m2-live.sqlite3
```

This checks question/label IDs, category and answerability consistency, source URLs against the manifest, the indexed source hashes and embedding profile, and gold pages against the indexed chunks. Validation passed for all 60 questions on 2026-09-27. The 10 no-answer labels mean the historical memo corpus lacks the requested information; they do not claim that Berkeley has no policy on those topics.

## Retrieval baseline

Measured 2026-09-27 on the 33-document, 189-chunk, 57-page snapshot above. All modes used the same 60 questions and the same 768-dimensional `gemini-embedding-001` query embeddings. Keyword search uses SQLite FTS5 BM25; dense search uses cosine similarity over stored embeddings; hybrid uses reciprocal rank fusion of their top 20 lists with constant 60. No answer-generation model was called. Run from `backend/`:

```powershell
uv run --no-sync python -m scripts.evaluate_retrieval --db data/m2-live.sqlite3
```

The command validates the indexed source hashes and embedding profile, caches query vectors in ignored `data/eval_query_embeddings.json`, and writes [per-question ranks and results](../eval/baseline_results.json). On a clean checkout, recreate the index using the README's M2 workflow first; that may require provider quota and may fail validation if public PDF bytes change. The first run of this evaluation also calls the embedding provider for 60 query vectors. Subsequent runs reuse the cache.

| Retrieval mode | Hit@5 | MRR@10 | Both documents at 5 | p50 retrieval | p95 retrieval |
| --- | ---: | ---: | ---: | ---: | ---: |
| Keyword | 50/50 (1.000) | 0.9133 | 7/8 (0.875) | 3.956 ms | 5.546 ms |
| Dense | 50/50 (1.000) | 0.9290 | 7/8 (0.875) | 56.728 ms | 67.740 ms |
| Hybrid | 50/50 (1.000) | 0.9367 | 7/8 (0.875) | 58.590 ms | 67.298 ms |

Hit@5 asks whether *any* acceptable evidence page appears among the first five chunks. MRR@10 uses the rank of the first acceptable page, with zero if none appears in ten. The two-document metric requires a page from each evidence group in the first five chunks. The ten no-answer questions are excluded from these relevance metrics; answer refusal will be measured in M4. Latencies cover local SQLite retrieval and ranking only, excluding query embedding, HTTP, and answer generation. These single-run local timings are indicative, not service response times. Chunk size and overlap were 900 and 120 approximate characters.

Hybrid improves MRR@10 by 0.0234 over keyword search and 0.0077 over dense search on this fixed set. It adds about 54.6 ms at p50 versus keyword because it scans stored embeddings. Hit@5 and two-document coverage do not improve. The 100% Hit@5 reflects this small, focused corpus and questions written from known memos; it is not a claim about unseen questions or citation correctness.

## Weak-case review

I inspected the ranked chunks for ten distinct questions where at least one mode put the first relevant page below rank 1 or missed one required source at five. These are ranking or top-five coverage errors, even though every answerable question has at least one hit by rank 5.

| Question | Observed weaker mode and cause |
| --- | --- |
| Q004 | Keyword rank 3, hybrid rank 2: TOEFL memo outranks the GSI oral English page. Similar vocabulary in competing documents. |
| Q013 | Keyword rank 2: a related Plan II summer memo precedes the labeled summer-enrollment memo. Document/version ambiguity. |
| Q018 | Dense rank 5: repeated chunks from page 1 precede the relevant page 2 of the in-absentia memo. Page ranking and chunk repetition. |
| Q020 | Dense rank 4: closely titled applicant-review memos from different years precede the labeled memo. Temporal/source ambiguity. |
| Q023 | Hybrid rank 2: page 1 of the correct GSI policy precedes its relevant page 2. Same-document page ranking. |
| Q028 | Keyword rank 3: page 1 and another GSI policy precede page 2 of the mentoring memo. Similar terminology and page ranking. |
| Q035 | All three modes rank page 2 above relevant page 1 of the same GSI policy. Exact-term/page ranking. |
| Q036 | Hybrid rank 3: another GSR memo and page 1 precede relevant page 2 of the GSI policy. Competing exact numbers and pages. |
| Q044 | Keyword's top five omit the 2015 filing-fee memo: three chunks from the 2018 summer memo and two from another summer memo fill the slots. Repeated chunks crowd out a required document. |
| Q048 | Dense and hybrid top five omit the 2015 filing-fee policy: several chunks from the 2016 clarification fill the slots. Repeated chunks crowd out a required document. |

The reviewed sources and gold pages are indexed, so these examples provide no evidence of an extraction failure or a missing source. Five labels allow two alternative pages after checking that both pages contain the same required fact; this prevents treating a valid page as a false miss. The remaining coverage issue suggests testing page diversity or date-aware source selection before adding an expensive reranker. A reranker is not justified by this baseline: it cannot repair the missing second source if only the crowded top five chunks are passed to it. M4 will measure whether these ranking errors actually affect answer support and citation correctness.

## Answer review status

An independent [extraction/chunking comparison](ingestion-validation.md#extraction-upgrade-2026-10-03) on October 3, 2026 retained the same 33 PDFs and 57 pages, with chunks increasing from 189 to 228. Keyword Hit@5 stayed at 50/50, MRR@10 rose from 0.9133 to 0.9167, and two-document coverage rose from 7/8 to 8/8. That comparison used temporary keyword indexes and no providers. It does not replace the dense/hybrid baseline or answer review; the existing indexed chunks and saved results were preserved.

M4's [rubric, sample, partial counts, and quota limitation](answer-evaluation.md) are tracked separately. The M3 retrieval numbers above do not measure whether generated answers are supported or whether cited excerpts prove their claims.

The M4 Q048 failure motivated a separate `hybrid_diverse` mode that caps context at two chunks per document. In a [matched rerun](../eval/diversity_results.json) on 2026-10-02, both original hybrid and diverse hybrid had 50/50 Hit@5 and 0.9367 MRR@10; two-document coverage rose from 7/8 to 8/8. Same-run p50 retrieval was 241.279 ms versus 226.343 ms, respectively. These timing values are much higher than the earlier local run, so the data support a coverage improvement but not a stable latency claim. `/ask` now uses diverse hybrid; the fixed answer baseline remains pinned to original hybrid for the eventual before/after comparison.
