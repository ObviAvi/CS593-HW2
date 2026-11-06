import xml.etree.ElementTree as ET

import httpx

ARXIV_URL = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}


def _clean(text):
    return " ".join((text or "").split())


def search_arxiv(query, max_results=10):
    # every keyword must appear somewhere in the paper (title, abstract, authors, ...)
    terms = " AND ".join(f"all:{word}" for word in query.split())
    params = {
        "search_query": terms,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
    }
    resp = httpx.get(ARXIV_URL, params=params, timeout=20, follow_redirects=True)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    results = []
    for entry in root.findall("a:entry", NS):
        pdf_url = None
        for link in entry.findall("a:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
        results.append({
            "title": _clean(entry.findtext("a:title", namespaces=NS)),
            "authors": [_clean(a.findtext("a:name", namespaces=NS)) for a in entry.findall("a:author", NS)],
            "year": (entry.findtext("a:published", namespaces=NS) or "")[:4],
            "abstract": _clean(entry.findtext("a:summary", namespaces=NS)),
            "url": entry.findtext("a:id", namespaces=NS),
            "pdf_url": pdf_url,
        })
    return results
