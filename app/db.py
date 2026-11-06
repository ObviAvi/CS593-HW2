import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "papers.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    year TEXT,
    abstract TEXT,
    url TEXT UNIQUE,
    pdf_url TEXT,
    pdf_path TEXT,
    full_text TEXT,
    source TEXT NOT NULL,
    summary TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS qa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# full_text is large, so list views leave it out
LIST_COLUMNS = ("id, title, authors, year, abstract, url, pdf_url, source, summary, created_at, "
                "full_text IS NOT NULL AND full_text != '' AS has_full_text")


@contextmanager
def connect():
    """Commits on success, rolls back on error, always closes."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    DATA_DIR.mkdir(exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def _to_dict(row):
    paper = dict(row)
    paper["authors"] = json.loads(paper["authors"])
    paper["has_full_text"] = bool(paper["has_full_text"])
    return paper


def add_paper(paper, source):
    """Insert a paper; returns its id. If the url is already saved, returns the existing id."""
    with connect() as conn:
        if paper.get("url"):
            existing = conn.execute("SELECT id FROM papers WHERE url = ?", (paper["url"],)).fetchone()
            if existing:
                return existing["id"]
        cur = conn.execute(
            "INSERT INTO papers (title, authors, year, abstract, url, pdf_url, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (paper["title"], json.dumps(paper["authors"]), paper.get("year"), paper.get("abstract"),
             paper.get("url"), paper.get("pdf_url"), source),
        )
        return cur.lastrowid


def list_papers():
    with connect() as conn:
        rows = conn.execute(f"SELECT {LIST_COLUMNS} FROM papers ORDER BY created_at DESC, id DESC").fetchall()
    return [_to_dict(r) for r in rows]


def get_paper(paper_id):
    with connect() as conn:
        row = conn.execute(f"SELECT {LIST_COLUMNS} FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return _to_dict(row) if row else None


def set_full_text(paper_id, pdf_path, full_text):
    with connect() as conn:
        conn.execute("UPDATE papers SET pdf_path = ?, full_text = ? WHERE id = ?",
                     (str(pdf_path), full_text, paper_id))


def delete_paper(paper_id):
    """Delete a paper; returns its pdf_path (may be None), or False if it didn't exist."""
    with connect() as conn:
        row = conn.execute("SELECT pdf_path FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        conn.execute("DELETE FROM qa WHERE paper_id = ?", (paper_id,))
    return row["pdf_path"]


def get_full_text(paper_id):
    with connect() as conn:
        row = conn.execute("SELECT full_text FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return row["full_text"] if row else None


def set_summary(paper_id, summary):
    with connect() as conn:
        conn.execute("UPDATE papers SET summary = ? WHERE id = ?", (summary, paper_id))


def list_qa(paper_id):
    with connect() as conn:
        rows = conn.execute("SELECT id, question, answer, created_at FROM qa WHERE paper_id = ? ORDER BY id",
                            (paper_id,)).fetchall()
    return [dict(r) for r in rows]


def add_qa(paper_id, question, answer):
    with connect() as conn:
        conn.execute("INSERT INTO qa (paper_id, question, answer) VALUES (?, ?, ?)", (paper_id, question, answer))
