#!/usr/bin/env python3
"""
rewrite_alternative_wikidata_idno.py

Transforms only:
  <idno type="alternative_wikidata">Q...</idno>
into:
  <idno type="wikidata" subtype="alternative">Q...</idno>

Everything else remains unchanged.

Usage:
  python3 rewrite_alternative_wikidata_idno.py INPUT_DIR OUTPUT_DIR
"""

import sys
from pathlib import Path
from lxml import etree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {"tei": TEI_NS}

def process_file(in_path: Path, out_path: Path) -> int:
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(in_path), parser)
    root = tree.getroot()

    changed = 0
    # Only TEI idno elements with @type="alternative_wikidata"
    for idno in root.xpath(".//tei:idno[@type='alternative_wikidata']", namespaces=NSMAP):
        # Set the new type/subtype exactly as requested
        idno.set("type", "wikidata")
        idno.set("subtype", "alternative")
        changed += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out_path), encoding="UTF-8", xml_declaration=True, pretty_print=True)
    return changed

def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python3 rewrite_alternative_wikidata_idno.py INPUT_DIR OUTPUT_DIR")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not input_dir.is_dir():
        print(f"ERROR: {input_dir} is not a directory")
        sys.exit(1)

    total_files = 0
    total_changed = 0

    for in_path in sorted(input_dir.rglob("*.xml")):
        rel = in_path.relative_to(input_dir)
        out_path = output_dir / rel
        total_files += 1
        total_changed += process_file(in_path, out_path)

    print(f"Processed {total_files} XML files. Rewritten <idno> elements: {total_changed}")

if __name__ == "__main__":
    main()
