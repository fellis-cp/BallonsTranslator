import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES

# ====== Merge Logic ======
def merge_txt_files(input_files, output_file, log):
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as out_f:
        for file in input_files:
            if not os.path.exists(file):
                log.insert(tk.END, f"[!] Skipping missing file: {file}\n")
                continue
            with open(file, 'r', encoding='utf-8') as in_f:
                lines = in_f.readlines()
                out_f.writelines(lines)
                log.insert(tk.END, f"[+] Added {len(lines)} lines from {os.path.basename(file)}\n")
    log.insert(tk.END, f"\n✅ Merged {len(input_files)} files into: {output_file}\n")

# ====== Split Logic ======
def split_txt_file(input_file, num_parts, output_folder, log):
    os.makedirs(output_folder, exist_ok=True)
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    total_lines = len(lines)
    lines_per_part = total_lines // num_parts
    remainder = total_lines % num_parts

    for i in range(num_parts):
        start_index = i * lines_per_part + min(i, remainder)
        end_index = start_index + lines_per_part + (1 if i < remainder else 0)
        part_lines = lines[start_index:end_index]

        output_path = os.path.join(output_folder, f"{os.path.splitext(os.path.basename(input_file))[0]}_part{i+1}.txt")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(part_lines)

        log.insert(tk.END, f"[+] Written {len(part_lines)} lines to {os.path.basename(output_path)}\n")

    log.insert(tk.END, f"\n✅ Split into {num_parts} parts in folder: {output_folder}\n")

# ====== Browse Button ======
def browse_files():
    selected_files = filedialog.askopenfilenames(
        title="Select TXT Files",
        filetypes=[("Text files", "*.txt")],
    )
    if selected_files:
        for file in selected_files:
            file_listbox.insert(tk.END, file)

# ====== Drag & Drop ======
def on_drop(event):
    paths = root.splitlist(event.data)  # Handles multiple file drops
    for path in paths:
        if os.path.isfile(path) and path.lower().endswith(".txt"):
            file_listbox.insert(tk.END, path)
        else:
            log_text.insert(tk.END, f"[!] Ignored non-txt file: {path}\n")

# ====== Run ======
def run_action():
    mode = mode_var.get()
    files = file_listbox.get(0, tk.END)
    if not files:
        messagebox.showerror("Error", "No .txt files selected.")
        return

    first_file_folder = os.path.dirname(files[0])
    output_folder = os.path.join(first_file_folder, "output")

    if mode == "merge":
        output_file = os.path.join(output_folder, "merged.txt")
        merge_txt_files(files, output_file, log_text)

    elif mode == "split":
        selected = file_listbox.curselection()
        if not selected:
            messagebox.showerror("Error", "Please select a file to split.")
            return
        file_to_split = file_listbox.get(selected[0])
        try:
            num_parts = int(parts_entry.get())
            if num_parts <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number of parts.")
            return
        split_txt_file(file_to_split, num_parts, output_folder, log_text)

# ====== Clear ======
def clear_all():
    file_listbox.delete(0, tk.END)
    log_text.delete(1.0, tk.END)

# ====== GUI ======
root = TkinterDnD.Tk()
root.title("TXT Merger & Splitter")
root.geometry("600x500")

# Browse Button
top_frame = ttk.Frame(root)
top_frame.pack(fill=tk.X, pady=5, padx=10)
ttk.Button(top_frame, text="Browse TXT Files", command=browse_files).pack(side=tk.LEFT)

# Drag & Drop Label
drop_label = tk.Label(root, text="📂 Drag TXT files here", relief="ridge", height=3, bg="#f0f0f0")
drop_label.pack(fill=tk.X, padx=10, pady=5)
drop_label.drop_target_register(DND_FILES)
drop_label.dnd_bind('<<Drop>>', on_drop)

# Mode Selection
mode_var = tk.StringVar(value="merge")
mode_frame = ttk.Frame(root)
mode_frame.pack(pady=5)
ttk.Radiobutton(mode_frame, text="Merge all", variable=mode_var, value="merge").pack(side=tk.LEFT, padx=5)
ttk.Radiobutton(mode_frame, text="Split one", variable=mode_var, value="split").pack(side=tk.LEFT, padx=5)

# Parts Entry (for split)
parts_frame = ttk.Frame(root)
parts_frame.pack(pady=5)
ttk.Label(parts_frame, text="Number of parts (split mode):").pack(side=tk.LEFT)
parts_entry = ttk.Entry(parts_frame, width=5)
parts_entry.insert(0, "2")
parts_entry.pack(side=tk.LEFT, padx=5)

# File Listbox
file_listbox = tk.Listbox(root, height=8)
file_listbox.pack(fill=tk.X, padx=10, pady=5)
file_listbox.drop_target_register(DND_FILES)
file_listbox.dnd_bind('<<Drop>>', on_drop)

# Buttons
btn_frame = ttk.Frame(root)
btn_frame.pack(pady=5)
ttk.Button(btn_frame, text="Run", command=run_action).pack(side=tk.LEFT, padx=5)
ttk.Button(btn_frame, text="Clear", command=clear_all).pack(side=tk.LEFT, padx=5)

# Log Output
log_text = tk.Text(root, height=10)
log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

root.mainloop()
    