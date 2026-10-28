import os
import zipfile

def create_project_zip(root_dir, output_zip):
    exclude_dirs = {
        '.git', '.venv', 'venv', '__pycache__', '.pytest_cache',
        '.gemini', '.idea', '.vscode', '.system_generated'
    }
    exclude_extensions = {'.pyc', '.pyo', '.webp'}
    exclude_files = {'rescueflow.db-journal', os.path.basename(output_zip)}

    print(f"Creating project zip: {output_zip}...")
    file_count = 0
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(root_dir):
            # Prune excluded directories in place
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
            
            for file in files:
                if file in exclude_files:
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in exclude_extensions:
                    continue
                
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                
                zf.write(full_path, rel_path)
                file_count += 1
                
    size_mb = os.path.getsize(output_zip) / (1024 * 1024)
    print(f"[OK] Archived {file_count} files into {output_zip}")
    print(f"[OK] Total Zip Size: {size_mb:.2f} MB (Limit is 100 MB)")

if __name__ == "__main__":
    root = r"c:\Users\sonu kumar\OneDrive - Lovely Professional University\Desktop\Agent__"
    out = r"c:\Users\sonu kumar\OneDrive - Lovely Professional University\Desktop\Agent__\RescueFlow_AI_Project.zip"
    create_project_zip(root, out)
