import argparse
import os

def merge_txt_files(input_files, output_file):
    with open(output_file, 'w', encoding='utf-8') as out_f:
        for file in input_files:
            if not os.path.exists(file):
                print(f"[!] Skipping missing file: {file}")
                continue
            with open(file, 'r', encoding='utf-8') as in_f:
                lines = in_f.readlines()
                out_f.writelines(lines)
                print(f"[+] Added {len(lines)} lines from {file}")

    print(f"\n✅ Merged {len(input_files)} files into: {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Merge multiple text files into one.")
    parser.add_argument('--input', nargs='+', required=True, help="List of input .txt files to merge")
    parser.add_argument('--output', required=True, help="Output file name")

    args = parser.parse_args()
    merge_txt_files(args.input, args.output)

if __name__ == "__main__":
    main()
