import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv(".env")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

_client = None


class MissingAPIKeyError(RuntimeError):
    pass


def client():
    global _client
    if _client is None:
        if not os.environ.get("GEMINI_API_KEY"):
            raise MissingAPIKeyError("GEMINI_API_KEY is not set. Add it to the .env file and restart the server.")
        # retry 429/5xx ("model overloaded") with backoff; the SDK default is no retries
        retry = types.HttpRetryOptions(attempts=4, max_delay=10)
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                               http_options=types.HttpOptions(retry_options=retry))
    return _client


def friendly_error(e):
    """Short user-facing message for an LLM failure."""
    code = getattr(e, "code", None)
    if code in (429, 503):
        return "The Gemini model is busy or rate-limited right now. Try again in a minute."
    if code in (401, 403):
        return "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
    if isinstance(e, MissingAPIKeyError):
        return str(e)
    return f"LLM request failed: {e}"


class PaperMetadata(BaseModel):
    title: str
    authors: list[str]
    year: str | None
    abstract: str | None


METADATA_PROMPT = """Below is text extracted from the first pages of a research paper PDF.
Extract the paper's title, author names, publication year, and abstract.
Copy the title and abstract as written in the paper. If the year is not stated, use null.

{text}"""


def extract_metadata(first_pages_text):
    resp = client().models.generate_content(
        model=MODEL,
        contents=METADATA_PROMPT.format(text=first_pages_text),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PaperMetadata,
        ),
    )
    return resp.parsed.model_dump()


# well under the model's context window; typical papers are 30k-100k chars
MAX_PAPER_CHARS = 400_000

# the frontend renders Markdown but not LaTeX
MATH_RULE = "Write any math in plain text with Unicode symbols (e.g. O(n²·d), √dₖ); do not use LaTeX or $ delimiters."

SUMMARY_PROMPT = """You are helping a researcher understand a paper. Using the full paper text below,
write a summary in Markdown with these sections:
- **Problem**: what problem the paper addresses and why it matters
- **Approach**: the main idea and how the method works
- **Experiments**: datasets, baselines, and key quantitative results
- **Limitations**: weaknesses or open questions (stated by the authors or evident from the paper)

Be specific: name the actual methods, datasets, and numbers from the paper. Keep it under 400 words.
{math_rule}

Paper text:
{text}"""


def summarize(full_text):
    resp = client().models.generate_content(
        model=MODEL,
        contents=SUMMARY_PROMPT.format(text=full_text[:MAX_PAPER_CHARS], math_rule=MATH_RULE),
    )
    return resp.text


QA_INSTRUCTION = """You answer questions about one research paper, whose full text is below.
Base your answers on the paper. Quote or cite specific sections, numbers, and names where helpful.
If the paper does not contain the answer, say so instead of guessing; you may add general
background knowledge only if you clearly label it as not coming from the paper.
Answer in Markdown and keep answers concise.
{math_rule}

Paper text:
{text}"""

# earlier Q&A turns sent with each question so follow-ups like "why?" make sense
QA_HISTORY_TURNS = 5


def answer(full_text, question, history):
    contents = []
    for qa in history[-QA_HISTORY_TURNS:]:
        contents.append(types.Content(role="user", parts=[types.Part(text=qa["question"])]))
        contents.append(types.Content(role="model", parts=[types.Part(text=qa["answer"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
    resp = client().models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=QA_INSTRUCTION.format(text=full_text[:MAX_PAPER_CHARS], math_rule=MATH_RULE),
        ),
    )
    return resp.text
