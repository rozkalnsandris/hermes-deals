#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print(json.dumps({"continue": True}))
    raise SystemExit(0)

# Prevent continuation loops: a failed gate gets one automatic repair pass.
if data.get("stop_hook_active"):
    print(json.dumps({"continue": True}))
    raise SystemExit(0)


def run(*args):
    return subprocess.run(args, text=True, capture_output=True)

root_p = run("git", "rev-parse", "--show-toplevel")
if root_p.returncode != 0:
    print(json.dumps({"continue": True}))
    raise SystemExit(0)
root = Path(root_p.stdout.strip())
os.chdir(root)

issues = []
for args, label in [
    (("git", "diff", "--check"), "unstaged diff"),
    (("git", "diff", "--cached", "--check"), "staged diff"),
]:
    p = run(*args)
    if p.returncode != 0:
        detail = (p.stdout + p.stderr).strip()[:1200]
        issues.append(f"{label} failed git diff --check: {detail}")

tracked = run("git", "ls-files")
if tracked.returncode == 0:
    forbidden = []
    for raw in tracked.stdout.splitlines():
        name = Path(raw).name.lower()
        if name in {".env", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"} or name.endswith((".pem", ".key", ".p12", ".pfx")):
            forbidden.append(raw)
    if forbidden:
        issues.append("secret-like files are tracked: " + ", ".join(forbidden[:20]))

if issues:
    reason = "Hermes Deals stop gate found issues. Fix them before finishing:\n- " + "\n- ".join(issues)
    print(json.dumps({"decision": "block", "reason": reason}))
else:
    print(json.dumps({"continue": True}))
