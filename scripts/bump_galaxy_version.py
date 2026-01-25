#!/usr/bin/env python3

import sys
from pathlib import Path

try:
    from ruamel.yaml import YAML
except ImportError as exc:
    raise SystemExit(
        "ERROR: ruamel.yaml is required to preserve galaxy.yml formatting. "
        "Install with: pip install ruamel.yaml"
    ) from exc


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: bump_galaxy_version.py <version>", file=sys.stderr)
        return 2

    version = sys.argv[1]
    galaxy_path = Path("galaxy.yml")

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.explicit_start = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    with galaxy_path.open("r", encoding="utf-8") as handle:
        data = yaml.load(handle) or {}

    data["version"] = version

    with galaxy_path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)

    print(f"Updated galaxy.yml to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
