import os
import io
import re
import pdfplumber
import openai
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from typing import List
from dotenv import load_dotenv

# Load API key
load_dotenv(os.path.expanduser("~/.env"))
client = openai.OpenAI()

# GPT function
def get_response_to_prompt(prompt, model="gpt-4o"):
    return client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    ).choices[0].message.content

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def form():
    return """
    <html>
        <head><title>Upload Legal Invoices</title></head>
        <body style="font-family: 'Times New Roman', serif;">
            <h2>Upload One or More Legal Invoices (PDF or TXT)</h2>
            <form action="/analyze" enctype="multipart/form-data" method="post">
                <input name="invoices" type="file" accept=".txt,.pdf" multiple required>
                <button type="submit">Analyze</button>
            </form>
        </body>
    </html>
    """

# HTML formatting helper
def format_output_with_themes(text: str) -> str:
    lines = text.strip().split("\n")
    html = []
    current_heading = None
    bullets = []

    def flush_heading():
        nonlocal html, current_heading, bullets
        if current_heading:
            html.append(f"<h3>{current_heading}</h3>")
            if bullets:
                html.append("<ul>")
                for b in bullets:
                    html.append(f"<li>{b}</li>")
                html.append("</ul>")
        current_heading = None
        bullets = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.isupper() or line.endswith(":"):
            flush_heading()
            current_heading = line.rstrip(":")
        elif re.match(r"^[-•*]\s+", line) or re.match(r"^\d+\.", line):
            item = re.sub(r"^[-•*]|\d+\.", "", line).strip()
            bullets.append(item)
        else:
            if current_heading:
                bullets.append(line)
            else:
                html.append(f"<p>{line}</p>")

    flush_heading()
    return "\n".join(html)

# Support multiple invoice files
@app.post("/analyze", response_class=HTMLResponse)
async def analyze(invoices: List[UploadFile] = File(...)):
    results = []

    for invoice in invoices:
        file_ext = invoice.filename.lower().split('.')[-1]
        content = await invoice.read()
        text = ""

        if file_ext == "txt":
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                results.append(f"<h3>{invoice.filename}</h3><p style='color:red;'>Could not decode text file.</p>")
                continue
        elif file_ext == "pdf":
            try:
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    pages = [page.extract_text() for page in pdf.pages if page.extract_text()]
                    text = "\n".join(pages)
            except Exception as e:
                results.append(f"<h3>{invoice.filename}</h3><p style='color:red;'>Failed to read PDF: {e}</p>")
                continue
        else:
            results.append(f"<h3>{invoice.filename}</h3><p style='color:red;'>Unsupported file type.</p>")
            continue

        if not text.strip():
            results.append(f"<h3>{invoice.filename}</h3><p style='color:red;'>No text found.</p>")
            continue

        # Construct prompt
        prompt = f"""You are an experienced general counsel concerned about high costs from your outside legal vendors. Please review the invoices and flag inefficiency and vagueness with a view towards tasks taking too long or descriptions not being sufficiently specific

--- INVOICE START ---
{text}
--- INVOICE END ---
"""

        try:
            evaluation = get_response_to_prompt(prompt)
            formatted = format_output_with_themes(evaluation)
            results.append(f"<h2>Invoice: {invoice.filename}</h2>{formatted}")
        except Exception as e:
            results.append(f"<h3>{invoice.filename}</h3><p style='color:red;'>Error analyzing invoice: {e}</p>")

    all_output = "\n".join(results)

    return f"""
    <html>
        <head><title>Invoice Evaluations</title></head>
        <body style="font-family: 'Times New Roman', serif;">
            <h1>Invoice Evaluations</h1>
            {all_output}
            <br><a href="/">Upload More</a>
        </body>
    </html>
    """
