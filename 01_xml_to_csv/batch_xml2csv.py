import subprocess
import os
import glob
import sys

# Base path (relative to project root)
# Compute project root as two levels up from this script (repo root).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Prefer `building/Building` at repo root, but fall back to `data/building/Building`
default_build_base = os.path.join(PROJECT_ROOT, "building", "Building")
alt_build_base = os.path.join(PROJECT_ROOT, "data", "building", "Building")

if os.path.exists(default_build_base):
    build_base = default_build_base
elif os.path.exists(alt_build_base):
    build_base = alt_build_base
else:
    raise FileNotFoundError(
        f"Building folder not found: tried {default_build_base} and {alt_build_base}"
    )

script_path = os.path.join(build_base, "0000000", "xml2csv.py")

if not os.path.exists(script_path):
    raise FileNotFoundError(f"xml2csv converter not found: {script_path}")

# Get all subdirectories except 0000000
subdirs = [d for d in os.listdir(build_base) 
           if os.path.isdir(os.path.join(build_base, d)) and d != "0000000"]

subdirs.sort()

# Filter to only process folders without CSVs
subdirs_to_process = []
for subdir in subdirs:
    folder_path = os.path.join(build_base, subdir)
    csv_files = glob.glob(os.path.join(folder_path, "*.csv"))
    if not csv_files:
        subdirs_to_process.append(subdir)

total = len(subdirs_to_process)
print(f"Found {total} directories without CSV to process\n")

for idx, subdir in enumerate(subdirs_to_process, 1):
    folder_path = os.path.join(build_base, subdir)
    print(f"[{idx}/{total}] Processing {subdir}...")
    
    try:
        result = subprocess.run(
            [sys.executable, script_path, folder_path],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout per folder
        )
        
        if result.returncode == 0:
            print(f"  [OK] Success")
            if "Done:" in result.stdout:
                print(f"    {result.stdout.split('Done:')[1].strip()[:100]}")
        else:
            print(f"  [ERROR] {result.stderr[:200]}")
    
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] Processing took too long")
    except Exception as e:
        print(f"  [EXCEPTION] {str(e)[:100]}")

print("\n" + "="*50)
print("All folders processed!")
