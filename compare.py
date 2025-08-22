import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import re

def load_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
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
            if re.match(r"^\d+\.", line):
                num = line.split(".")[0]
                found = any(l.startswith(num + ".") for l in en_lines)
                if not found:
                    missing.append(line)
        if missing:
            report.append(f"⚠️ {page} is missing translations:\n" + "\n".join("   " + m for m in missing))
        else:
            report.append(f"✅ {page} is fully translated.")
    return "\n\n".join(report)

def load_original():
    filepath = filedialog.askopenfilename(title="Select Original (JP) File", filetypes=[("Text Files", "*.txt")])
    if filepath:
        global original_file
        original_file = filepath
        messagebox.showinfo("Loaded", f"Original file loaded:\n{filepath}")

def load_translated():
    filepath = filedialog.askopenfilename(title="Select Translated (EN) File", filetypes=[("Text Files", "*.txt")])
    if filepath:
        global translated_file
        translated_file = filepath
        messagebox.showinfo("Loaded", f"Translated file loaded:\n{filepath}")

def run_check():
    if not original_file or not translated_file:
        messagebox.showerror("Error", "Please load both Original and Translated files first.")
        return
    original = load_file(original_file)
    translated = load_file(translated_file)
    original_pages = split_by_page(original)
    translated_pages = split_by_page(translated)
    result = check_pages(original_pages, translated_pages)
    output_text.delete(1.0, tk.END)
    output_text.insert(tk.END, result)

root = tk.Tk()
root.title("Translation Checker by Page")
root.geometry("800x600")

original_file = None
translated_file = None

frame = tk.Frame(root)
frame.pack(pady=10)

btn_load_original = tk.Button(frame, text="Load Original (JP)", command=load_original, width=20)
btn_load_original.grid(row=0, column=0, padx=10)

btn_load_translated = tk.Button(frame, text="Load Translated (EN)", command=load_translated, width=20)
btn_load_translated.grid(row=0, column=1, padx=10)

btn_check = tk.Button(root, text="Check Translation", command=run_check, width=40, bg="lightblue")
btn_check.pack(pady=10)

output_text = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=100, height=25)
output_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

root.mainloop()
