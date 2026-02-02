#!/usr/bin/env python3

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(
    r"^(?P<indent>\s*)version\s*:\s*(?P<quote>['\"]?)(?P<value>[^'\"]*)(?P=quote)(?P<comment>\s+#.*)?$",
    re.M,
)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: bump_galaxy_version.py <version>", file=sys.stderr)
        return 2

    version = sys.argv[1]
    galaxy_path = Path("galaxy.yml")

    try:
        text = galaxy_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print("ERROR: galaxy.yml not found in current directory.", file=sys.stderr)
        return 1

    match = VERSION_RE.search(text)
    if match:
        def repl(m: re.Match) -> str:
            indent = m.group("indent")
            quote = m.group("quote") or ""
            comment = m.group("comment") or ""
            return f"{indent}version: {quote}{version}{quote}{comment}"

        new_text = VERSION_RE.sub(repl, text, count=1)
    else:
        new_text = text
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += f"version: {version}\n"

    galaxy_path.write_text(new_text, encoding="utf-8")
    print(f"Updated galaxy.yml to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
