#!/usr/bin/env python3
"""
fix_xml_declaration_only.py

Replace ONLY the exact XML declaration at the very start of each XML file:

    <?xml version='1.0' encoding='UTF-8'?>
->  <?xml version="1.0" encoding="utf-8"?>

No other bytes are changed. Files are copied to OUTPUT_DIR preserving
relative paths from INPUT_DIR.

Usage:
    python3 fix_xml_declaration_only.py INPUT_DIR OUTPUT_DIR
Example:
    python3 fix_xml_declaration_only.py caldracor lxml-output/xml-decl-fix
"""

import sys
from pathlib import Path

OLD_DECL = b"<?xml version='1.0' encoding='UTF-8'?>"
NEW_DECL = b'<?xml version="1.0" encoding="utf-8"?>'


def process_one_file(src: Path, dst: Path) -> tuple[bool, str]:
    data = src.read_bytes()

    changed = False
    if data.startswith(OLD_DECL):
        data = NEW_DECL + data[len(OLD_DECL):]
        changed = True

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)

    return changed, ("changed" if changed else "copied")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python3 fix_xml_declaration_only.py INPUT_DIR OUTPUT_DIR", file=sys.stderr)
        return 2

    input_dir = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()

    if not input_dir.is_dir():
        print(f"ERROR: INPUT_DIR is not a directory: {input_dir}", file=sys.stderr)
        return 2

    xml_files = sorted([p for p in input_dir.rglob("*.xml") if p.is_file()])

    total = 0
    changed_count = 0

    for src in xml_files:
        rel = src.relative_to(input_dir)
        dst = output_dir / rel

        changed, _status = process_one_file(src, dst)
        total += 1
        if changed:
            changed_count += 1

    print(f"Processed {total} XML files.")
    print(f"Declarations replaced in {changed_count} files.")
    print(f"Output written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
