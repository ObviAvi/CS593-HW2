from pathlib import Path

import httpx
import pymupdf

PDF_DIR = Path("data") / "pdfs"


def pdf_path_for(paper_id):
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    return PDF_DIR / f"{paper_id}.pdf"


def download_pdf(url):
    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise ValueError("Response is not a PDF")
    return resp.content


def extract_pages(data):
    """Text of each page of an in-memory PDF."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [page.get_text() for page in doc]
