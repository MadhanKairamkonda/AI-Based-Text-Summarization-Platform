from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from pdfminer.high_level import extract_text
from groq import Groq
from dotenv import load_dotenv

# ================== CONFIG ==================
# Load .env from the same folder as main.py  ← single, reliable path
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("GROQ_API_KEY is not set. Add it to your .env file.")

client = Groq(api_key=groq_api_key)

app = FastAPI(
    title="AI Text Summarizer",
    description="Summarize text or PDF files using AI",
    version="1.0.0"
)

# ================== CORS ==================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================== UTILS ==================

def split_text(text: str, size: int = 1500) -> list:
    """Split text into chunks of specified size."""
    return [text[i:i + size] for i in range(0, len(text), size)]


def clean_text(text: str) -> str:
    """Remove extra whitespace from text."""
    return " ".join(text.split())


def generate_summary(text: str) -> str:
    """Generate a summary using Groq free LLaMA3 model."""
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful summarizer. "
                    "Provide clear and concise summaries that capture the key points."
                ),
            },
            {
                "role": "user",
                "content": f"Summarize this text:\n{text}",
            },
        ],
        temperature=0.5,
        max_tokens=512,
    )
    return response.choices[0].message.content


# ================== ROUTES ==================

@app.get("/")
def home():
    return {
        "message": "AI Text Summarizer is running",
        "endpoints": {
            "summarize": "POST /summarize",
            "docs":      "GET  /docs",
        },
    }


@app.post("/summarize")
async def summarize(
    text: str = Form(None),
    file: UploadFile = File(None),
):
    """
    Summarize either uploaded PDF or plain text.

    - **text** : Plain text string to summarize
    - **file** : PDF file to extract and summarize

    Returns { "summary": str }
    """

    final_text = ""

    # ── Case 1: PDF Upload ───────────────────────────────────────
    if file and file.filename:

        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are supported.",
            )

        with NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            final_text = extract_text(tmp_path)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to extract PDF text: {e}",
            )
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ── Case 2: Plain Text ───────────────────────────────────────
    elif text:
        final_text = text

    # ── Case 3: Nothing provided ─────────────────────────────────
    else:
        raise HTTPException(
            status_code=400,
            detail="No input provided. Send either 'text' or upload a PDF 'file'.",
        )

    # ── Clean & validate ─────────────────────────────────────────
    final_text = clean_text(final_text)

    if not final_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No readable content found in the input.",
        )

    # ── Summarise ────────────────────────────────────────────────
    chunks = split_text(final_text, size=1500)

    try:
        if len(chunks) == 1:
            # Short text — one direct API call
            final_summary = generate_summary(final_text)

        else:
            # Long text — summarise each chunk then merge all summaries
            chunk_summaries = []
            for i, chunk in enumerate(chunks):
                chunk_summaries.append(generate_summary(chunk))

            combined = " ".join(chunk_summaries)
            final_summary = generate_summary(
                f"Create one cohesive summary from these summaries:\n{combined}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"AI processing failed: {e}",
        )

    return {"summary": final_summary}


# ================== RUN ==================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)