import os
import subprocess
import time
from datetime import datetime
from difflib import SequenceMatcher
import re

PRIMARY_MODEL = "mistral:7b-instruct"
FALLBACK_MODEL = "codellama:13b-instruct-q4_K_M"
CHUNK_SIZE = 90
CHUNK_OVERLAP = 30
TIMEOUT = 120
DEBUG = True
INCLUDE_AP200 = False  # Enable if AP200 context is needed

PRIMARY_FILE = r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP160.rpg36.txt"
CONTEXT_FILE = r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP200.rpg36.txt"
TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"
FUZZY_THRESHOLD = 0.94


def read_lines(path):
    with open(path, "r") as f:
        return [line.rstrip("\n") for line in f.readlines()]

def chunk_lines(lines, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    step = size - overlap
    return ['\n'.join(lines[i:i+size]) for i in range(0, len(lines), step)]

def build_prompt(template, chunk, context=None):
    context_block = f"\nContext code from AP200 (reference only):\n{context}\n" if context else ""
    return f"""{template}

You are analyzing **IBM RPG code from AP160** (Accounts Payable system). Your job is to extract only the business logic in a structured use case format. Focus on:
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

def normalize_headers(text):
    replacements = {
        "## Input Validation": "## Input Type Validation Checks",
        "## Validation Rules": "## Input Type Validation Checks",
        "## Entities Used": "## Entities Used / Tables Used",
        "## Tables Used": "## Entities Used / Tables Used"
    }
    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)
    return text

def is_valid_output(text):
    checks = ["## Identification", "## Description", "## Input Type Validation Checks", "## Process Steps"]
    return sum(1 for c in checks if c in text) >= 2  # lower threshold for debugging

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

def process_chunk(i, chunk, template, ap200_context, outdir, logdir):
    prompt = build_prompt(template, chunk, ap200_context if INCLUDE_AP200 else None)
    result = run_ollama(PRIMARY_MODEL, prompt) or run_ollama(FALLBACK_MODEL, prompt)

    if result:
        result = normalize_headers(result)
        if DEBUG:
            print(f"\n🧾 Chunk {i+1} Preview:\n" + "\n".join(result.splitlines()[:10]) + "\n...")

        if is_valid_output(result):
            with open(os.path.join(outdir, f"use_case_{i+1:02d}.md"), "w") as f:
                f.write(result + "\n")
            print(f"✅ Chunk {i+1} saved.")
            return result

        else:
            with open(os.path.join(logdir, f"failed_chunk_{i+1:02d}.txt"), "w") as f:
                f.write(result)
            print(f"❌ Chunk {i+1}: structure failed.")
    else:
        print(f"❌ Chunk {i+1}: no output.")
    return None

if __name__ == "__main__":
    ap160 = read_lines(PRIMARY_FILE)
    ap200 = read_lines(CONTEXT_FILE)[:40] if INCLUDE_AP200 else []
    template = open(TEMPLATE_FILE, "r").read()
    chunks = chunk_lines(ap160)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(OUTPUT_BASE, f"mistral_final_{ts}")
    logdir = os.path.join("logs", f"logs_{ts}")
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(logdir, exist_ok=True)

    all_results = []
    for i, chunk in enumerate(chunks):
        res = process_chunk(i, chunk, template, '\n'.join(ap200), outdir, logdir)
        if res:
            all_results.append(res)

    final = fuzzy_dedupe(all_results)
    with open(os.path.join(outdir, "SUMMARY.md"), "w") as f:
        for uc in final:
            f.write(format_narrative(uc) + "\n\n" + "="*60 + "\n\n")

    print(f"\n✅ {len(final)} unique use cases saved to {outdir}")
