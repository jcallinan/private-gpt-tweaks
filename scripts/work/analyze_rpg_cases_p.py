import os
import subprocess
import time
from datetime import datetime
from multiprocessing import Pool, cpu_count
from difflib import SequenceMatcher
import hashlib

# === CONFIGURATION ===
PRIMARY_MODEL = "codellama:13b-instruct-q4_K_M"
FALLBACK_MODEL = "mistral:7b-instruct-q4_K_M"
CHUNK_SIZE = 30
TIMEOUT = 120
SOURCE_FILE = "AP160.rpg36"
USE_CASE_TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"
LOG_DIR = "logs"
FUZZY_SIMILARITY_THRESHOLD = 0.95  # Prevent duplicates

# === UTILS ===
def read_lines(path):
    with open(path, "r") as f:
        return [line.strip("\n") for line in f.readlines()]

def chunk_file(file_path, lines_per_chunk=CHUNK_SIZE):
    lines = read_lines(file_path)
    return ['\n'.join(lines[i:i+lines_per_chunk]) for i in range(0, len(lines), lines_per_chunk)]

def is_similar_to_template(chunk, template_lines):
    return any(line.strip() in template_lines for line in chunk.splitlines())

def build_prompt(rpg_code):
    return f"""
You are an expert in legacy IBM RPG financial systems.

Analyze the following RPG code and extract a **single use case** related to:

- Accounts Payable
- Vouchers
- Invoices
- Vendor processing
- GL validation
- Freight
- Receipts
- 1099 tracking
- Payment records

Ignore unrelated logic like inventory, sales, purchase orders, or product management.

Format your response like this:

- Use Case Title
- What the code does (1–2 sentences)
- Input fields used
- Validations or error handling
- Files or subroutines called

Respond only in that structure. Do not repeat the RPG code.

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
        filename = f"chunk_{index+1:02d}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(f"# Use Case from Chunk {index+1}\n\n{result}\n")
        print(f"✅ Chunk {index+1}: Saved use case.")
        return result
    else:
        print(f"❌ Chunk {index+1}: Model failed or timed out.")
        return None

def fuzzy_deduplicate(use_cases):
    seen = []
    deduped = []

    for uc in use_cases:
        is_dup = False
        for existing in seen:
            ratio = SequenceMatcher(None, uc, existing).ratio()
            if ratio > FUZZY_SIMILARITY_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            seen.append(uc)
            deduped.append(uc)
    return deduped

# === MAIN ===
if __name__ == "__main__":
    if not os.path.exists(SOURCE_FILE):
        print(f"❌ RPG source file not found: {SOURCE_FILE}")
        exit(1)
    if not os.path.exists(USE_CASE_TEMPLATE_FILE):
        print(f"❌ Use case template file not found: {USE_CASE_TEMPLATE_FILE}")
        exit(1)

    template_lines = read_lines(USE_CASE_TEMPLATE_FILE)
    chunks = chunk_file(SOURCE_FILE)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join(OUTPUT_BASE, f"run_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    pool_args = [(i, chunk, template_lines, output_dir) for i, chunk in enumerate(chunks)]

    print(f"🧠 Processing {len(pool_args)} chunks with {cpu_count()} CPUs...")

    with Pool(processes=cpu_count()) as pool:
        results = pool.map(process_chunk, pool_args)

    valid_results = [r for r in results if r]
    deduped_results = fuzzy_deduplicate(valid_results)

    summary_file = os.path.join(output_dir, "SUMMARY.md")
    with open(summary_file, "w") as f:
        f.write(f"# Summary of Use Cases - {len(deduped_results)} Unique\n\n")
        for i, uc in enumerate(deduped_results, 1):
            f.write(f"## Use Case {i}\n\n{uc}\n\n")

    print(f"\n📄 {len(deduped_results)} unique use cases saved to: {output_dir}")
