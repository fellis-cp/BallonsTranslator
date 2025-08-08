import argparse

def split_txt_file(input_file, num_parts):
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    total_lines = len(lines)
    lines_per_part = total_lines // num_parts
    remainder = total_lines % num_parts

    for i in range(num_parts):
        start_index = i * lines_per_part + min(i, remainder)
        end_index = start_index + lines_per_part + (1 if i < remainder else 0)
        part_lines = lines[start_index:end_index]

        output_file = f"{input_file.rsplit('.', 1)[0]}_part{i+1}.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(part_lines)

        print(f"[+] Written {len(part_lines)} lines to {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Split a text file into equal parts.")
    parser.add_argument('--input', required=True, help="Path to the input .txt file")
    parser.add_argument('--parts', type=int, required=True, help="Number of parts to split into")

    args = parser.parse_args()
    split_txt_file(args.input, args.parts)

if __name__ == "__main__":
    main()
