import os
import subprocess
import time
from datetime import datetime

# === Config ===
PRIMARY_MODEL = "codellama:13b-instruct-q4_K_M"
FALLBACK_MODEL = "mistral:7b-instruct-q4_K_M"
CHUNK_SIZE = 30
TIMEOUT = 120  # seconds
OUTPUT_FILE = "use_cases.md"
SOURCE_FILE = "AP160.rpg36"
USE_CASE_TEMPLATE_FILE = "use_case_template.md"
LOG_DIR = "logs"

# === Utility Functions ===
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

# === Main Use Case Processing ===
def analyze_chunks(chunks, template_lines):
    os.makedirs(LOG_DIR, exist_ok=True)

    with open(OUTPUT_FILE, 'w') as out:
        out.write(f"# Use Cases Extracted from {SOURCE_FILE}\n")
        out.write(f"_Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n\n")

        for i, chunk in enumerate(chunks):
            if is_similar_to_template(chunk, template_lines):
                print(f"⏭️ Skipping chunk {i+1} (matches template content)")
                continue

            print(f"\n🧩 Processing chunk {i + 1}/{len(chunks)}...")
            prompt = build_prompt(chunk)

            log_file = os.path.join(LOG_DIR, f"chunk_{i+1:02d}_prompt.txt")
            with open(log_file, "w") as f:
                f.write(prompt)

            print(f"⚙️ Trying primary model: {PRIMARY_MODEL}")
            result = run_ollama(PRIMARY_MODEL, prompt)

            if result is None:
                print("⏱️ Timeout. Trying fallback model...")
                result = run_ollama(FALLBACK_MODEL, prompt)

            if result is None:
                print("❌ Both models failed. Skipping chunk.")
                out.write(f"## Chunk {i+1} - FAILED (timeout or error)\n\n")
            else:
                out.write(f"## Chunk {i+1}\n\n")
                out.write(result + "\n\n")
                print("✅ Use case extracted.")

            # Log model output
            with open(os.path.join(LOG_DIR, f"chunk_{i+1:02d}_response.txt"), "w") as f:
                f.write(result or "[No Response]")

            time.sleep(1)  # prevent model lock / overload

# === Entry Point ===
if __name__ == "__main__":
    if not os.path.exists(SOURCE_FILE):
        print(f"❌ RPG source file not found: {SOURCE_FILE}")
    elif not os.path.exists(USE_CASE_TEMPLATE_FILE):
        print(f"❌ Use case template file not found: {USE_CASE_TEMPLATE_FILE}")
    else:
        template_lines = read_lines(USE_CASE_TEMPLATE_FILE)
        chunks = chunk_file(SOURCE_FILE)
        analyze_chunks(chunks, template_lines)
        print(f"\n📄 All results saved to {OUTPUT_FILE}")
