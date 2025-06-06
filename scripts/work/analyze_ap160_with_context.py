import os
import subprocess
import time
from datetime import datetime
from difflib import SequenceMatcher
import re

# === CONFIGURATION ===
PRIMARY_MODEL = "mistral:7b-instruct-q4_K_M"
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

STRUCTURED_FORMAT = """<same as before — omitted here for brevity>"""

def read_lines(path):
    with open(path, "r") as f:
        return [line.rstrip("\n") for line in f.readlines()]

def sliding_chunks(lines, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    step = size - overlap
    return ['\n'.join(lines[i:i+size]) for i in range(0, len(lines), step) if i + size <= len(lines)]

def build_prompt(ap160_chunk, ap200_context):
    return f"""
You are analyzing IBM RPG legacy code from **program AP160**, which references **support routines from AP200**.

Your job is to extract a detailed business use case **based on the AP160 logic only**, using AP200 strictly as context if needed.

Focus on:
- Accounts Payable logic
- Vouchers, GL validations, payments, 1099s
- Do NOT generate a use case for AP200 directly

Always include:
- Input field validations
- Tables/entities used
- A step-by-step process
- A flowchart (if possible)

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

def has_flowchart(text):
    return "## Flowchart" in text or ("```" in text and "Process" in text)

def is_structured_output(text):
    """Check if the result contains enough key sections — allow flowcharts or loose matches."""
    sections = [
        "## Identification",
        "## Description",
        "## Process Steps",
        "## Entities Used",
        "## Tables Used",
        "## Input Validation",
        "## Input Type Validation Checks",
        "## Flowchart"
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
        "Identification": "",
        "Description": "",
        "Pre-Condition": "",
        "Post-Condition": "",
        "Entities Used / Tables Used": "",
        "Program Steps": "",
        "Tests Needed": ""
    }
    current = None
    lines = use_case_text.splitlines()
    for line in lines:
        match = re.match(r"^##+\s+(.*)", line)
        if match:
            title = match.group(1).strip()
            norm = title.lower()
            if "identification" in norm:
                current = "Identification"
            elif "description" in norm:
                current = "Description"
            elif "pre-condition" in norm:
                current = "Pre-Condition"
            elif "post-condition" in norm:
                current = "Post-Condition"
            elif "entities used" in norm or "tables used" in norm:
                current = "Entities Used / Tables Used"
            elif "steps" in norm:
                current = "Program Steps"
            elif "test" in norm:
                current = "Tests Needed"
            else:
                current = None
        elif current:
            sections[current] += line.strip() + "\n"

    # Identification field spacing
    if sections["Identification"]:
        id_lines = []
        for line in sections["Identification"].splitlines():
            if line.strip():
                id_lines.append(line.strip())
        sections["Identification"] = "\n".join(id_lines)

    result = ["Use Case Template\n"]
    for section in sections:
        result.append(f"### {section}\n")
        result.append(sections[section].strip() + "\n")
    return "\n".join(result).strip()

def process_chunk(chunk_index, ap160_chunk, ap200_context, template_lines, output_dir, log_dir):
    prompt = build_prompt(ap160_chunk, ap200_context)
    start_time = time.time()

    result = run_ollama(PRIMARY_MODEL, prompt)
    if not result:
        print("🔁 Primary model failed. Trying fallback...")
        result = run_ollama(FALLBACK_MODEL, prompt)

    duration = int(time.time() - start_time)
    print(f"⏳ Chunk {chunk_index+1} took {duration}s")

    if result:
        result = normalize_headers(result)

        if DEBUG:
            print(f"\n🧾 Output preview for chunk {chunk_index+1}:\n" + "-"*50)
            print("\n".join(result.splitlines()[:10]) + "\n...")

        if is_structured_output(result):
            filename = f"use_case_{chunk_index+1:02d}.md"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w') as f:
                f.write(result + "\n")
            print(f"✅ Chunk {chunk_index+1}: Saved structured use case.")
            return result
        else:
            fail_path = os.path.join(log_dir, f"failed_chunk_{chunk_index+1:02d}.txt")
            with open(fail_path, "w") as f:
                f.write(result)
            print(f"❌ Chunk {chunk_index+1}: Format check failed. Logged to {fail_path}")
            return None
    else:
        print(f"❌ Chunk {chunk_index+1}: Model completely failed.")
        return None

def fuzzy_deduplicate(use_cases):
    seen = []
    deduped = []
    for uc in use_cases:
        if not any(SequenceMatcher(None, uc, existing).ratio() > FUZZY_SIMILARITY_THRESHOLD for existing in seen):
            seen.append(uc)
            deduped.append(uc)
    return deduped

# === MAIN ===
if __name__ == "__main__":
    for file in [PRIMARY_FILE, CONTEXT_FILE]:
        if not os.path.exists(file):
            print(f"❌ Required file not found: {file}")
            exit(1)

    if not os.path.exists(USE_CASE_TEMPLATE_FILE):
        print(f"❌ Template file not found: {USE_CASE_TEMPLATE_FILE}")
        exit(1)

    ap160_lines = read_lines(PRIMARY_FILE)
    ap200_lines = read_lines(CONTEXT_FILE)
    template_lines = read_lines(USE_CASE_TEMPLATE_FILE)

    ap160_chunks = sliding_chunks(ap160_lines)
    ap200_context = "\n".join(ap200_lines)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join(OUTPUT_BASE, f"ap160_run_{timestamp}")
    log_dir = os.path.join("logs", f"logs_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    print(f"🚀 Starting AP160 analysis with AP200 as context ({len(ap160_chunks)} chunks)...\n")

    all_results = []
    for i, chunk in enumerate(ap160_chunks):
        result = process_chunk(i, chunk, ap200_context, template_lines, output_dir, log_dir)
        if result:
            all_results.append(result)

    final = fuzzy_deduplicate(all_results)
    summary_file = os.path.join(output_dir, "SUMMARY.md")
    with open(summary_file, "w") as f:
        for i, uc in enumerate(final, 1):
            f.write(to_narrative_format(uc))
            f.write("\n\n" + "="*60 + "\n\n")

    print(f"\n✅ {len(final)} unique use cases saved to {output_dir}")
    print(f"🪵 Logs saved to {log_dir}")
