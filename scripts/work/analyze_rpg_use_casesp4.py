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
SOURCE_FILE = "AP160.rpg36"
USE_CASE_TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"
LOG_DIR = "logs"
FUZZY_SIMILARITY_THRESHOLD = 0.94

# === STRUCTURED FORMAT INJECTION ===
STRUCTURED_FORMAT = """
Respond using the following structure and labels. Do not reuse example content. Fill in all applicable sections:

# <Use Case Title>

## Identification
**Use Case ID**: UC-AP-XXX-XX  
**Module Group**: Accounts Payable  
**Legacy Program Ref**: <Legacy Program Ref>  
**Version**: 1.0  
**Last Update**: <Date>  
**Last Update By**: <Name>  
**Created**: <Date>  
**Created By**: <Name>  
**Approved By**: <Name or ?>

## Description
<Describe what this use case does>

## Pre-Condition
<List all required conditions>

## Post-Condition
<List all results or outcomes>

## Entities Used / Tables Used
<List database tables, files, or entities involved>

## Process Steps
- Step 1
- Step 2
- ...

## Tests Needed
<Any required tests for this logic>

## Input Type Validation Checks
1. <Validation Rule>
2. ...

## Business Rule
<Business-specific conditions or logic>

## Existence Checking
<Check for required related records, validations, or constraints>
"""

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
You are analyzing legacy IBM RPG code to extract structured business use cases.

Only include use cases related to:
- Accounts Payable
- Vouchers
- Invoices
- Vendor processing
- GL validation
- Freight
- Receipts
- 1099 tracking
- Payment records

Do NOT include inventory, sales, or product logic.

Use the structure below for formatting — do not copy its content, only match its headings and layout:

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
    required_sections = ["## Identification", "## Description", "## Process Steps"]
    return all(section in text for section in required_sections)

def process_chunk(args):
    index, chunk, template_lines, output_dir = args

    if is_similar_to_template(chunk, template_lines):
        print(f"⏭️ Skipping chunk {index+1} (matches template)")
        return None

    prompt = build_prompt(chunk)
    result = run_ollama(PRIMARY_MODEL, prompt)
    if result is None:
        result = run_ollama(FALLBACK_MODEL, prompt)

    if result:
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
            print(f"❌ Chunk {index+1}: Output did not match expected structure.")
            print(f"💡 Logged to {fail_path}")
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
    if not os.path.exists(SOURCE_FILE):
        print(f"❌ RPG source file not found: {SOURCE_FILE}")
        exit(1)
    if not os.path.exists(USE_CASE_TEMPLATE_FILE):
        print(f"❌ Template file not found: {USE_CASE_TEMPLATE_FILE}")
        exit(1)

    template_lines = read_lines(USE_CASE_TEMPLATE_FILE)
    lines = read_lines(SOURCE_FILE)
    merged_chunks = sliding_chunks(lines)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join(OUTPUT_BASE, f"structured_run_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    args = [(i, chunk, template_lines, output_dir) for i, chunk in enumerate(merged_chunks)]

    print(f"🔄 Processing {len(args)} structured chunks using {cpu_count()} CPUs...")

    with Pool(processes=cpu_count()) as pool:
        results = pool.map(process_chunk, args)

    final = fuzzy_deduplicate([r for r in results if r])
    summary_file = os.path.join(output_dir, "SUMMARY.md")
    with open(summary_file, "w") as f:
        f.write(f"# Unique Use Cases ({len(final)})\n\n")
        for i, uc in enumerate(final, 1):
            f.write(f"## Use Case {i}\n\n{uc}\n\n")

    print(f"\n📄 {len(final)} unique use cases saved to {output_dir}")
