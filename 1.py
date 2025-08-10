import os

def collect_code_files(root_dir, output_file):
    code_extensions = {'.py', '.txt', '.json'}

    # 只包含可能需要改动的路径
    include_paths = {
        'main.py',
        os.path.join('src', 'main_cli.py'),
        'requirements.txt',
        os.path.join('src', 'logic'),
        os.path.join('src', 'image_logic'),
        os.path.join('src', 'path_manager'),
        os.path.join('src', 'logger.py')
    }

    with open(output_file, 'w', encoding='utf-8') as outfile:
        for root, dirs, files in os.walk(root_dir):
            # 跳过缓存和素材
            if 'assets' in root or 'cache' in root or '__pycache__' in root or 'ui_manager' in root or 'window' in root:
                continue

            # 过滤不在 include_paths 的路径
            relative_root = os.path.relpath(root, root_dir)
            if not any(
                relative_root == p or relative_root.startswith(p)
                for p in include_paths
            ):
                continue

            for file in files:
                if os.path.splitext(file)[1] in code_extensions:
                    file_path = os.path.join(root, file)
                    try:
                        outfile.write(f"\n\n{'=' * 80}\n")
                        outfile.write(f"FILE: {file_path}\n")
                        outfile.write(f"{'=' * 80}\n\n")
                        with open(file_path, 'r', encoding='utf-8') as infile:
                            outfile.write(infile.read())
                    except Exception as e:
                        print(f"Error processing {file_path}: {e}")

if __name__ == "__main__":
    project_root = '.'
    output_filename = '1.txt'

    print(f"Collecting CLI-relevant code files from {project_root} into {output_filename}...")
    collect_code_files(project_root, output_filename)
    print("Done!")
