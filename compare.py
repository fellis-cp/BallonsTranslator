# Compare Japanese original vs English translation by page (### sections)

import re

def load_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [line.rstrip() for line in f if line.strip()]

def split_by_page(lines):
    pages = {}
    current_page = None

    for line in lines:
        if line.startswith("###"):
            current_page = line.strip()
            pages[current_page] = []
        elif current_page:
            pages[current_page].append(line.strip())
    return pages

def check_pages(original_pages, translated_pages):
    report = []

    for page, jp_lines in original_pages.items():
        en_lines = translated_pages.get(page, [])
        missing = []

        for line in jp_lines:
            if re.match(r"^\d+\.", line):  # only numbered lines
                num = line.split(".")[0]
                found = any(l.startswith(num + ".") for l in en_lines)
                if not found:
                    missing.append(line)

        if missing:
            report.append(f"⚠️ Page {page} is missing translations:")
            for m in missing:
                report.append("   " + m)
        else:
            report.append(f"✅ Page {page} is fully translated.")
    return report

if __name__ == "__main__":
    original = load_file("original.txt")      # Japanese source
    translated = load_file("translated.txt")  # English translation

    original_pages = split_by_page(original)
    translated_pages = split_by_page(translated)

    result = check_pages(original_pages, translated_pages)

    print("\n".join(result))
