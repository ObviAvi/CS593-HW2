from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db, llm
from app.pdf_utils import download_pdf, extract_pages, pdf_path_for
from app.search import search_arxiv

app = FastAPI()
db.init_db()


class PaperIn(BaseModel):
    title: str
    authors: list[str]
    year: str | None = None
    abstract: str | None = None
    url: str | None = None
    pdf_url: str | None = None


class QuestionIn(BaseModel):
    question: str


@app.get("/api/search")
def search(q: str):
    if not q.strip():
        raise HTTPException(400, "Empty query")
    try:
        return search_arxiv(q)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"arXiv request failed: {e}")


@app.post("/api/papers")
def save_paper(paper: PaperIn):
    paper_id = db.add_paper(paper.model_dump(), source="arxiv")
    saved = db.get_paper(paper_id)
    # the paper stays saved even if the PDF can't be fetched; has_full_text tells the UI
    if not saved["has_full_text"] and paper.pdf_url:
        path = pdf_path_for(paper_id)
        try:
            data = download_pdf(paper.pdf_url)
            # extract before writing so a corrupt PDF never leaves an untracked file on disk
            full_text = "\n".join(extract_pages(data)).strip()
            path.write_bytes(data)
            db.set_full_text(paper_id, path, full_text)
        except Exception as e:
            print(f"Could not get full text for paper {paper_id}: {e}")
        saved = db.get_paper(paper_id)
    return saved


@app.post("/api/papers/upload")
async def upload_paper(file: UploadFile):
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "File is not a PDF")
    try:
        pages = extract_pages(data)
    except Exception as e:
        raise HTTPException(400, f"Could not read PDF: {e}")
    full_text = "\n".join(pages).strip()
    if not full_text:
        raise HTTPException(400, "No text found in PDF (it may be a scanned image)")

    warning = None
    try:
        meta = llm.extract_metadata("\n".join(pages[:2])[:15000])
    except Exception as e:
        print(f"Metadata extraction failed for {file.filename}: {e}")
        warning = f"{llm.friendly_error(e)} Saved with the file name as its title."
        meta = {"title": Path(file.filename or "Untitled").stem, "authors": [], "year": None, "abstract": None}

    paper_id = db.add_paper(meta, source="upload")
    path = pdf_path_for(paper_id)
    path.write_bytes(data)
    db.set_full_text(paper_id, path, full_text)
    return {**db.get_paper(paper_id), "warning": warning}


@app.get("/api/papers")
def list_papers():
    return db.list_papers()


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: int):
    paper = db.get_paper(paper_id)
    if not paper:
        raise HTTPException(404, "Paper not found")
    return paper


@app.post("/api/papers/{paper_id}/summarize")
def summarize_paper(paper_id: int, regenerate: bool = False):
    paper = db.get_paper(paper_id)
    if not paper:
        raise HTTPException(404, "Paper not found")
    if paper["summary"] and not regenerate:
        return {"summary": paper["summary"]}
    full_text = db.get_full_text(paper_id)
    if not full_text:
        raise HTTPException(400, "This paper has no full text to summarize")
    try:
        summary = llm.summarize(full_text)
    except Exception as e:
        raise HTTPException(502, llm.friendly_error(e))
    db.set_summary(paper_id, summary)
    return {"summary": summary}


@app.get("/api/papers/{paper_id}/qa")
def list_qa(paper_id: int):
    if not db.get_paper(paper_id):
        raise HTTPException(404, "Paper not found")
    return db.list_qa(paper_id)


@app.post("/api/papers/{paper_id}/ask")
def ask_question(paper_id: int, body: QuestionIn):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Empty question")
    if not db.get_paper(paper_id):
        raise HTTPException(404, "Paper not found")
    full_text = db.get_full_text(paper_id)
    if not full_text:
        raise HTTPException(400, "This paper has no full text to ask about")
    try:
        answer = llm.answer(full_text, question, db.list_qa(paper_id))
    except Exception as e:
        raise HTTPException(502, llm.friendly_error(e))
    db.add_qa(paper_id, question, answer)
    return {"question": question, "answer": answer}


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: int):
    pdf_path = db.delete_paper(paper_id)
    if pdf_path is False:
        raise HTTPException(404, "Paper not found")
    if pdf_path:
        Path(pdf_path).unlink(missing_ok=True)
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
