import os
import subprocess
import time
from datetime import datetime

PRIMARY_MODEL = "mistral:7b-instruct"
FALLBACK_MODEL = "codellama:13b-instruct-q4_K_M"
CHUNK_SIZE = 300  # Larger superchunks
CHUNK_OVERLAP = 60
TIMEOUT = 180

PRIMARY_FILE = r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP160.rpg36.txt"
CONTEXT_FILE = r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP200.rpg36.txt"
USE_CASE_TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"


def read_lines(path):
    with open(path, "r") as f:
        return [line.rstrip("\n") for line in f.readlines()]


def superchunks(lines, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    step = size - overlap
    return ['\n'.join(lines[i:i+size]) for i in range(0, len(lines), step)]


def build_prompt(template, ap200_context, ap160_chunk):
    return f"""
{template}

---
You are analyzing **IBM RPG III code** from program AP160 on the AS/400 platform. 

The program logic relates to:
- Accounts Payable
- Vouchers
- Vendor validation
- GL and 1099 logic

You are also provided with supporting code from AP200 (below), which may be referenced, but should NOT be used to generate separate use cases.

Do **not** describe the code. Instead, output a structured use case ONLY, following the format above.

---
[AP200 SUPPORT CODE - CONTEXT ONLY]
{ap200_context}

---
[RPG PROGRAM: AP160 CHUNK]
{ap160_chunk}
---
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


def process_chunk(index, template, ap200, chunk, output_dir):
    prompt = build_prompt(template, ap200, chunk)
    result = run_ollama(PRIMARY_MODEL, prompt) or run_ollama(FALLBACK_MODEL, prompt)

    if result and any(h in result for h in ["## Identification", "## Description"]):
        out_file = os.path.join(output_dir, f"use_case_{index+1:02d}.md")
        with open(out_file, "w") as f:
            f.write(result + "\n")
        print(f"✅ Chunk {index+1}: use case saved.")
    else:
        fail_file = os.path.join(output_dir, f"failed_chunk_{index+1:02d}.txt")
        with open(fail_file, "w") as f:
            f.write(result or "[NO OUTPUT]")
        print(f"❌ Chunk {index+1}: failed or empty. Logged.")


if __name__ == "__main__":
    ap160 = read_lines(PRIMARY_FILE)
    ap200 = read_lines(CONTEXT_FILE)[:50]  # Trim to top 50 lines
    template = open(USE_CASE_TEMPLATE_FILE, "r").read()

    chunks = superchunks(ap160)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUTPUT_BASE, f"ap160_superchunk_{timestamp}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"🚀 Generating use cases from {len(chunks)} superchunks...\n")

    for i, chunk in enumerate(chunks):
        process_chunk(i, template, '\n'.join(ap200), chunk, out_dir)

    print(f"\n✅ Run complete. Output saved to: {out_dir}")
