#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
APP = ROOT / ".app.json"


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"plugin_asdk_app_[A-Za-z0-9_-]+", sys.argv[1]):
        print("Usage: python scripts/configure_plugin.py plugin_asdk_app_<technical-id>")
        return 2
    technical_id = sys.argv[1]

    APP.write_text(
        json.dumps({"apps": {"bilibili-video-reader": {"id": technical_id}}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["apps"] = "./.app.json"
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Configured {technical_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
