"""
Run this script from ANYWHERE to execute the Agent-OS test suite.
Usage: python run_tests.py
"""
import sys
import os
import subprocess

PROJECT_ROOT = r"C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os"

if not os.path.exists(PROJECT_ROOT):
    print(f"ERROR: Project not found at: {PROJECT_ROOT}")
    sys.exit(1)

src_dir = os.path.join(PROJECT_ROOT, "src")

env = os.environ.copy()
current_pythonpath = env.get("PYTHONPATH", "")
extra_paths = f"{src_dir}{os.pathsep}{PROJECT_ROOT}"
env["PYTHONPATH"] = f"{extra_paths}{os.pathsep}{current_pythonpath}" if current_pythonpath else extra_paths

print(f"Running tests from: {PROJECT_ROOT}")
print(f"PYTHONPATH includes: {extra_paths}")
print("=" * 60)

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    cwd=PROJECT_ROOT,
    env=env,
    text=True,
)
sys.exit(result.returncode)
