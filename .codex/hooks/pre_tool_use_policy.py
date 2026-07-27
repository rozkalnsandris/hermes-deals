#!/usr/bin/env python3
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
    raise SystemExit(0)

command = str((data.get("tool_input") or {}).get("command") or "")
patterns = [
    (r"(^|\s)git\s+reset\s+--hard\b", "git reset --hard can destroy uncommitted evidence"),
    (r"(^|\s)git\s+clean\s+-[^\n]*f", "git clean -f can delete untracked evidence"),
    (r"(^|\s)git\s+checkout\s+--\s+\.($|\s)", "bulk checkout can discard the working tree"),
    (r"(^|\s)docker(?:\s+compose|-compose)\s+down\b[^\n]*\s-v(?:\s|$)", "docker compose down -v can delete database volumes"),
    (r"(^|\s)docker\s+volume\s+(rm|prune)\b", "Docker volume deletion is destructive"),
    (r"rm\s+-[^\n]*r[^\n]*f[^\n]*\s+/(?:\s|$|\*)", "recursive deletion from filesystem root is blocked"),
]
for pattern, reason in patterns:
    if re.search(pattern, command, flags=re.IGNORECASE):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Hermes Deals safety policy: {reason}. Use a narrow, reviewable command instead."
            }
        }))
        raise SystemExit(0)

print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
