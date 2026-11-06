"""Test suite for AI Research Assistant. Expected behavior comes from the spec (R1-R22)."""
import sqlite3
from types import SimpleNamespace

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, llm, main, pdf_utils

BUSY = "The Gemini model is busy or rate-limited right now. Try again in a minute."
BAD_KEY = "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
NO_KEY = "GEMINI_API_KEY is not set. Add it to the .env file and restart the server."

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is
      All   You Need</title>
    <summary>  The dominant sequence
  transduction models.  </summary>
    <author><name>Ashish
      Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <link href="http://arxiv.org/abs/1706.03762v7" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v7" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2001.00001v1</id>
    <published>2020-01-01T00:00:00Z</published>
    <title>No PDF Paper</title>
    <summary>Abstract two.</summary>
    <author><name>Jane Doe</name></author>
    <link href="http://arxiv.org/abs/2001.00001v1" rel="alternate" type="text/html"/>
  </entry>
</feed>"""

EMPTY_FEED = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


# ---------- fixtures and helpers ----------

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No real Gemini key and no network unless a test installs a fake."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_client", None)

    def no_network(*args, **kwargs):
        raise httpx.ConnectError("network disabled in tests")

    monkeypatch.setattr(httpx, "get", no_network)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(pdf_utils, "PDF_DIR", tmp_path / "pdfs")
    db.init_db()
    return TestClient(main.app)


class FakeAPIError(Exception):
    def __init__(self, code, message="api error"):
        super().__init__(message)
        self.code = code


class FakeModels:
    def __init__(self, text="LLM output", parsed=None, error=None):
        self.text, self.parsed, self.error = text, parsed, error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, parsed=self.parsed)


@pytest.fixture
def fake_llm(monkeypatch):
    def install(**kwargs):
        models = FakeModels(**kwargs)
        monkeypatch.setattr(llm, "client", lambda: SimpleNamespace(models=models))
        return models
    return install


def fake_http(monkeypatch, status=200, content=b"", text=None):
    """Replace httpx.get; returns the list of recorded calls."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        req = httpx.Request("GET", url)
        if text is not None:
            return httpx.Response(status, text=text, request=req)
        return httpx.Response(status, content=content, request=req)

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def make_pdf(pages):
    """In-memory PDF; an empty string gives a page with no text (scanned)."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def seed_paper(full_text="Full text of the paper.", summary=None, abstract="An abstract.", url=None):
    pid = db.add_paper({"title": "Seeded Paper", "authors": ["A. Author"], "year": "2024",
                        "abstract": abstract, "url": url, "pdf_url": None}, source="arxiv")
    if full_text is not None:
        db.set_full_text(pid, pdf_utils.pdf_path_for(pid), full_text)
    if summary is not None:
        db.set_summary(pid, summary)
    return pid


ARXIV_PAPER = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": "2017",
    "abstract": "The dominant sequence transduction models.",
    "url": "http://arxiv.org/abs/1706.03762v7",
    "pdf_url": "http://arxiv.org/pdf/1706.03762v7",
}


def upload(client, data, filename="paper.pdf"):
    return client.post("/api/papers/upload", files={"file": (filename, data, "application/pdf")})


def good_metadata():
    return llm.PaperMetadata(title="Uploaded Title", authors=["Ada Lovelace", "Alan Turing"],
                             year="2021", abstract="Uploaded abstract.")


# ---------- Search (R1-R4) ----------

@pytest.mark.parametrize("q", ["", "   ", "\t\n"])
def test_search_empty_or_whitespace_query_returns_400(client, q):
    resp = client.get("/api/search", params={"q": q})
    assert resp.status_code == 400


def test_search_sends_all_keywords_anded_to_arxiv(client, monkeypatch):
    calls = fake_http(monkeypatch, text=ATOM)
    client.get("/api/search", params={"q": "attention  transformer"})
    assert calls[0]["params"]["search_query"] == "all:attention AND all:transformer"


def test_search_single_keyword_query(client, monkeypatch):
    calls = fake_http(monkeypatch, text=ATOM)
    client.get("/api/search", params={"q": "attention"})
    assert calls[0]["params"]["search_query"] == "all:attention"


def test_search_result_has_expected_fields(client, monkeypatch):
    fake_http(monkeypatch, text=ATOM)
    resp = client.get("/api/search", params={"q": "attention"})
    assert resp.status_code == 200
    assert resp.json()[0] == ARXIV_PAPER


def test_search_collapses_whitespace_in_title_abstract_authors(client, monkeypatch):
    fake_http(monkeypatch, text=ATOM)
    first = client.get("/api/search", params={"q": "attention"}).json()[0]
    assert first["title"] == "Attention Is All You Need"
    assert first["abstract"] == "The dominant sequence transduction models."
    assert first["authors"][0] == "Ashish Vaswani"


def test_search_year_is_four_digit_string_from_published(client, monkeypatch):
    fake_http(monkeypatch, text=ATOM)
    results = client.get("/api/search", params={"q": "attention"}).json()
    assert [r["year"] for r in results] == ["2017", "2020"]


def test_search_result_without_pdf_link_has_null_pdf_url(client, monkeypatch):
    fake_http(monkeypatch, text=ATOM)
    second = client.get("/api/search", params={"q": "attention"}).json()[1]
    assert second["pdf_url"] is None
    assert second["url"] == "http://arxiv.org/abs/2001.00001v1"


def test_search_with_no_matches_returns_empty_list(client, monkeypatch):
    fake_http(monkeypatch, text=EMPTY_FEED)
    resp = client.get("/api/search", params={"q": "zzzzqqq"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_network_error_returns_502(client):
    # autouse fixture makes httpx.get raise ConnectError
    resp = client.get("/api/search", params={"q": "attention"})
    assert resp.status_code == 502


def test_search_arxiv_http_error_status_returns_502(client, monkeypatch):
    fake_http(monkeypatch, status=503, text="Service Unavailable")
    resp = client.get("/api/search", params={"q": "attention"})
    assert resp.status_code == 502


# ---------- Library: save (R5-R8) ----------

def test_save_paper_returns_saved_paper_with_id_and_arxiv_source(client):
    resp = client.post("/api/papers", json=ARXIV_PAPER)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["id"], int)
    assert body["source"] == "arxiv"
    for key, value in ARXIV_PAPER.items():
        assert body[key] == value


def test_save_paper_with_only_required_fields(client):
    resp = client.post("/api/papers", json={"title": "Minimal", "authors": []})
    assert resp.status_code == 200
    body = resp.json()
    assert (body["year"], body["abstract"], body["url"], body["pdf_url"]) == (None, None, None, None)
    assert body["authors"] == []


@pytest.mark.parametrize("missing", ["title", "authors"])
def test_save_paper_missing_required_field_is_rejected(client, missing):
    payload = {k: v for k, v in ARXIV_PAPER.items() if k != missing}
    resp = client.post("/api/papers", json=payload)
    assert resp.status_code == 422


def test_save_paper_downloads_pdf_and_sets_has_full_text(client, monkeypatch):
    calls = fake_http(monkeypatch, content=make_pdf(["Transformer body text"]))
    body = client.post("/api/papers", json=ARXIV_PAPER).json()
    assert body["has_full_text"] is True
    assert calls[0]["url"] == ARXIV_PAPER["pdf_url"]


def test_save_paper_stores_extracted_text_and_pdf_file(client, monkeypatch):
    pdf = make_pdf(["Transformer body text"])
    fake_http(monkeypatch, content=pdf)
    pid = client.post("/api/papers", json=ARXIV_PAPER).json()["id"]
    assert "Transformer body text" in db.get_full_text(pid)
    assert pdf_utils.pdf_path_for(pid).read_bytes() == pdf


@pytest.mark.parametrize("status,content", [
    (404, b"not found"),
    (200, b"<html>captcha page</html>"),
])
def test_save_paper_pdf_http_error_or_non_pdf_still_saves_without_full_text(client, monkeypatch, status, content):
    fake_http(monkeypatch, status=status, content=content)
    resp = client.post("/api/papers", json=ARXIV_PAPER)
    assert resp.status_code == 200
    assert resp.json()["has_full_text"] is False
    assert len(client.get("/api/papers").json()) == 1


def test_save_paper_pdf_network_error_still_saves_without_full_text(client):
    resp = client.post("/api/papers", json=ARXIV_PAPER)
    assert resp.status_code == 200
    assert resp.json()["has_full_text"] is False
    assert len(client.get("/api/papers").json()) == 1


def test_save_paper_corrupt_pdf_leaves_no_file_on_disk(client, monkeypatch):
    fake_http(monkeypatch, content=b"%PDF-1.4 truncated garbage")
    body = client.post("/api/papers", json=ARXIV_PAPER).json()
    assert body["has_full_text"] is False
    assert not pdf_utils.pdf_path_for(body["id"]).exists()


def test_save_paper_without_pdf_url_has_no_full_text(client):
    payload = {**ARXIV_PAPER, "pdf_url": None}
    assert client.post("/api/papers", json=payload).json()["has_full_text"] is False


def test_save_duplicate_url_returns_existing_paper(client):
    first = client.post("/api/papers", json=ARXIV_PAPER).json()
    second = client.post("/api/papers", json=ARXIV_PAPER).json()
    assert second["id"] == first["id"]
    assert len(client.get("/api/papers").json()) == 1


def test_save_duplicate_without_full_text_retries_download(client, monkeypatch):
    first = client.post("/api/papers", json=ARXIV_PAPER).json()  # network disabled -> no full text
    assert first["has_full_text"] is False
    fake_http(monkeypatch, content=make_pdf(["Retried text"]))
    second = client.post("/api/papers", json=ARXIV_PAPER).json()
    assert second["id"] == first["id"]
    assert second["has_full_text"] is True


def test_save_duplicate_with_full_text_does_not_redownload(client, monkeypatch):
    calls = fake_http(monkeypatch, content=make_pdf(["Body"]))
    client.post("/api/papers", json=ARXIV_PAPER)
    client.post("/api/papers", json=ARXIV_PAPER)
    assert len(calls) == 1


def test_save_papers_without_url_are_not_deduplicated(client):
    client.post("/api/papers", json={"title": "A", "authors": []})
    client.post("/api/papers", json={"title": "B", "authors": []})
    assert len(client.get("/api/papers").json()) == 2


# ---------- Library: list / get (R9-R10) ----------

def test_list_papers_empty_library(client):
    assert client.get("/api/papers").json() == []


def test_list_papers_newest_first(client):
    ids = [client.post("/api/papers", json={"title": t, "authors": [], "url": f"u/{t}"}).json()["id"]
           for t in ("first", "second", "third")]
    listed = [p["id"] for p in client.get("/api/papers").json()]
    assert listed == list(reversed(ids))


def test_list_papers_excludes_full_text(client):
    seed_paper(full_text="SECRET FULL TEXT")
    paper = client.get("/api/papers").json()[0]
    assert "full_text" not in paper
    assert "SECRET FULL TEXT" not in str(paper)


def test_get_paper_excludes_full_text(client):
    pid = seed_paper(full_text="SECRET FULL TEXT")
    paper = client.get(f"/api/papers/{pid}").json()
    assert "full_text" not in paper
    assert paper["has_full_text"] is True


def test_list_papers_authors_is_list(client):
    client.post("/api/papers", json=ARXIV_PAPER)
    assert client.get("/api/papers").json()[0]["authors"] == ARXIV_PAPER["authors"]


def test_papers_persist_across_restart(client):
    pid = client.post("/api/papers", json=ARXIV_PAPER).json()["id"]
    db.init_db()  # simulate server restart on the same DB file
    restarted = TestClient(main.app)
    assert [p["id"] for p in restarted.get("/api/papers").json()] == [pid]


def test_get_paper_returns_saved_paper(client):
    saved = client.post("/api/papers", json=ARXIV_PAPER).json()
    resp = client.get(f"/api/papers/{saved['id']}")
    assert resp.status_code == 200
    assert resp.json() == saved


def test_get_paper_returns_404_for_unknown_id(client):
    resp = client.get("/api/papers/999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Paper not found"}


# ---------- Library: delete (R11) ----------

def test_delete_paper_returns_ok_and_removes_it(client):
    pid = seed_paper()
    resp = client.delete(f"/api/papers/{pid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert client.get(f"/api/papers/{pid}").status_code == 404


def test_delete_paper_removes_stored_pdf_file(client, monkeypatch):
    fake_http(monkeypatch, content=make_pdf(["Body"]))
    pid = client.post("/api/papers", json=ARXIV_PAPER).json()["id"]
    path = pdf_utils.pdf_path_for(pid)
    assert path.exists()
    client.delete(f"/api/papers/{pid}")
    assert not path.exists()


def test_delete_paper_removes_qa_history(client):
    pid = seed_paper()
    db.add_qa(pid, "Q1", "A1")
    client.delete(f"/api/papers/{pid}")
    assert db.list_qa(pid) == []


def test_delete_paper_saved_without_pdf(client):
    pid = client.post("/api/papers", json=ARXIV_PAPER).json()["id"]  # download fails -> no stored PDF
    assert client.delete(f"/api/papers/{pid}").json() == {"ok": True}
    assert client.get(f"/api/papers/{pid}").status_code == 404


def test_delete_paper_whose_pdf_file_is_already_gone(client):
    pid = seed_paper()  # pdf_path set but no file written
    assert client.delete(f"/api/papers/{pid}").json() == {"ok": True}


def test_delete_unknown_paper_returns_404(client):
    assert client.delete("/api/papers/999").status_code == 404


def test_delete_paper_twice_returns_404_second_time(client):
    pid = seed_paper()
    client.delete(f"/api/papers/{pid}")
    assert client.delete(f"/api/papers/{pid}").status_code == 404


# ---------- PDF upload (R12-R14) ----------

def test_upload_non_pdf_returns_400(client):
    assert upload(client, b"hello, not a pdf", "notes.txt").status_code == 400


def test_upload_empty_file_returns_400(client):
    assert upload(client, b"").status_code == 400


def test_upload_unparseable_pdf_returns_400(client):
    assert upload(client, b"%PDF-1.4 this is garbage").status_code == 400


def test_upload_scanned_pdf_without_text_returns_400(client):
    assert upload(client, make_pdf(["", ""])).status_code == 400


def test_upload_saves_paper_with_extracted_metadata(client, fake_llm):
    fake_llm(parsed=good_metadata())
    resp = upload(client, make_pdf(["Uploaded Title\nAda Lovelace"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Uploaded Title"
    assert body["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert body["year"] == "2021"
    assert body["abstract"] == "Uploaded abstract."
    assert body["source"] == "upload"
    assert body["has_full_text"] is True
    assert body["warning"] is None


def test_upload_stores_pdf_file(client, fake_llm):
    fake_llm(parsed=good_metadata())
    pdf = make_pdf(["Some text"])
    pid = upload(client, pdf).json()["id"]
    assert pdf_utils.pdf_path_for(pid).read_bytes() == pdf


def test_upload_stores_full_text_of_all_pages(client, fake_llm):
    fake_llm(parsed=good_metadata())
    pid = upload(client, make_pdf(["Page one", "Page two", "Page three"])).json()["id"]
    text = db.get_full_text(pid)
    assert "Page one" in text and "Page three" in text


def test_upload_metadata_uses_only_first_two_pages(client, monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "extract_metadata", lambda text: seen.append(text) or good_metadata().model_dump())
    upload(client, make_pdf(["Page one", "Page two", "Page three"]))
    assert "Page one" in seen[0] and "Page two" in seen[0]
    assert "Page three" not in seen[0]


def test_upload_metadata_text_capped_at_15000_chars(client, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "extract_pages", lambda data: ["A" * 10000, "B" * 10000, "C"])
    monkeypatch.setattr(llm, "extract_metadata", lambda text: seen.append(text) or good_metadata().model_dump())
    upload(client, b"%PDF-fake")
    assert len(seen[0]) == 15000
    assert seen[0].startswith("A" * 10000)


def test_upload_gemini_failure_falls_back_to_filename(client, fake_llm):
    fake_llm(error=FakeAPIError(429))
    resp = upload(client, make_pdf(["Some text"]), "my_paper.pdf")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "my_paper"
    assert body["authors"] == []
    assert body["year"] is None
    assert body["abstract"] is None
    assert body["has_full_text"] is True


def test_upload_gemini_failure_warning_explains_error(client, fake_llm):
    fake_llm(error=FakeAPIError(429))
    warning = upload(client, make_pdf(["Some text"])).json()["warning"]
    assert warning and BUSY in warning


def test_upload_missing_api_key_warning(client):
    warning = upload(client, make_pdf(["Some text"])).json()["warning"]
    assert warning and NO_KEY in warning


def test_upload_fallback_title_strips_only_last_extension(client, fake_llm):
    fake_llm(error=FakeAPIError(500))
    body = upload(client, make_pdf(["Some text"]), "my.paper.v2.pdf").json()
    assert body["title"] == "my.paper.v2"


# ---------- Summaries (R15-R17) ----------

def test_summarize_returns_llm_summary(client, fake_llm):
    fake_llm(text="A summary.")
    pid = seed_paper()
    resp = client.post(f"/api/papers/{pid}/summarize")
    assert resp.status_code == 200
    assert resp.json() == {"summary": "A summary."}


def test_summarize_caches_summary(client, fake_llm):
    fake_llm(text="A summary.")
    pid = seed_paper()
    client.post(f"/api/papers/{pid}/summarize")
    assert db.get_paper(pid)["summary"] == "A summary."


def test_summarize_returns_cached_without_calling_llm(client, fake_llm):
    models = fake_llm(text="NEW")
    pid = seed_paper(summary="CACHED")
    resp = client.post(f"/api/papers/{pid}/summarize", params={"regenerate": "false"})
    assert resp.json() == {"summary": "CACHED"}
    assert models.calls == []


def test_summarize_regenerate_calls_llm_and_replaces_cache(client, fake_llm):
    models = fake_llm(text="NEW")
    pid = seed_paper(summary="CACHED")
    resp = client.post(f"/api/papers/{pid}/summarize", params={"regenerate": "true"})
    assert resp.json() == {"summary": "NEW"}
    assert len(models.calls) == 1
    assert db.get_paper(pid)["summary"] == "NEW"


def test_summarize_uses_full_text_not_abstract(client, fake_llm):
    models = fake_llm()
    pid = seed_paper(full_text="FULLTEXT_BODY", abstract="ABSTRACT_ONLY")
    client.post(f"/api/papers/{pid}/summarize")
    prompt = models.calls[0]["contents"]
    assert "FULLTEXT_BODY" in prompt
    assert "ABSTRACT_ONLY" not in prompt


def test_summarize_full_text_capped_at_400000_chars(client, fake_llm):
    models = fake_llm()
    pid = seed_paper(full_text="A" * 400_000 + "TAILMARKER")
    client.post(f"/api/papers/{pid}/summarize")
    prompt = models.calls[0]["contents"]
    assert "A" * 400_000 in prompt
    assert "TAILMARKER" not in prompt


def test_summarize_unknown_paper_returns_404(client):
    assert client.post("/api/papers/999/summarize").status_code == 404


def test_summarize_paper_without_full_text_returns_400(client, fake_llm):
    models = fake_llm()
    pid = seed_paper(full_text=None)
    assert client.post(f"/api/papers/{pid}/summarize").status_code == 400
    assert models.calls == []


def test_summarize_llm_failure_returns_502_with_friendly_message(client, fake_llm):
    fake_llm(error=FakeAPIError(503))
    pid = seed_paper()
    resp = client.post(f"/api/papers/{pid}/summarize")
    assert resp.status_code == 502
    assert resp.json()["detail"] == BUSY


def test_summarize_llm_failure_caches_nothing(client, fake_llm):
    fake_llm(error=FakeAPIError(503))
    pid = seed_paper()
    client.post(f"/api/papers/{pid}/summarize")
    assert db.get_paper(pid)["summary"] is None


def test_summarize_regenerate_failure_keeps_previous_summary(client, fake_llm):
    fake_llm(error=FakeAPIError(503))
    pid = seed_paper(summary="OLD")
    client.post(f"/api/papers/{pid}/summarize", params={"regenerate": "true"})
    assert db.get_paper(pid)["summary"] == "OLD"


def test_summarize_missing_api_key_returns_502(client):
    pid = seed_paper()
    resp = client.post(f"/api/papers/{pid}/summarize")
    assert resp.status_code == 502
    assert resp.json()["detail"] == NO_KEY


# ---------- Q&A (R18-R21) ----------

def test_ask_returns_question_and_answer(client, fake_llm):
    fake_llm(text="It uses WMT.")
    pid = seed_paper()
    resp = client.post(f"/api/papers/{pid}/ask", json={"question": "Which dataset?"})
    assert resp.status_code == 200
    assert resp.json() == {"question": "Which dataset?", "answer": "It uses WMT."}


def test_ask_saves_turn_to_history(client, fake_llm):
    fake_llm(text="It uses WMT.")
    pid = seed_paper()
    client.post(f"/api/papers/{pid}/ask", json={"question": "Which dataset?"})
    history = client.get(f"/api/papers/{pid}/qa").json()
    assert [(h["question"], h["answer"]) for h in history] == [("Which dataset?", "It uses WMT.")]


def test_ask_strips_question_whitespace(client, fake_llm):
    models = fake_llm()
    pid = seed_paper()
    resp = client.post(f"/api/papers/{pid}/ask", json={"question": "  Why?\n "})
    assert resp.json()["question"] == "Why?"
    assert models.calls[0]["contents"][-1].parts[0].text == "Why?"
    assert db.list_qa(pid)[0]["question"] == "Why?"


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_ask_empty_question_returns_400(client, fake_llm, question):
    models = fake_llm()
    pid = seed_paper()
    resp = client.post(f"/api/papers/{pid}/ask", json={"question": question})
    assert resp.status_code == 400
    assert models.calls == []


def test_ask_unknown_paper_returns_404(client):
    assert client.post("/api/papers/999/ask", json={"question": "Why?"}).status_code == 404


def test_ask_paper_without_full_text_returns_400(client, fake_llm):
    fake_llm()
    pid = seed_paper(full_text=None)
    assert client.post(f"/api/papers/{pid}/ask", json={"question": "Why?"}).status_code == 400


def test_ask_llm_failure_returns_502_and_saves_nothing(client, fake_llm):
    fake_llm(error=FakeAPIError(401))
    pid = seed_paper()
    resp = client.post(f"/api/papers/{pid}/ask", json={"question": "Why?"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == BAD_KEY
    assert db.list_qa(pid) == []


def test_ask_puts_full_text_in_system_instruction(client, fake_llm):
    models = fake_llm()
    pid = seed_paper(full_text="FULLTEXT_BODY")
    client.post(f"/api/papers/{pid}/ask", json={"question": "Why?"})
    assert "FULLTEXT_BODY" in models.calls[0]["config"].system_instruction


def test_ask_full_text_capped_at_400000_chars(client, fake_llm):
    models = fake_llm()
    pid = seed_paper(full_text="A" * 400_000 + "TAILMARKER")
    client.post(f"/api/papers/{pid}/ask", json={"question": "Why?"})
    instruction = models.calls[0]["config"].system_instruction
    assert "A" * 400_000 in instruction
    assert "TAILMARKER" not in instruction


def test_ask_without_history_sends_only_question(client, fake_llm):
    models = fake_llm()
    pid = seed_paper()
    client.post(f"/api/papers/{pid}/ask", json={"question": "Why?"})
    contents = models.calls[0]["contents"]
    assert [(c.role, c.parts[0].text) for c in contents] == [("user", "Why?")]


def test_ask_sends_only_last_five_turns_oldest_first(client, fake_llm):
    models = fake_llm()
    pid = seed_paper()
    for i in range(1, 8):
        db.add_qa(pid, f"Q{i}", f"A{i}")
    client.post(f"/api/papers/{pid}/ask", json={"question": "NEW"})
    contents = models.calls[0]["contents"]
    expected = []
    for i in range(3, 8):
        expected += [("user", f"Q{i}"), ("model", f"A{i}")]
    expected.append(("user", "NEW"))
    assert [(c.role, c.parts[0].text) for c in contents] == expected


def test_qa_history_in_order_asked(client, fake_llm):
    fake_llm(text="ans")
    pid = seed_paper()
    for q in ("first?", "second?", "third?"):
        client.post(f"/api/papers/{pid}/ask", json={"question": q})
    history = client.get(f"/api/papers/{pid}/qa").json()
    assert [h["question"] for h in history] == ["first?", "second?", "third?"]


def test_qa_history_empty_for_new_paper(client):
    pid = seed_paper()
    assert client.get(f"/api/papers/{pid}/qa").json() == []


def test_qa_history_unknown_paper_returns_404(client):
    assert client.get("/api/papers/999/qa").status_code == 404


# ---------- DB connection handling ----------

@pytest.fixture
def tracked_connections(monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", tracking_connect)
    return opened


def is_closed(conn):
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def test_db_connections_closed_after_requests(client, tracked_connections, fake_llm):
    fake_llm(text="ans")
    pid = client.post("/api/papers", json=ARXIV_PAPER).json()["id"]
    db.set_full_text(pid, pdf_utils.pdf_path_for(pid), "text")
    client.get("/api/papers")
    client.post(f"/api/papers/{pid}/ask", json={"question": "Why?"})
    client.delete(f"/api/papers/{pid}")
    assert tracked_connections
    assert all(is_closed(c) for c in tracked_connections)


def test_db_connection_closed_when_block_raises(client, tracked_connections):
    with pytest.raises(ZeroDivisionError):
        with db.connect():
            1 / 0
    assert is_closed(tracked_connections[0])


def test_db_write_rolled_back_when_block_raises(client):
    with pytest.raises(ZeroDivisionError):
        with db.connect() as conn:
            conn.execute("INSERT INTO papers (title, authors, source) VALUES ('t', '[]', 'arxiv')")
            1 / 0
    assert db.list_papers() == []


# ---------- LLM errors (R22) ----------

@pytest.mark.parametrize("code,expected", [
    (429, BUSY),
    (503, BUSY),
    (401, BAD_KEY),
    (403, BAD_KEY),
])
def test_friendly_error_known_status_codes(code, expected):
    assert llm.friendly_error(FakeAPIError(code)) == expected


def test_friendly_error_other_status_code_is_generic():
    assert llm.friendly_error(FakeAPIError(500, "server exploded")) == "LLM request failed: server exploded"


def test_friendly_error_exception_without_code_is_generic():
    assert llm.friendly_error(ValueError("bad json")) == "LLM request failed: bad json"


def test_friendly_error_unrelated_runtime_error_is_generic():
    assert llm.friendly_error(RuntimeError("event loop closed")) == "LLM request failed: event loop closed"


def test_client_without_api_key_raises_with_message():
    with pytest.raises(RuntimeError) as exc:
        llm.client()
    assert llm.friendly_error(exc.value) == NO_KEY


@pytest.fixture
def fake_genai_client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    created = []
    monkeypatch.setattr(llm.genai, "Client", lambda **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))
    return created


def test_client_uses_api_key_and_retries(fake_genai_client):
    llm.client()
    kwargs = fake_genai_client[0]
    assert kwargs["api_key"] == "test-key"
    assert kwargs["http_options"].retry_options.attempts == 4


def test_client_is_created_once_and_reused(fake_genai_client):
    assert llm.client() is llm.client()
    assert len(fake_genai_client) == 1
