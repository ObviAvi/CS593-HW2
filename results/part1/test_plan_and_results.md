# Part 1: Initial test suite

Prompt: `prompts/part1_initial_tests.md`. Agent: Claude Code (Opus 5.5). Test file: `tests/test_app.py`.

## Step 1: test cases

N = normal, B = boundary, I = invalid, E = edge/error path. Parametrized tests count once per parameter in the run total.

| # | Test | Input | Expected (from spec) | Req | Kind |
|---|---|---|---|---|---|
| 1 | test_search_empty_or_whitespace_query_returns_400 (x3) | q = "", "   ", "\t\n" | 400 | R1 | I/B |
| 2 | test_search_sends_all_keywords_anded_to_arxiv | q="attention  transformer" | search_query = `all:attention AND all:transformer` | R2 | N |
| 3 | test_search_single_keyword_query | q="attention" | search_query = `all:attention` | R2 | B |
| 4 | test_search_result_has_expected_fields | Atom feed, 2 entries | first result == exact dict (title, authors, year, abstract, url, pdf_url) | R3 | N |
| 5 | test_search_collapses_whitespace_in_title_abstract_authors | title/abstract/author with newlines + runs of spaces | single-spaced, trimmed | R3 | E |
| 6 | test_search_year_is_four_digit_string_from_published | published 2017-..., 2020-... | ["2017", "2020"] | R3 | N |
| 7 | test_search_result_without_pdf_link_has_null_pdf_url | entry with no `title="pdf"` link | pdf_url null | R3 | E |
| 8 | test_search_with_no_matches_returns_empty_list | empty feed | 200, [] | R3 | B |
| 9 | test_search_network_error_returns_502 | httpx.ConnectError | 502 | R4 | E |
| 10 | test_search_arxiv_http_error_status_returns_502 | arXiv 503 | 502 | R4 | E |
| 11 | test_save_paper_returns_saved_paper_with_id_and_arxiv_source | full PaperIn | id int, source "arxiv", fields echoed | R5 | N |
| 12 | test_save_paper_with_only_required_fields | title + authors [] | optional fields null, authors [] | R5 | B |
| 13 | test_save_paper_missing_required_field_is_rejected (x2) | no title / no authors | 422 | R5 | I |
| 14 | test_save_paper_downloads_pdf_and_sets_has_full_text | PDF response | has_full_text true, pdf_url fetched | R6 | N |
| 15 | test_save_paper_stores_extracted_text_and_pdf_file | PDF response | text in DB, bytes on disk | R6 | N |
| 16 | test_save_paper_pdf_http_error_or_non_pdf_still_saves_without_full_text (x2) | 404 / HTML body | saved, has_full_text false | R7 | E |
| 17 | test_save_paper_pdf_network_error_still_saves_without_full_text | ConnectError | saved, has_full_text false | R7 | E |
| 18 | test_save_paper_without_pdf_url_has_no_full_text | pdf_url null | has_full_text false | R6/R7 | B |
| 19 | test_save_duplicate_url_returns_existing_paper | same url twice | same id, 1 paper | R8 | N |
| 20 | test_save_duplicate_without_full_text_retries_download | fail then succeed | same id, has_full_text true | R8 | E |
| 21 | test_save_duplicate_with_full_text_does_not_redownload | succeed twice | 1 download | R8 | E |
| 22 | test_save_papers_without_url_are_not_deduplicated | 2 papers, url null | 2 papers | R8 | B |
| 23 | test_list_papers_empty_library | none | [] | R9 | B |
| 24 | test_list_papers_newest_first | 3 saves | ids descending | R9 | N |
| 25 | test_list_papers_excludes_full_text | seeded full text | no full_text key/value | R9 | N |
| 26 | test_get_paper_excludes_full_text | seeded full text | no full_text, has_full_text true | R9 | N |
| 27 | test_list_papers_authors_is_list | saved paper | authors list | R9 | N |
| 28 | test_papers_persist_across_restart | init_db + new client | paper still listed | R9 | N |
| 29 | test_get_paper_returns_saved_paper | saved id | 200, same body as save | R10 | N |
| 30 | test_get_paper_returns_404_for_unknown_id | id 999 | 404 "Paper not found" | R10 | I |
| 31 | test_delete_paper_returns_ok_and_removes_it | seeded id | {"ok": true}, then 404 | R11 | N |
| 32 | test_delete_paper_removes_stored_pdf_file | saved with PDF | file gone | R11 | N |
| 33 | test_delete_paper_removes_qa_history | seeded Q&A | history empty | R11 | N |
| 34 | test_delete_paper_whose_pdf_file_is_already_gone | pdf_path set, no file | {"ok": true} | R11 | E |
| 35 | test_delete_unknown_paper_returns_404 | id 999 | 404 | R11 | I |
| 36 | test_delete_paper_twice_returns_404_second_time | delete x2 | second 404 | R11 | E |
| 37 | test_upload_non_pdf_returns_400 | text bytes | 400 | R12 | I |
| 38 | test_upload_empty_file_returns_400 | b"" | 400 | R12 | B |
| 39 | test_upload_unparseable_pdf_returns_400 | `%PDF-1.4 garbage` | 400 | R12 | I |
| 40 | test_upload_scanned_pdf_without_text_returns_400 | 2 blank pages | 400 | R12 | E |
| 41 | test_upload_saves_paper_with_extracted_metadata | PDF + fake Gemini metadata | metadata fields, source upload, has_full_text, warning null | R13 | N |
| 42 | test_upload_stores_pdf_file | PDF | bytes on disk | R13 | N |
| 43 | test_upload_stores_full_text_of_all_pages | 3-page PDF | all pages in full text | R13 | N |
| 44 | test_upload_metadata_uses_only_first_two_pages | 3-page PDF | Gemini input has pages 1-2, not 3 | R13 | B |
| 45 | test_upload_metadata_text_capped_at_15000_chars | pages 10k + 10k chars | input length 15000 | R13 | B |
| 46 | test_upload_gemini_failure_falls_back_to_filename | Gemini 429, "my_paper.pdf" | title "my_paper", authors [], year/abstract null | R14 | E |
| 47 | test_upload_gemini_failure_warning_explains_error | Gemini 429 | warning contains busy message | R14 | E |
| 48 | test_upload_missing_api_key_warning | no key | warning contains missing-key message | R14/R22 | E |
| 49 | test_upload_fallback_title_strips_only_last_extension | "my.paper.v2.pdf" | "my.paper.v2" | R14 | B |
| 50 | test_summarize_returns_llm_summary | full text | {"summary": ...} | R15 | N |
| 51 | test_summarize_caches_summary | full text | summary stored | R15 | N |
| 52 | test_summarize_returns_cached_without_calling_llm | cached, regenerate=false | cached, 0 LLM calls | R15 | N |
| 53 | test_summarize_regenerate_calls_llm_and_replaces_cache | cached, regenerate=true | new summary, 1 call, cache replaced | R15 | N |
| 54 | test_summarize_uses_full_text_not_abstract | distinct markers | prompt has full text, not abstract | R16 | N |
| 55 | test_summarize_full_text_capped_at_400000_chars | 400k + marker | marker not sent | R16 | B |
| 56 | test_summarize_unknown_paper_returns_404 | id 999 | 404 | R17 | I |
| 57 | test_summarize_paper_without_full_text_returns_400 | no full text | 400, no LLM call | R17 | I |
| 58 | test_summarize_llm_failure_returns_502_with_friendly_message | Gemini 503 | 502, busy message | R17/R22 | E |
| 59 | test_summarize_llm_failure_caches_nothing | Gemini 503 | summary null | R17 | E |
| 60 | test_summarize_regenerate_failure_keeps_previous_summary | cached + 503 | old summary kept | R17 | E |
| 61 | test_summarize_missing_api_key_returns_502 | no key | 502, missing-key message | R17/R22 | E |
| 62 | test_ask_returns_question_and_answer | question | {"question","answer"} | R18 | N |
| 63 | test_ask_saves_turn_to_history | question | in /qa | R18/R21 | N |
| 64 | test_ask_strips_question_whitespace | "  Why?\n " | "Why?" returned, sent, stored | R18 | B |
| 65 | test_ask_empty_question_returns_400 (x3) | "", "   ", "\n\t" | 400, no LLM call | R18 | I |
| 66 | test_ask_unknown_paper_returns_404 | id 999 | 404 | R19 | I |
| 67 | test_ask_paper_without_full_text_returns_400 | no full text | 400 | R19 | I |
| 68 | test_ask_llm_failure_returns_502_and_saves_nothing | Gemini 401 | 502, key message, history empty | R19/R22 | E |
| 69 | test_ask_puts_full_text_in_system_instruction | full text marker | in system_instruction | R20 | N |
| 70 | test_ask_full_text_capped_at_400000_chars | 400k + marker | marker not sent | R20 | B |
| 71 | test_ask_without_history_sends_only_question | no history | [user: question] | R20 | B |
| 72 | test_ask_sends_only_last_five_turns_oldest_first | 7 prior turns | Q3..Q7 alternating user/model, then new question | R20 | B |
| 73 | test_qa_history_in_order_asked | 3 asks | same order | R21 | N |
| 74 | test_qa_history_empty_for_new_paper | none | [] | R21 | B |
| 75 | test_qa_history_unknown_paper_returns_404 | id 999 | 404 | R21 | I |
| 76 | test_friendly_error_known_status_codes (x4) | code 429/503/401/403 | busy / key messages | R22 | N |
| 77 | test_friendly_error_other_status_code_is_generic | code 500 | "LLM request failed: ..." | R22 | N |
| 78 | test_friendly_error_exception_without_code_is_generic | ValueError | "LLM request failed: ..." | R22 | E |
| 79 | test_friendly_error_unrelated_runtime_error_is_generic | RuntimeError("event loop closed") | "LLM request failed: event loop closed" | R22 | E |
| 80 | test_client_without_api_key_raises_with_message | no key | RuntimeError, missing-key message | R22 | E |

## Assumptions (spec is silent or ambiguous)

- Missing required fields (title/authors, `file`) get FastAPI's default 422; spec gives no code.
- R2 "ANDed" is checked via the query sent to arXiv (`all:w1 AND all:w2`); the actual filtering is arXiv's job, can't be checked offline.
- R3 for an entry with no `<published>`: not tested (spec says 4-digit year but doesn't say what to return when missing).
- R4 covers network/HTTP errors only; malformed XML from arXiv is unspecified, not tested.
- R6 assumes the downloaded PDF has extractable text; a text-less downloaded PDF is unspecified.
- R8: a null url is not "already in the library", so url-less papers are never deduplicated.
- R8: whether re-saving moves a paper to the top of the list is unspecified, not tested.
- R9 "persist across restarts" is simulated by re-running `init_db()` and a new TestClient on the same DB file.
- R14: "warning explains what happened" is checked as "contains the R22 friendly message".
- R17: summary cached but full text missing is unspecified, not tested.
- R18/R19: precedence of empty question vs unknown id is unspecified; each is tested in isolation.
- R22 "anything else" includes any RuntimeError that is not the missing-key error.

## Results

Command: `.venv/Scripts/python -m pytest` (from project root). Full log: `results/part1/pytest_output.txt`, coverage data: `results/part1/coverage.json`.

- 89 tests collected (80 functions incl. parametrized), 88 passed, 1 failed
- deterministic: 3 consecutive runs, same result
- ~6-10 s wall time, no network, no API key

### Coverage (line + branch)

| File | Stmts | Miss | Branch | BrPart | Cover | Missing |
|---|---|---|---|---|---|---|
| app/db.py | 61 | 0 | 6 | 0 | 100% | |
| app/llm.py | 49 | 3 | 12 | 2 | 92% | 20-23 |
| app/main.py | 120 | 0 | 28 | 1 | 99% | 145->147 |
| app/pdf_utils.py | 16 | 0 | 2 | 0 | 100% | |
| app/search.py | 20 | 0 | 6 | 0 | 100% | |
| **Total** | 266 | 3 | 54 | 3 | **98%** | |

Uncovered:
- `llm.py:20-23`: real `genai.Client` construction with a key present (retry options). Every test fakes `llm.client` or has no key.
- `main.py:145->147`: delete of a paper with `pdf_path` NULL (saved, download failed). Seeded papers always have a path.

### Failure

`test_friendly_error_unrelated_runtime_error_is_generic`

```
assert 'event loop closed' == 'LLM request failed: event loop closed'
```

Classification: app bug (spec deviation), not a test error. `llm.friendly_error` (`app/llm.py:33-34`) returns `str(e)` for every `RuntimeError`, intended only for the missing-key case. R22 says anything else -> `"LLM request failed: <error>"`, so any other RuntimeError (e.g. from the SDK or asyncio) reaches the user without the prefix/context.

### Other observations (not test failures)

- 336 `ResourceWarning: unclosed database` warnings. `db.py` uses `with sqlite3.connect(...) as conn`, which commits but never closes the connection, so every DB call leaks a connection until GC. Not in the spec, but real.
- `save_paper` writes the PDF to disk before extracting text; if extraction fails the file stays on disk while `pdf_path` stays NULL, so DELETE won't remove it (orphan file). Spec R11 is about the "stored PDF", so arguably out of scope; untested.
