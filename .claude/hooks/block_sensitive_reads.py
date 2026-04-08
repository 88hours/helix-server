"""
PreToolUse hook — blocks Claude from reading or searching sensitive files.

Handles Read (file_path), Grep (path), and Glob (pattern + path).
Receives a JSON payload on stdin; outputs a block decision and exits 2 if matched.
"""

import json
import re
import sys

SENSITIVE_PATTERNS = [
    r"\.env$",           # .env
    r"\.env\.",          # .env.production, .env.local, etc.
    r"\.pem$",           # PEM keys/certs
    r"\.p12$",           # PKCS#12 bundles
    r"\.pfx$",           # PFX key files
    r"(^|[\\/])\.key$",  # bare .key files
    r"private[-_]?key",  # private-key, private_key, privatekey
]


def is_sensitive(value):
    if not value:
        return None
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            return pattern
    return None


def block(path, pattern):
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"Blocked: '{path}' matches sensitive file pattern '{pattern}'. "
            "If you need this file's contents, read it manually in your terminal."
        )
    }))
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    inp = data.get("tool_input", {})

    if tool_name == "Read":
        path = inp.get("file_path", "")
        matched = is_sensitive(path)
        if matched:
            block(path, matched)

    elif tool_name == "Grep":
        # Block if the search is scoped to a sensitive file path
        path = inp.get("path", "")
        matched = is_sensitive(path)
        if matched:
            block(path, matched)

    elif tool_name == "Glob":
        # Block if the glob pattern itself targets sensitive files,
        # or if the search directory is a sensitive path
        for value in (inp.get("pattern", ""), inp.get("path", "")):
            matched = is_sensitive(value)
            if matched:
                block(value, matched)

    sys.exit(0)


if __name__ == "__main__":
    main()
