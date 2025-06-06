import os
import subprocess
import time
from datetime import datetime
from multiprocessing import Pool, cpu_count
from difflib import SequenceMatcher

# === CONFIGURATION ===
PRIMARY_MODEL = "codellama:13b-instruct-q4_K_M"
FALLBACK_MODEL = "mistral:7b-instruct-q4_K_M"
CHUNK_SIZE = 90
CHUNK_OVERLAP = 30
TIMEOUT = 120
DEBUG = True

# === MULTIPLE SOURCE FILES ===
SOURCE_FILES = [
    r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP160.rpg36.txt",
    r"C:\Temp\IBM-GitHub-Submission-Unedited\IBM-GitHub-Submission\QSRC\AP200.rpg36.txt"
]
USE_CASE_TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"
LOG_DIR = "logs"
FUZZY_SIMILARITY_THRESHOLD = 0.94

STRUCTURED_FORMAT = """ ... """  # Use unchanged from your last script (shortened here for space)

# === UTILS ===
def read_lines(path):
    with open(path, "r") as f:
        return [line.rstrip("\n") for line in f.readlines()]

def sliding_chunks(lines, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    step = size - overlap
    return ['\n'.join(lines[i:i+size]) for i in range(0, len(lines), step) if i + size <= len(lines)]

def is_similar_to_template(chunk, template_lines):
    return any(line.strip() in template_lines for line in chunk.splitlines())

def build_prompt(rpg_code):
    return f"""
You are analyzing legacy IBM RPG (Report Program Generator) code to extract a structured business use case, including all field validations.

Use the following format. Match the section headings exactly:

{STRUCTURED_FORMAT}

[RPG CODE]
{rpg_code}
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

def is_structured_output(text):
    sections = [
        "## Identification",
        "## Description",
        "## Process Steps",
        ("## Input Type Validation Checks", "## Input Validation")
    ]
    found = 0
    for s in sections:
        if isinstance(s, tuple):
            if any(sub in text for sub in s):
                found += 1
        elif s in text:
            found += 1
    return found >= 3

def normalize_headers(text):
    return text.replace("## Input Validation", "## Input Type Validation Checks")

def process_chunk(args):
    index, chunk, template_lines, output_dir = args

    if is_similar_to_template(chunk, template_lines):
        print(f"⏭️ Skipping chunk {index+1} (matches template)")
        return None

    prompt = build_prompt(chunk)
    result = run_ollama(PRIMARY_MODEL, prompt) or run_ollama(FALLBACK_MODEL, prompt)

    if result:
        if DEBUG:
            print(f"\n🧾 Output preview for chunk {index+1}:\n" + "-"*50)
            print("\n".join(result.splitlines()[:10]) + "\n...")

        result = normalize_headers(result)

        if is_structured_output(result):
            filename = f"use_case_{index+1:02d}.md"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w') as f:
                f.write(result + "\n")
            print(f"✅ Chunk {index+1}: Saved structured use case.")
            return result
        else:
            fail_path = os.path.join(LOG_DIR, f"failed_chunk_{index+1:02d}.txt")
            with open(fail_path, "w") as f:
                f.write(result)
            print(f"❌ Chunk {index+1}: Missing expected structure. Logged to {fail_path}")
            return None
    else:
        print(f"❌ Chunk {index+1}: Model failed or timed out.")
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
    for file in SOURCE_FILES:
        if not os.path.exists(file):
            print(f"❌ Source file not found: {file}")
            exit(1)

    if not os.path.exists(USE_CASE_TEMPLATE_FILE):
        print(f"❌ Template file not found: {USE_CASE_TEMPLATE_FILE}")
        exit(1)

    template_lines = read_lines(USE_CASE_TEMPLATE_FILE)

    # Read and combine all source files
    all_lines = []
    for file in SOURCE_FILES:
        all_lines.extend(read_lines(file))

    merged_chunks = sliding_chunks(all_lines)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join(OUTPUT_BASE, f"structured_run_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    args = [(i, chunk, template_lines, output_dir) for i, chunk in enumerate(merged_chunks)]

    print(f"🔄 Processing {len(args)} chunks using {cpu_count()} CPUs...")

    with Pool(processes=cpu_count()) as pool:
        results = pool.map(process_chunk, args)

    final = fuzzy_deduplicate([r for r in results if r])
    summary_file = os.path.join(output_dir, "SUMMARY.md")
    with open(summary_file, "w") as f:
        f.write(f"# Unique Use Cases ({len(final)})\n\n")
        for i, uc in enumerate(final, 1):
            f.write(f"## Use Case {i}\n\n{uc}\n\n")

    print(f"\n📄 {len(final)} unique use cases saved to {output_dir}")
