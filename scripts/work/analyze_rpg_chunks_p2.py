import os
import subprocess
import time
from datetime import datetime
from multiprocessing import Pool, cpu_count
from difflib import SequenceMatcher

# === CONFIGURATION ===
PRIMARY_MODEL = "codellama:13b-instruct-q4_K_M"
FALLBACK_MODEL = "mistral:7b-instruct-q4_K_M"
CHUNK_SIZE = 90          # Merge to bigger windows
CHUNK_OVERLAP = 30       # Sliding window
TIMEOUT = 120
SOURCE_FILE = "AP160.rpg36"
USE_CASE_TEMPLATE_FILE = "use_case_template.md"
OUTPUT_BASE = "use_case_outputs"
LOG_DIR = "logs"
FUZZY_SIMILARITY_THRESHOLD = 0.94

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
You are analyzing IBM RPG legacy source code for finance systems.

Please identify **one complete use case** in the following code related to:

- Accounts Payable
- Vouchers
- Invoices
- Vendor processing
- GL validation
- Freight
- Receipts
- 1099 tracking
- Payment records

Only include one use case. Format:

- Use Case Title
- What the code does (1–2 sentences)
- Input fields used
- Validations or error handling
- Files or subroutines called

Avoid any unrelated business processes (e.g., inventory or sales).

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
        filename = f"merged_chunk_{index+1:02d}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w') as f:
            f.write(f"# Use Case from Merged Chunk {index+1}\n\n{result}\n")
        print(f"✅ Merged Chunk {index+1}: Saved use case.")
        return result
    else:
        print(f"❌ Merged Chunk {index+1}: Model failed.")
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
    output_dir = os.path.join(OUTPUT_BASE, f"merged_run_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    args = [(i, chunk, template_lines, output_dir) for i, chunk in enumerate(merged_chunks)]

    print(f"🔄 Merged into {len(args)} larger chunks. Starting parallel analysis...")

    with Pool(processes=cpu_count()) as pool:
        results = pool.map(process_chunk, args)

    final = fuzzy_deduplicate([r for r in results if r])
    summary_file = os.path.join(output_dir, "SUMMARY.md")
    with open(summary_file, "w") as f:
        f.write(f"# Unique Use Cases ({len(final)})\n\n")
        for i, uc in enumerate(final, 1):
            f.write(f"## Use Case {i}\n\n{uc}\n\n")

    print(f"\n📄 {len(final)} unique use cases saved to {output_dir}")
