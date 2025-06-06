import os
import subprocess
import time
from datetime import datetime
from difflib import SequenceMatcher
import re
import sys
from docx import Document

PRIMARY_MODEL = "mistral:7b-instruct"
FALLBACK_MODEL = "codellama:13b-instruct-q4_K_M"
CHUNK_SIZE = 90
CHUNK_OVERLAP = 30
TIMEOUT = 120
DEBUG = True
INCLUDE_AP200 = False
TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"
FUZZY_THRESHOLD = 0.94
MODULE_NAME = "AP"


def read_lines(path):
    with open(path, "r") as f:
        return [line.rstrip("\n") for line in f.readlines()]

def chunk_lines(lines, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    step = size - overlap
    return ['\n'.join(lines[i:i+size]) for i in range(0, len(lines), step)]

def build_prompt(template, chunk, context=None, program="160"):
    context_block = f"\nContext code from AP200 (reference only):\n{context}\n" if context else ""
    return f"""{template}

You are analyzing **IBM RPG code from AP{program}** (Accounts Payable system). Your job is to extract only the business logic in a structured use case format. Focus on:
- AP vouchers, vendor validation, invoice rules, GL, payments, and 1099 logic.
- Skip implementation detail and low-level RPG structure.

DO NOT return summaries or commentary. Follow the format strictly.
{context_block}
[RPG CODE]
{chunk}
[END CODE]
"""

def run_ollama(model, prompt):
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=prompt.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT
        )
        return result.stdout.decode().strip()
    except subprocess.TimeoutExpired:
        return None

def normalize_headers(text, program):
    replacements = {
        "## Input Validation": "## Input Type Validation Checks",
        "## Validation Rules": "## Input Type Validation Checks",
        "## Entities Used": "## Entities Used / Tables Used",
        "## Tables Used": "## Entities Used / Tables Used"
    }
    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    text = re.sub(r"(\*\*Use Case ID\*\*:\s*UC-AP-)(\d+)", rf"\1AP{program}-\2", text)
    return text

def is_valid_output(text):
    return any(k in text for k in ["Use Case ID", "## Identification", "## Description"])

def format_narrative(text):
    sections = ["Identification", "Description", "Pre-Condition", "Post-Condition",
                "Entities Used / Tables Used", "Program Steps", "Tests Needed"]
    out = ["Use Case Template\n"]
    for sec in sections:
        match = re.search(f"##+\s+{re.escape(sec)}(.*?)((?=## )|\Z)", text, re.DOTALL | re.IGNORECASE)
        if match:
            out.append(f"### {sec}\n")
            out.append(match.group(1).strip() + "\n")
    return '\n'.join(out)

def fuzzy_dedupe(results):
    seen, unique = [], []
    for r in results:
        if not any(SequenceMatcher(None, r, s).ratio() > FUZZY_THRESHOLD for s in seen):
            seen.append(r)
            unique.append(r)
    return unique

def extract_title(text, program):
    match_id = re.search(r"Use Case ID.*?UC-AP-[^\n]*", text, re.IGNORECASE)
    id_part = match_id.group(0).strip().split()[-1].replace("UC-", "") if match_id else "XXX"
    match_title = re.search(r"(?i)^#\s*(.*?)\n", text)
    title = match_title.group(1).strip() if match_title else "Untitled"
    title_clean = re.sub(r'[^a-zA-Z0-9\- ]+', '', title).replace(' ', '-').strip('-')
    return re.sub(r'-+', '-', f"UC-{MODULE_NAME}-{program}-{id_part}-{title_clean}"[:80])

def save_as_docx(content, path):
    doc = Document()
    for para in content.splitlines():
        doc.add_paragraph(para)
    doc.save(path)

def process_chunk(i, chunk, template, ap200_context, outdir, logdir, rawfile, docx_dir, program):
    prompt = build_prompt(template, chunk, ap200_context if INCLUDE_AP200 else None, program)
    result = run_ollama(PRIMARY_MODEL, prompt) or run_ollama(FALLBACK_MODEL, prompt)

    if result:
        result = normalize_headers(result, program)
        if DEBUG:
            print(f"\n🧾 Chunk {i+1} Preview:\n" + "\n".join(result.splitlines()[:10]) + "\n...")

        with open(rawfile, "a") as rf:
            rf.write(f"\n\n# Chunk {i+1}\n\n{result}\n\n{'='*60}\n")

        if is_valid_output(result):
            filename_base = extract_title(result, program)
            md_path = os.path.join(outdir, f"{filename_base}.md")
            docx_path = os.path.join(docx_dir, f"{filename_base}.docx")
            try:
                with open(md_path, "w") as f:
                    f.write(result + "\n")
                save_as_docx(result, docx_path)
                print(f"✅ Chunk {i+1}: saved as {filename_base}.")
                return result
            except OSError as e:
                print(f"❌ Failed to write {filename_base}: {e}")
        else:
            with open(os.path.join(logdir, f"failed_chunk_{i+1:02d}.txt"), "w") as f:
                f.write(result)
            print(f"❌ Chunk {i+1}: structure failed.")
    else:
        print(f"❌ Chunk {i+1}: no output.")
    return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Please provide a primary RPG file path (e.g., AP160.rpg36.txt)")
        sys.exit(1)

    PRIMARY_FILE = sys.argv[1]
    PROGRAM_NAME = re.findall(r"AP(\d+)", os.path.basename(PRIMARY_FILE).upper())[0] if "AP" in PRIMARY_FILE.upper() else "XXX"

    ap160 = read_lines(PRIMARY_FILE)
    ap200 = read_lines("C:\\Temp\\IBM-GitHub-Submission-Unedited\\IBM-GitHub-Submission\\QSRC\\AP200.rpg36.txt")[:40] if INCLUDE_AP200 else []
    template = open(TEMPLATE_FILE, "r").read()
    chunks = chunk_lines(ap160)

    now = datetime.now()
    date_folder = os.path.join(OUTPUT_BASE, f"usecases-{now.strftime('%Y-%m-%d')}")
    ts = now.strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(date_folder, f"ap{PROGRAM_NAME}_{ts}")
    logdir = os.path.join("logs", f"logs_{ts}")
    docxdir = os.path.join(outdir, "word_docs")
    rawfile = os.path.join(outdir, "RAW_OLLAMA_OUTPUT.md")
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(logdir, exist_ok=True)
    os.makedirs(docxdir, exist_ok=True)

    all_results = []
    for i, chunk in enumerate(chunks):
        res = process_chunk(i, chunk, template, '\n'.join(ap200), outdir, logdir, rawfile, docxdir, PROGRAM_NAME)
        if res:
            all_results.append(res)

    final = fuzzy_dedupe(all_results)
    with open(os.path.join(outdir, "SUMMARY.md"), "w") as f:
        for uc in final:
            f.write(format_narrative(uc) + "\n\n" + "="*60 + "\n\n")

    print(f"\n✅ {len(final)} unique use cases saved to {outdir}")
