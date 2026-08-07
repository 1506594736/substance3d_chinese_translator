#!/usr/bin/env python3
"""Summarize QGraphicsScene data from SD widget-sniffer JSON reports."""

import json
import pprint
import sys
from pathlib import Path


def main(paths):
    for path_text in paths:
        path = Path(path_text)
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n=== {path.name} records={payload.get('record_count')} ===")
        for record in payload.get("records", []):
            graphics = record.get("graphics_scene")
            if not graphics or "GraphView" not in record.get("cpp_class", ""):
                continue
            print(
                "VIEW",
                record.get("cpp_class"),
                "origin=",
                record.get("origin"),
                "items=",
                graphics.get("item_count"),
                "error=",
                graphics.get("inspection_error"),
            )
            print("TYPES")
            pprint.pp(graphics.get("item_types", []), width=180, sort_dicts=False)
            print("CURSOR")
            pprint.pp(
                graphics.get("items_at_cursor", []),
                width=180,
                sort_dicts=False,
            )
            print("TYPE EXAMPLES WITH TEXT OR DATA")
            examples = [
                item
                for item in graphics.get("type_examples", [])
                if item.get("text") or item.get("data_roles")
            ]
            pprint.pp(examples, width=180, sort_dicts=False)
            print("ALL TEXT ITEMS")
            pprint.pp(
                graphics.get("text_items", []),
                width=180,
                sort_dicts=False,
            )


if __name__ == "__main__":
    main(sys.argv[1:])
