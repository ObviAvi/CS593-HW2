# AI Research Assistant

A web app for finding, organizing, and understanding research papers. Search arXiv, save papers to a local library, upload your own PDFs, and use an LLM (Google Gemini) to summarize papers and answer questions about them.

Built for CS593 Homework 1 with a coding agent.

## Features

| Feature | What it does |
|---|---|
| **Paper search** | Searches arXiv by keyword or topic. Results show title, authors, year, abstract, and links to the paper and PDF. |
| **Local library** | Saves papers to a SQLite database, so they persist across page refreshes and server restarts. Saving downloads the paper's PDF and extracts its full text. |
| **PDF upload** | Upload any research paper PDF. Gemini reads the first pages and extracts the title, authors, year, and abstract, so uploads show up just like search results. |
| **Summaries** | Generates a structured summary (problem, approach, experiments, limitations) from the paper's **full text**, not just its abstract. Summaries are cached and can be regenerated. |
| **Q&A** | Ask natural-language questions about a paper ("What datasets are used?"). Answers are grounded in the full text, follow-up questions keep context, and history is saved per paper. |

## Requirements

- Python 3.13 (developed and tested on it; 3.10+ should work)
- A Google Gemini API key (from [Google AI Studio](https://aistudio.google.com/apikey))
- Internet access (arXiv and Gemini)

## Setup

1. **Create a virtual environment and install dependencies** (run from the project root):

   ```bash
   python -m venv .venv

   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

2. **Add your API key.** Copy `.env.example` to `.env` and fill it in:

   ```
   GEMINI_API_KEY=your-key-here
   # optional; defaults to gemini-3.1-flash-lite
   # GEMINI_MODEL=gemini-3.1-flash-lite
   ```

## Running

From the project root, with the virtual environment active:

```bash
uvicorn app.main:app --reload
```

Then open http://localhost:8000.

The database (`data/papers.db`) and stored PDFs (`data/pdfs/`) are created automatically on first run.

## Testing

The test suite (HW2) is in `tests/test_app.py`. It runs fully offline: arXiv, PDF downloads, and Gemini are faked, no API key is needed, and each test uses its own temporary database.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Run from the project root. `pytest.ini` turns on line + branch coverage for `app/` and prints missing lines. For an HTML report:

```bash
python -m pytest --cov-report=html     # open htmlcov/index.html
```

Saved results for each round (pytest log with the coverage table, `coverage.json`) are in `results/part1/`, `results/round1/`, `results/round2/`. `results/part1/test_plan_and_results.md` has the initial test-case table and assumptions. The prompt used to generate the initial suite is `prompts/part1_initial_tests.md`.

## Using the app

1. **Search** (sidebar): enter keywords and click **Search**, then **Save to library** on the papers you want.
2. **Add your own paper** (lime card in the sidebar): choose a PDF and click **Upload PDF**.
3. **Library**: browse saved papers; **Open** a paper to see its detail page, or **Remove** it.
4. On a paper's page, click **Summarize** for an LLM summary, and use **Ask about this paper** to ask questions (or click one of the suggested questions).

## How it works

```
Browser (static/)  ──fetch──▶  FastAPI (app/main.py)
                                 ├── search.py     ──▶ arXiv API
                                 ├── pdf_utils.py  ──▶ download PDFs, extract text (PyMuPDF)
                                 ├── llm.py        ──▶ Gemini API
                                 └── db.py         ──▶ SQLite (data/papers.db)
```

- **Saving a search result:** the backend stores the metadata, downloads the arXiv PDF, extracts its text, and stores it in the `papers` table.
- **Uploading a PDF:** the backend extracts the text and asks Gemini for structured JSON metadata from the first two pages. If Gemini fails, the paper is still saved with the file name as its title.
- **Summaries and Q&A:** the paper's full text is sent to Gemini; no chunking or retrieval is needed because papers fit in the model's context window. For Q&A, the paper goes in the system instruction and the last 5 Q&A turns are included so follow-ups make sense.
- Gemini calls retry automatically on rate-limit/overload errors (429/5xx).

## Project structure

```
app/
  main.py        FastAPI app: API routes, serves the frontend
  db.py          SQLite schema and queries (papers, qa tables)
  search.py      arXiv search and Atom XML parsing
  pdf_utils.py   PDF download and per-page text extraction
  llm.py         Gemini client and prompts: metadata, summary, Q&A
static/
  index.html     Single-page UI (search, library, paper detail)
  app.js         Frontend logic, calls the API
  style.css      Styles
requirements.txt Python dependencies (pinned)
.env.example     Template for the API key config
PLAN.md          Original build plan made with the coding agent
data/            Created at runtime, gitignored
```

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/search?q=...` | Search arXiv |
| GET | `/api/papers` | List saved papers |
| POST | `/api/papers` | Save a search result (JSON body; downloads its PDF) |
| POST | `/api/papers/upload` | Upload a PDF (multipart field `file`) |
| GET | `/api/papers/{id}` | Get one paper |
| DELETE | `/api/papers/{id}` | Remove a paper, its PDF, and its Q&A history |
| POST | `/api/papers/{id}/summarize?regenerate=false` | Get or generate the summary |
| GET | `/api/papers/{id}/qa` | Q&A history for a paper |
| POST | `/api/papers/{id}/ask` | Ask a question, body `{"question": "..."}` |

Interactive API docs are available at http://localhost:8000/docs while the server is running.

## Troubleshooting

- **"GEMINI_API_KEY is not set"**: create `.env` in the project root (see Setup) and restart the server.
- **"Gemini rejected the API key"**: the key is invalid or lacks access to the model; generate a new one or set `GEMINI_MODEL` to a model your key can use.
- **"The Gemini model is busy or rate-limited"**: temporary; wait a minute and try again.
- **"No full text" on a saved paper**: its PDF couldn't be downloaded, so summaries and Q&A are disabled for it. Saving it again from search retries the download.
- **"No text found in PDF"**: the PDF is a scanned image without a text layer; OCR isn't supported.

## Known limitations

- arXiv's relevance ranking is keyword-based, so some results are only loosely related.
- Single-user, local app: no accounts or authentication.
- The LLM is asked to write math as plain Unicode because the UI doesn't render LaTeX; it occasionally slips.
