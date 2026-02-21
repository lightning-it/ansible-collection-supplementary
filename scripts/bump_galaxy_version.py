#!/usr/bin/env python3

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(
    r"^(?P<indent>\s*)version\s*:\s*(?P<quote>['\"]?)(?P<value>[^'\"\n#]*)(?P=quote)(?P<comment>\s+#.*)?$"
)

def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: bump_galaxy_version.py <version>", file=sys.stderr)
        return 2

    version = sys.argv[1]
    galaxy_path = Path("galaxy.yml")

    try:
        lines = galaxy_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        print("ERROR: galaxy.yml not found in current directory.", file=sys.stderr)
        return 1

    updated = False
    for idx, line in enumerate(lines):
        line_no_eol = line.rstrip("\r\n")
        line_ending = line[len(line_no_eol):]
        match = VERSION_RE.match(line_no_eol)
        if not match:
            continue
        indent = match.group("indent")
        quote = match.group("quote") or ""
        comment = match.group("comment") or ""
        lines[idx] = f"{indent}version: {quote}{version}{quote}{comment}{line_ending}"
        updated = True
        break

    if not updated:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] = lines[-1] + "\n"
        lines.append(f"version: {version}\n")

    galaxy_path.write_text("".join(lines), encoding="utf-8")
    print(f"Updated galaxy.yml to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
