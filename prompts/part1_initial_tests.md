Role: You are a QA engineer writing pytest tests to find bugs.

Spec:
The app is "AI Research Assistant", a single-user FastAPI web app (see README.md). It searches arXiv,
saves papers to a SQLite library, accepts PDF uploads, and uses Google Gemini to summarize papers and
answer questions about them. Requirements:

Search
- R1. GET /api/search?q=... searches arXiv. An empty or whitespace-only query returns 400.
- R2. Every keyword in the query must appear in the paper (keywords are ANDed, not ORed).
- R3. Each result has: title, authors (list of strings), year (4-digit string from the published date),
  abstract, url (arXiv id URL), pdf_url. Title, abstract and author names have whitespace/newlines
  collapsed to single spaces. A result with no PDF link has pdf_url = null.
- R4. If the arXiv request fails (network error or HTTP error status), the endpoint returns 502.

Library
- R5. POST /api/papers saves a search result (JSON: title, authors required; year, abstract, url,
  pdf_url optional) with source "arxiv" and returns the saved paper including its id.
- R6. Saving downloads the paper's PDF, extracts its text, and stores both; the returned paper has
  has_full_text = true.
- R7. If the PDF can't be downloaded (network error, HTTP error, or the response isn't a PDF), the paper
  is still saved, with has_full_text = false.
- R8. Saving a paper whose url is already in the library does not create a duplicate; it returns the
  existing paper. If that existing paper has no full text, saving again retries the PDF download.
- R9. GET /api/papers lists saved papers, newest first. Papers persist across restarts (SQLite).
  List and get responses never include the full text, and authors is always a list.
- R10. GET /api/papers/{id} returns one paper; unknown id returns 404.
- R11. DELETE /api/papers/{id} removes the paper, its stored PDF file, and its Q&A history, and returns
  {"ok": true}. Unknown id returns 404.

PDF upload
- R12. POST /api/papers/upload (multipart field "file"). Returns 400 if the file is not a PDF
  (doesn't start with %PDF), if the PDF can't be parsed, or if it has no extractable text
  (scanned image).
- R13. On success, Gemini extracts title, authors, year, abstract from the text of the first two pages
  (capped at 15,000 chars). The paper is saved with source "upload", its PDF is stored, it has full text,
  and the response includes "warning": null.
- R14. If the Gemini call fails, the paper is still saved with the file name (without extension) as its
  title, authors [], year null, abstract null, and the response "warning" explains what happened.

Summaries
- R15. POST /api/papers/{id}/summarize?regenerate=false returns {"summary": "..."}. If a summary is cached
  it is returned without calling the LLM; regenerate=true calls the LLM again and replaces the cache.
- R16. The summary is generated from the paper's full text (capped at 400,000 chars), not the abstract.
- R17. Unknown id returns 404. A paper without full text returns 400. An LLM failure returns 502 with a
  user-friendly message (see R22) and nothing is cached.

Q&A
- R18. POST /api/papers/{id}/ask with {"question": "..."} returns {"question", "answer"}. The question is
  stripped of surrounding whitespace; an empty/whitespace question returns 400.
- R19. Unknown id returns 404; a paper without full text returns 400; an LLM failure returns 502 and
  nothing is saved to history.
- R20. The paper's full text (capped at 400,000 chars) goes in the system instruction. Only the last 5
  previous Q&A turns are sent, oldest first, as alternating user/model messages, followed by the new
  question.
- R21. GET /api/papers/{id}/qa returns the paper's Q&A history in the order asked; unknown id returns 404.

LLM errors
- R22. User-facing error messages: status 429 or 503 -> "The Gemini model is busy or rate-limited right
  now. Try again in a minute."; 401 or 403 -> "Gemini rejected the API key. Check GEMINI_API_KEY in
  .env."; a missing GEMINI_API_KEY -> "GEMINI_API_KEY is not set. Add it to the .env file and restart the
  server."; anything else -> "LLM request failed: <error>".

Code under test:
Source is in app/. Read it for signatures and seams, but take expected behavior from the spec above.

app/main.py (FastAPI routes, primary target; `app = FastAPI()`)
  search(q: str)                                        GET    /api/search
  save_paper(paper: PaperIn)                            POST   /api/papers
  upload_paper(file: UploadFile)  (async)               POST   /api/papers/upload
  list_papers()                                         GET    /api/papers
  get_paper(paper_id: int)                              GET    /api/papers/{paper_id}
  summarize_paper(paper_id: int, regenerate: bool=False) POST  /api/papers/{paper_id}/summarize
  list_qa(paper_id: int)                                GET    /api/papers/{paper_id}/qa
  ask_question(paper_id: int, body: QuestionIn)         POST   /api/papers/{paper_id}/ask
  delete_paper(paper_id: int)                           DELETE /api/papers/{paper_id}
  PaperIn: title: str, authors: list[str], year/abstract/url/pdf_url: str | None = None
  QuestionIn: question: str

What it calls:
  app.search.search_arxiv(query, max_results=10) -> list[dict]
      calls httpx.get(ARXIV_URL, params={"search_query", "start", "max_results", "sortBy"}, timeout=20,
      follow_redirects=True), then parses the Atom XML (namespace http://www.w3.org/2005/Atom)
  app.pdf_utils.download_pdf(url) -> bytes          httpx.get; ValueError if body isn't a PDF
  app.pdf_utils.extract_pages(data: bytes) -> list[str]   pymupdf, one string per page
  app.pdf_utils.pdf_path_for(paper_id) -> Path      PDF_DIR / "<id>.pdf", creates PDF_DIR
  app.llm.extract_metadata(first_pages_text) -> dict(title, authors, year, abstract)
  app.llm.summarize(full_text) -> str
  app.llm.answer(full_text, question, history: list[dict]) -> str
  app.llm.friendly_error(e) -> str                  reads e.code
  app.llm.client() -> genai.Client                  RuntimeError if GEMINI_API_KEY unset; the llm
      functions call client().models.generate_content(model=..., contents=..., config=...)
  app.db: init_db(), add_paper(paper, source) -> int, list_papers() -> list[dict],
      get_paper(id) -> dict | None, set_full_text(id, pdf_path, full_text), delete_paper(id) -> pdf_path
      (str | None) or False if missing, get_full_text(id) -> str | None, set_summary(id, summary),
      list_qa(id) -> list[dict], add_qa(id, question, answer)

Test setup notes:
- Isolate storage: db.DATA_DIR, db.DB_PATH and pdf_utils.PDF_DIR are module globals read at call time;
  monkeypatch them to tmp_path and call db.init_db() (see the fixture below).
- Importing app.main runs db.init_db() and mounts static/ relative to the cwd, so run pytest from the
  project root (pytest.ini already sets testpaths=tests, pythonpath=., and coverage flags).
- No network: patch httpx.get for search/download unit tests, or patch app.main.search_arxiv /
  app.main.download_pdf for endpoint tests. Patch app.llm.client (fake object with
  .models.generate_content) or app.main.llm.summarize / answer / extract_metadata. No real API key.
- Build test PDFs in memory with pymupdf (pymupdf.open(), new_page(), insert_text(), tobytes()); a page
  with no inserted text gives a "scanned" PDF.
- Use fastapi.testclient.TestClient. Available deps: pytest, pytest-cov, fastapi, httpx, pymupdf.

Existing test for style:
```python
import pytest
from fastapi.testclient import TestClient

from app import db, main, pdf_utils


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(pdf_utils, "PDF_DIR", tmp_path / "pdfs")
    db.init_db()
    return TestClient(main.app)


def test_get_paper_returns_404_for_unknown_id(client):
    resp = client.get("/api/papers/999")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Paper not found"}
```

Step 1: List test cases as a table: input, expected output, which
requirement it checks. Cover normal, boundary, invalid, and edge cases.
Derive expected outputs from the SPEC, not the implementation.
Step 2: Write them as a single pytest file. Deterministic, no network,
one behavior per test, descriptive names.
If the spec is ambiguous, list your assumptions instead of guessing.
