# Answer and citation evaluation (M4)

## Fixed review set and procedure

The [sample](../eval/answer_sample.json) fixes 30 of the [M3 questions](../eval/questions.jsonl): five direct, five paraphrase, five exact, five requiring two documents, and all ten no-answer questions. The [M3 labels](../eval/labels.jsonl) identify expected source pages, but answer review checks the actual cited excerpts rather than treating a matching URL and page as proof of support. All questions concern the historical UC Berkeley Graduate Division memo corpus, not current policy advice.

Run from `backend/` after recreating the matching corpus index:

```powershell
uv run --no-sync python -m scripts.validate_eval --db data/campuslens.sqlite3
uv run --no-sync python -m scripts.evaluate_answers --db data/campuslens.sqlite3
```

The runner uses the production `DocumentService.ask` path, a fixed copy of the M3 query embeddings, and the selected answer model. For a consistent baseline it explicitly selects the original `hybrid` retrieval mode; `/ask` now defaults to `hybrid_diverse`. It saves every answer, citation excerpt, source URL and page, model name, retrieval mode, and service latency in ignored `backend/data/answer_baseline.jsonl`. Responses are appended as they complete; rerunning resumes missing IDs. The first run can consume provider quota. The reviewer reads each answer and all cited excerpts, checks the labeled source pages where needed, and records a judgment for each rubric field with a brief reason. The service latency excludes query embedding because vectors are cached. Keeping full source excerpts in ignored local data avoids redistributing large sections of public PDFs in the repository.

## Rubric

Each answerable question receives three separate binary judgments:

| Field | Pass condition |
| --- | --- |
| `supported` | Every material factual claim in the answer follows from the cited excerpts. A plausible claim without cited support fails. |
| `complete` | The answer covers every part of the question with the requested value or distinction. For a two-document question, it uses evidence from both periods or sources. A supported refusal on an answerable question fails. |
| `citation_correct` | Each factual claim has a bracketed citation that maps to a returned citation entry, and that specific excerpt supports the claim. A marker attached to the wrong source or page fails even if the answer is true. |

Each no-answer question receives `refusal_correct`: the response explicitly says the supplied historical memos cannot answer it, gives no invented fact, and returns no citation for a claimed answer. A generic refusal counts as correct; the app need not assert that Berkeley has no policy on the topic. An answerable question that refuses is recorded as incomplete, not a correct refusal.

Record `error_type` as one of `none`, `retrieval`, `generation`, `citation_mapping`, or `ambiguous_label`. `retrieval` means the necessary evidence is absent from the five supplied chunks; `generation` means it was supplied but the answer misstated or omitted it; `citation_mapping` means a marker points to a wrong or unsupported excerpt. These judgments are made by reading the actual excerpts, not by matching citation markers alone. Counts use the 20 answerable and 10 no-answer denominators separately. A response with a provider error is not silently scored as a refusal.

## Baseline and change log

The baseline began 2026-09-27 and resumed 2026-10-02 with the same fixed questions, corpus, answer model, and original `hybrid` retrieval mode. The Gemini model's daily free-tier quota and intermittent availability stopped it at 26 of 30 saved responses. The [manual judgments](../eval/answer_review.jsonl) cover all 20 answerable cases and six of ten no-answer cases:

| Measure | Reviewed result | Status |
| --- | ---: | --- |
| Fully supported answer | 17/20 | Complete answerable sample |
| Complete answer | 19/20 | Complete answerable sample |
| Citation supports every material claim | 17/20 | Complete answerable sample |
| Correct refusal | 6/6 | Partial; four no-answer cases missing |

Do not report 6/6 as the final refusal rate. Q053, Q056, Q059, and Q060 remain unrun; an API error is not counted as a refusal.

The regression set now includes an API test rejecting an unmapped source number and a prompt-construction test keeping an instruction embedded in document text out of the system instruction. Q001 and Q040 are fixed real examples of unsupported or imprecise claims for the next answer review. The prompt-construction test verifies message placement; it does not establish that the live model will resist every injected instruction. A live injected-document answer case remains to be reviewed when quota permits.

- Q001 gives the requested guideline components, but changes the memo's "should be made available" language to "must be provided" for distribution to the Graduate Division and committee members. This is a stronger obligation than the cited excerpt states.
- Q040 gives the correct TOEFL minimum of 90, but describes the policy as applying to "applications for Fall 2014". The cited memo says applications **received in Fall 2014**; the answer's timing is ambiguous enough to mislead about the admission term.
- Q048 refused an answerable 2015-versus-2016 filing-fee comparison. The five supplied hybrid chunks all came from the 2016 clarification, even though the 2015 filing-fee memo is indexed. This is a retrieval coverage failure, not evidence that the corpus lacks an answer.

The retrieval response to Q048 is a two-chunk-per-document cap in `hybrid_diverse`, now used by `/ask`. The [matched retrieval comparison](../eval/diversity_results.json) kept Hit@5 at 50/50 and MRR@10 at 0.9367, while complete two-document evidence at five improved from 7/8 to 8/8. Same-run p50 retrieval times were 241.279 ms for `hybrid` and 226.343 ms for `hybrid_diverse`; p95 values were 282.705 and 270.419 ms. Both modes ran much slower on this date than the September baseline, so this single run does not establish a latency improvement. A new live answer run is needed to show whether Q048's answer and the full sample improve.

After the Gemini quota resets, resume the four missing **baseline** cases with the first command below. Then run the identical sample with the revised retrieval mode into a separate ignored file and review it against the same rubric:

```powershell
uv run --no-sync python -m scripts.evaluate_answers --db data/m2-live.sqlite3 --retrieval-mode hybrid
uv run --no-sync python -m scripts.evaluate_answers --db data/m2-live.sqlite3 --retrieval-mode hybrid_diverse --output data/answer_diverse.jsonl
```

The runner checks the mode recorded in each response so it cannot silently mix old and new retrieval in one output file. Full before/after answer counts remain pending provider quota. Do not present M3 Hit@5 or these partial refusal counts as answer or citation accuracy for the full sample.
