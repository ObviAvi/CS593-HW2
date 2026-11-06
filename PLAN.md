# CS593 HW1: AI Research Assistant, build plan

> The original plan, written with the coding agent before implementation. See `README.md` for the final application.

## Context
Homework (due Oct 10, 11:59 PM): build a small web app with a coding agent. 60% app, 40% reflection on using the agent.
Required features: paper search via public API, save to local DB (persists across restarts), browse library, PDF upload with metadata extraction (title/authors/year/abstract), LLM summary based on full paper content, LLM Q&A on a selected paper.
Starting point: an empty project folder containing only the requirements PDF; Python 3.13 available.

Decisions: FastAPI + SQLite + vanilla HTML/JS, Google Gemini as the LLM, run locally (no deploy).

## Stack
- Backend: FastAPI + uvicorn, `sqlite3` (stdlib), `httpx`, `pymupdf` for PDF text, `google-genai` SDK, `python-dotenv`
- Paper search: **arXiv API** (free, no key, every result has a PDF link, which matters because summaries must use full content, not just abstracts)
- Frontend: single `static/index.html` + `app.js` + `style.css`, served by FastAPI
- Gemini: current Flash model (check the docs for the exact id). Whole paper text fits in context, so no chunking/RAG.

## Layout
```
CS593-HW1/
  app/main.py        FastAPI routes + static mount
  app/db.py          sqlite schema + queries
  app/search.py      arXiv query + XML parsing
  app/pdf_utils.py   download PDF, extract text
  app/llm.py         Gemini: extract_metadata, summarize, answer
  static/            index.html, app.js, style.css
  data/              papers.db, pdfs/  (gitignored)
  .env               GEMINI_API_KEY (gitignored)
  requirements.txt, README.md, AGENT_LOG.md
```

## DB schema (one table)
`papers(id, title, authors, year, abstract, url, pdf_path, full_text, source['arxiv'|'upload'], summary, created_at)`
Optional `qa(id, paper_id, question, answer, created_at)` to show Q&A history.

## API
- `GET /api/search?q=` → arXiv results (title, authors, year, abstract, url, pdf_url)
- `POST /api/papers` → save a search result; download its PDF, extract text, store
- `GET /api/papers`, `GET /api/papers/{id}`, `DELETE /api/papers/{id}`
- `POST /api/papers/upload` (multipart) → save PDF, extract text, Gemini pulls title/authors/year/abstract as JSON from first ~2 pages
- `POST /api/papers/{id}/summarize` → Gemini over full_text, cache in `summary`
- `POST /api/papers/{id}/ask` `{question}` → Gemini answers grounded on full_text

## Steps (each = one agent session, log it)
1. Setup: `git init`, venv, requirements, `.env`, hello-world FastAPI serving static page → verify: page loads at localhost:8000
2. Search: arXiv client + endpoint + results UI → verify: search "graph neural networks" shows 10 results with all 5 fields
3. Library: DB + save/list/delete + library tab → verify: save 2 papers, restart server, still listed
4. Full text for saved arXiv papers: download PDF on save, extract text → verify: `full_text` non-empty in DB
5. Upload: file input, pymupdf extract, Gemini metadata JSON, fallback to filename if parsing fails → verify: upload 2 real PDFs, metadata renders like search results
6. Summarize: button on paper detail view → verify: summary mentions method/results details not in abstract
7. Q&A: question box + answer display (+ history) → verify: the 5 example questions from the spec give sensible answers
8. Polish: loading spinners, error messages (API down, bad PDF, no key), README with setup/run steps
9. Reflection report (40%): written from AGENT_LOG.md

## Reflection prep (do this throughout, not at the end)
Keep `AGENT_LOG.md` while building: prompt given, what the agent produced, what broke, how you fixed/re-prompted, time spent. Note where the agent was wrong (e.g. outdated SDK calls, arXiv XML parsing bugs), where it saved time, and how you verified its output. Screenshots of the working app for the report.

## Risks
- arXiv rate limit: ~1 req / 3s; fine for manual use
- Scanned/odd PDFs: pymupdf may return little text; show an error rather than a bad summary
- Gemini free tier rate limits: cache summaries in DB
- Very long papers: truncate text to a safe char limit before sending

## Verification (end-to-end)
`uvicorn app.main:app --reload`, then in the browser: search → save → refresh/restart → library still there → upload PDF → metadata shown → summarize → ask the 5 sample questions.
