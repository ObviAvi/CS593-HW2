const $ = (id) => document.getElementById(id);

const SUGGESTED_QUESTIONS = [
  "What problem does this paper address?",
  "What is the main idea of the proposed approach?",
  "What datasets are used?",
  "What are the major limitations?",
  "How does this method compare with the baselines?",
];

let searchResults = [];
let currentPaper = null;

// helpers

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s ?? "";
  return div.innerHTML;
}

function renderMarkdown(md) {
  return DOMPurify.sanitize(marked.parse(md));
}

async function api(path, options) {
  let resp;
  try {
    resp = await fetch(path, options);
  } catch {
    throw new Error("Can't reach the server. Check that it's running.");
  }
  let data = null;
  try {
    data = await resp.json();
  } catch {
    // non-JSON body, e.g. a proxy error page
  }
  if (!resp.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${resp.status})`);
  }
  return data;
}

function setBusy(btn, busy, label) {
  btn.disabled = busy;
  btn.classList.toggle("busy", busy);
  if (label) btn.textContent = label;
}

function setStatus(el, text, isError = false) {
  el.textContent = text;
  el.classList.toggle("error", isError);
}

let toastTimer;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 4000);
}

function formatAuthors(authors) {
  if (!authors.length) return "Unknown authors";
  if (authors.length <= 6) return authors.join(", ");
  return `${authors.slice(0, 6).join(", ")} and ${authors.length - 6} more`;
}

function linksHtml(p) {
  const links = [];
  if (p.url) links.push(`<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">View on arXiv</a>`);
  if (p.pdf_url) links.push(`<a href="${escapeHtml(p.pdf_url)}" target="_blank" rel="noopener">PDF</a>`);
  return links.join("");
}

function pillsHtml(p) {
  const pills = [];
  if (p.year) pills.push(`<span class="pill">${escapeHtml(p.year)}</span>`);
  if (p.source === "arxiv") pills.push(`<span class="pill pill-arxiv">arXiv</span>`);
  if (p.source === "upload") pills.push(`<span class="pill pill-upload">Uploaded</span>`);
  if (p.id && !p.has_full_text) pills.push(`<span class="pill pill-warn">No full text</span>`);
  return pills.join("");
}

function paperCard(p, actions) {
  const abstract = p.abstract || "No abstract available.";
  const more = abstract.length > 320 ? `<button class="more" type="button">Show full abstract</button>` : "";
  return `
    <article class="paper">
      <div class="paper-top">${pillsHtml(p)}</div>
      <h2>${escapeHtml(p.title)}</h2>
      <p class="authors">${escapeHtml(formatAuthors(p.authors))}</p>
      <p class="abstract">${escapeHtml(abstract)}</p>
      ${more}
      <div class="paper-actions">${linksHtml(p)}<span class="spacer"></span>${actions}</div>
    </article>`;
}

function emptyHtml(title, text) {
  return `<div class="empty"><strong>${escapeHtml(title)}</strong>${escapeHtml(text)}</div>`;
}

// abstract expand/collapse, shared by every paper list
document.addEventListener("click", (e) => {
  const btn = e.target.closest("button.more");
  if (!btn) return;
  const abstract = btn.previousElementSibling;
  const expanded = abstract.classList.toggle("expanded");
  btn.textContent = expanded ? "Show less" : "Show full abstract";
});

// navigation

function showView(id) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== id));
  const navTarget = id === "detail-view" ? "library-view" : id;
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === navTarget));
  window.scrollTo(0, 0);
}

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    showView(item.dataset.view);
    if (item.dataset.view === "library-view") loadLibrary();
  });
});

function updateLibraryCount(n) {
  const badge = $("library-count");
  badge.textContent = n;
  badge.hidden = n === 0;
}

// search

$("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  const statusEl = $("status");
  setBusy(btn, true);
  setStatus(statusEl, "Searching arXiv...");
  $("results").innerHTML = "";
  try {
    const [results, library] = await Promise.all([
      api(`/api/search?q=${encodeURIComponent($("search-input").value)}`),
      api("/api/papers").catch(() => []),
    ]);
    searchResults = results;
    const savedUrls = new Set(library.map((p) => p.url));
    setStatus(statusEl, results.length ? `${results.length} results` : "");
    $("results").innerHTML = results.length
      ? results
          .map((p, i) => {
            const saved = savedUrls.has(p.url);
            return paperCard(
              p,
              `<button class="btn btn-dark btn-small save" data-index="${i}" ${saved ? "disabled" : ""}>
                ${saved ? "In your library" : "Save to library"}</button>`
            );
          })
          .join("")
      : emptyHtml("No papers found", "Try fewer or more general keywords.");
  } catch (err) {
    setStatus(statusEl, `Search failed: ${err.message}`, true);
  } finally {
    setBusy(btn, false);
  }
});

$("results").addEventListener("click", async (e) => {
  const btn = e.target.closest("button.save");
  if (!btn) return;
  setBusy(btn, true, "Saving");
  try {
    const paper = await api("/api/papers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(searchResults[btn.dataset.index]),
    });
    setBusy(btn, false, "In your library");
    btn.disabled = true;
    if (!paper.has_full_text) toast("Saved, but the PDF couldn't be downloaded, so summaries and Q&A won't work for it.");
    refreshLibraryCount();
  } catch (err) {
    setBusy(btn, false, "Save to library");
    toast(`Save failed: ${err.message}`);
  }
});

// library

async function refreshLibraryCount() {
  try {
    updateLibraryCount((await api("/api/papers")).length);
  } catch {
    // the badge is cosmetic; the library view shows real errors
  }
}

async function loadLibrary() {
  const statusEl = $("library-status");
  try {
    const papers = await api("/api/papers");
    updateLibraryCount(papers.length);
    setStatus(statusEl, papers.length === 1 ? "1 paper saved." : `${papers.length} papers saved.`);
    $("library").innerHTML = papers.length
      ? papers
          .map((p) =>
            paperCard(
              p,
              `<button class="btn btn-outline btn-small danger delete" data-id="${p.id}">Remove</button>
               <button class="btn btn-dark btn-small open" data-id="${p.id}">Open</button>`
            )
          )
          .join("")
      : emptyHtml("Your library is empty", "Search arXiv and save a paper, or upload a PDF from the sidebar.");
  } catch (err) {
    setStatus(statusEl, `Couldn't load your library: ${err.message}`, true);
  }
}

$("library").addEventListener("click", async (e) => {
  const openBtn = e.target.closest("button.open");
  if (openBtn) return openPaper(openBtn.dataset.id);
  const btn = e.target.closest("button.delete");
  if (!btn) return;
  setBusy(btn, true);
  try {
    await api(`/api/papers/${btn.dataset.id}`, { method: "DELETE" });
    loadLibrary();
  } catch (err) {
    setBusy(btn, false);
    toast(`Remove failed: ${err.message}`);
  }
});

// upload

$("upload-input").addEventListener("change", () => {
  const file = $("upload-input").files[0];
  $("upload-name").textContent = file ? file.name : "Choose a PDF";
});

$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const btn = form.querySelector("button");
  const statusEl = $("upload-status");
  const body = new FormData();
  body.append("file", $("upload-input").files[0]);
  setBusy(btn, true, "Reading PDF");
  setStatus(statusEl, "");
  try {
    const paper = await api("/api/papers/upload", { method: "POST", body });
    setStatus(statusEl, paper.warning || `Added "${paper.title}".`, Boolean(paper.warning));
    form.reset();
    $("upload-name").textContent = "Choose a PDF";
    if ($("library-view").hidden) refreshLibraryCount();
    else loadLibrary();
  } catch (err) {
    setStatus(statusEl, `Upload failed: ${err.message}`, true);
  } finally {
    setBusy(btn, false, "Upload PDF");
  }
});

// paper detail

function renderSummary(summary) {
  $("summary").innerHTML = summary ? renderMarkdown(summary) : "";
  $("summarize-btn").textContent = summary ? "Regenerate" : "Summarize";
}

function renderSuggestions(hasHistory) {
  $("qa-suggestions").innerHTML = hasHistory
    ? ""
    : SUGGESTED_QUESTIONS.map((q) => `<button type="button" class="suggestion">${escapeHtml(q)}</button>`).join("");
}

async function openPaper(id) {
  try {
    currentPaper = await api(`/api/papers/${id}`);
  } catch (err) {
    toast(`Couldn't open paper: ${err.message}`);
    return;
  }
  const p = currentPaper;
  $("detail-head").innerHTML = `
    <div class="paper-top">${pillsHtml(p)}</div>
    <h1>${escapeHtml(p.title)}</h1>
    <p class="authors">${escapeHtml(formatAuthors(p.authors))}</p>
    <div class="paper-actions">${linksHtml(p)}</div>`;
  $("detail-abstract").textContent = p.abstract || "No abstract available.";

  const canUseLlm = p.has_full_text;
  const noText = "This paper has no full text, so it can't be summarized or questioned.";
  setStatus($("summary-status"), canUseLlm ? (p.summary ? "" : "No summary yet.") : noText);
  $("summarize-btn").disabled = !canUseLlm;
  renderSummary(p.summary);

  $("ask-input").disabled = $("ask-form").querySelector("button").disabled = !canUseLlm;
  setStatus($("ask-status"), canUseLlm ? "" : noText);
  $("qa-list").innerHTML = "";
  renderSuggestions(true);
  showView("detail-view");

  if (canUseLlm) {
    try {
      const history = await api(`/api/papers/${id}/qa`);
      history.forEach(appendQa);
      renderSuggestions(history.length > 0);
    } catch (err) {
      setStatus($("ask-status"), `Couldn't load earlier questions: ${err.message}`, true);
    }
  }
}

$("back-btn").addEventListener("click", () => {
  showView("library-view");
  loadLibrary();
});

$("summarize-btn").addEventListener("click", async () => {
  const btn = $("summarize-btn");
  const paperId = currentPaper.id;
  const regenerate = Boolean(currentPaper.summary);
  setBusy(btn, true, regenerate ? "Regenerating" : "Summarizing");
  setStatus($("summary-status"), "Reading the full paper. This usually takes 5-15 seconds.");
  try {
    const { summary } = await api(`/api/papers/${paperId}/summarize?regenerate=${regenerate}`, { method: "POST" });
    if (currentPaper.id !== paperId) return;
    currentPaper.summary = summary;
    setStatus($("summary-status"), "");
    renderSummary(summary);
  } catch (err) {
    setStatus($("summary-status"), `Summary failed: ${err.message}`, true);
    renderSummary(currentPaper.summary);
  } finally {
    btn.disabled = false;
    btn.classList.remove("busy");
  }
});

// Q&A

function appendQa({ question, answer }) {
  const list = $("qa-list");
  list.insertAdjacentHTML(
    "beforeend",
    `<div class="qa">
      <p class="question">${escapeHtml(question)}</p>
      <div class="answer markdown">${renderMarkdown(answer)}</div>
    </div>`
  );
  list.scrollTop = list.scrollHeight;
}

async function ask(question) {
  const btn = $("ask-form").querySelector("button");
  const paperId = currentPaper.id;
  setBusy(btn, true);
  setStatus($("ask-status"), "Reading the paper to answer...");
  try {
    const qa = await api(`/api/papers/${paperId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    // ignore the answer if the user switched papers while waiting
    if (currentPaper.id !== paperId) return;
    appendQa(qa);
    renderSuggestions(true);
    $("ask-form").reset();
    setStatus($("ask-status"), "");
  } catch (err) {
    setStatus($("ask-status"), `Question failed: ${err.message}`, true);
  } finally {
    setBusy(btn, false);
  }
}

$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  ask($("ask-input").value);
});

$("qa-suggestions").addEventListener("click", (e) => {
  const btn = e.target.closest("button.suggestion");
  if (!btn || $("ask-form").querySelector("button").disabled) return;
  $("ask-input").value = btn.textContent;
  ask(btn.textContent);
});

refreshLibraryCount();
