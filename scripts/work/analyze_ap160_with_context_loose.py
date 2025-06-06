import os
import subprocess
import time
from datetime import datetime
from difflib import SequenceMatcher
import re

# === CONFIGURATION ===
PRIMARY_MODEL = "mistral:7b-instruct"
FALLBACK_MODEL = "codellama:13b-instruct-q4_K_M"
CHUNK_SIZE = 90
CHUNK_OVERLAP = 30
TIMEOUT = 120
DEBUG = True
ALLOW_FLOWCHART = True

PRIMARY_FILE = r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP160.rpg36.txt"
CONTEXT_FILE = r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP200.rpg36.txt"
USE_CASE_TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"
FUZZY_SIMILARITY_THRESHOLD = 0.94

STRUCTURED_FORMAT = """<insert your full use case format here>"""

def read_lines(path):
    with open(path, "r") as f:
        return [line.rstrip("\n") for line in f.readlines()]

def sliding_chunks(lines, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    step = size - overlap
    return ['\n'.join(lines[i:i+size]) for i in range(0, len(lines), step) if i + size <= len(lines)]

def build_prompt(ap160_chunk, ap200_context):
    return f"""
You are analyzing **IBM RPG III code** from an AS/400 system. The code is written in fixed-format RPG with RPG opcodes like CHAIN, EXSR, Z-ADD, etc.

The primary program being analyzed is **AP160**. It optionally calls subroutines from **AP200**, which is provided below for reference only.

Do NOT describe the structure of the code. Instead, generate a structured use case based ONLY on the AP160 logic, using AP200 only as support context.

Use the following format:

{STRUCTURED_FORMAT}

[CONTEXT: AP200 reference code]
{ap200_context}
[END CONTEXT]

[RPG CODE: AP160 logic to analyze]
{ap160_chunk}
[END CODE]
"""

def run_ollama(model, prompt, retries=2, delay=5):
    for attempt in range(retries):
        try:
            print(f"🤖 Running model: {model} (Attempt {attempt + 1})")
            result = subprocess.run(
                ["ollama", "run", model],
                input=prompt.encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=TIMEOUT
            )
            return result.stdout.decode().strip()
        except subprocess.TimeoutExpired:
            print(f"⏱️ Timeout on {model}, attempt {attempt + 1}. Retrying in {delay}s...")
            time.sleep(delay)
    return None

def is_structured_output(text):
    sections = [
        "## Identification", "## Description", "## Process Steps",
        "## Input Type Validation Checks", "## Input Validation", "## Validation Rules",
        "## Entities Used / Tables Used", "## Entities Used", "## Tables Used", "## Flowchart"
    ]
    count = sum(1 for s in sections if s in text)
    return count >= 3

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

def to_narrative_format(use_case_text):
    sections = {
        "Identification": "", "Description": "", "Pre-Condition": "",
        "Post-Condition": "", "Entities Used / Tables Used": "",
        "Program Steps": "", "Tests Needed": ""
    }
    current = None
    for line in use_case_text.splitlines():
        match = re.match(r"^##+\s+(.*)", line)
        if match:
            title = match.group(1).strip().lower()
            if "identification" in title: current = "Identification"
            elif "description" in title: current = "Description"
            elif "pre-condition" in title: current = "Pre-Condition"
            elif "post-condition" in title: current = "Post-Condition"
            elif "entities" in title or "tables" in title: current = "Entities Used / Tables Used"
            elif "step" in title: current = "Program Steps"
            elif "test" in title: current = "Tests Needed"
            else: current = None
        elif current:
            sections[current] += line.strip() + "\n"

    if sections["Identification"]:
        id_lines = [line.strip() for line in sections["Identification"].splitlines() if line.strip()]
        sections["Identification"] = "\n".join(id_lines)

    result = ["Use Case Template\n"]
    for section in sections:
        result.append(f"### {section}\n")
        result.append(sections[section].strip() + "\n")
    return "\n".join(result).strip()

def process_chunk(i, chunk, ap200_context, output_dir, log_dir):
    prompt = build_prompt(chunk, ap200_context)
    result = run_ollama(PRIMARY_MODEL, prompt) or run_ollama(FALLBACK_MODEL, prompt)
    if result:
        result = normalize_headers(result)
        if DEBUG:
            print(f"\n📄 Chunk {i+1} Preview:\n" + "-"*50)
            print("\n".join(result.splitlines()[:10]) + "\n...")
        if is_structured_output(result):
            with open(os.path.join(output_dir, f"use_case_{i+1:02d}.md"), "w") as f:
                f.write(result + "\n")
            print(f"✅ Chunk {i+1} saved.")
            return result
        else:
            failpath = os.path.join(log_dir, f"failed_chunk_{i+1:02d}.txt")
            with open(failpath, "w") as f:
                f.write(result)
            print(f"❌ Chunk {i+1}: Format failed — logged to {failpath}")
            return None
    else:
        print(f"❌ Chunk {i+1}: Model did not return anything.")
        return None

def fuzzy_deduplicate(use_cases):
    seen, deduped = [], []
    for uc in use_cases:
        if not any(SequenceMatcher(None, uc, s).ratio() > FUZZY_SIMILARITY_THRESHOLD for s in seen):
            seen.append(uc)
            deduped.append(uc)
    return deduped

if __name__ == "__main__":
    if not os.path.exists(PRIMARY_FILE) or not os.path.exists(CONTEXT_FILE):
        print("❌ One or more input files not found.")
        exit(1)
    ap160_lines = read_lines(PRIMARY_FILE)
    ap200_lines = read_lines(CONTEXT_FILE)
    ap160_chunks = sliding_chunks(ap160_lines)
    ap200_context = "\n".join(ap200_lines[:150])  # trimmed context

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join(OUTPUT_BASE, f"ap160_run_{ts}")
    log_dir = os.path.join("logs", f"logs_{ts}")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    all_results = []
    for i, chunk in enumerate(ap160_chunks):
        result = process_chunk(i, chunk, ap200_context, output_dir, log_dir)
        if result:
            all_results.append(result)

    final = fuzzy_deduplicate(all_results)
    summary_file = os.path.join(output_dir, "SUMMARY.md")
    with open(summary_file, "w") as f:
        for uc in final:
            f.write(to_narrative_format(uc) + "\n\n" + "="*60 + "\n\n")
    print(f"\n✅ {len(final)} unique use cases saved to {summary_file}")
