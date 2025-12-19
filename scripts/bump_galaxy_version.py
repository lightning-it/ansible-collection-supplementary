#!/usr/bin/env python3

import sys, yaml
ver = sys.argv[1]
with open("galaxy.yml") as f:
    data = yaml.safe_load(f)
data["version"] = ver
with open("galaxy.yml", "w") as f:
    yaml.safe_dump(data, f, sort_keys=False)
print(f"Updated galaxy.yml to {ver}")
