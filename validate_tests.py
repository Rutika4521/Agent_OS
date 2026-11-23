"""
Quick syntax validator for all test files.
Run: python validate_tests.py
"""
import sys
import ast
import os

TEST_DIR = r"C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os\tests"

errors = []
files_checked = 0

for fname in os.listdir(TEST_DIR):
    if not fname.endswith(".py"):
        continue
    fpath = os.path.join(TEST_DIR, fname)
    with open(fpath, encoding="utf-8") as f:
        source = f.read()
    try:
        ast.parse(source)
        files_checked += 1
        print(f"  OK  {fname}")
    except SyntaxError as e:
        errors.append((fname, str(e)))
        print(f"  FAIL {fname}: {e}")

print(f"\n{files_checked} files checked, {len(errors)} syntax errors.")
if errors:
    sys.exit(1)
