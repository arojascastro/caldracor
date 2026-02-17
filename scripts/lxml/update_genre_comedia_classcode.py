#!/usr/bin/env python3
"""
update_genre_comedia_classcode.py

Reemplaza todas las ocurrencias de:

    <classCode scheme="http://www.wikidata.org/entity/">Q40831</classCode>

por:

    <classCode scheme="http://www.wikidata.org/entity/">Q6592456</classCode>

en todos los ficheros .xml de INPUT_DIR.

Solo toca <classCode> con:
- @scheme exactamente "http://www.wikidata.org/entity/"
- texto exactamente "Q40831" (ignorando espacios alrededor)

Escribe los ficheros modificados en OUTPUT_DIR
y genera un log CSV con los cambios.

Uso:
    python3 update_genre_comedia_classcode.py INPUT_DIR OUTPUT_DIR
"""

import csv
import sys
from pathlib import Path
from lxml import etree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {"tei": TEI_NS}

OLD_QID = "Q40831"
NEW_QID = "Q6592456"
SCHEME_URI = "http://www.wikidata.org/entity/"


def process_file(input_path: Path, output_path: Path, log_rows: list):
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(input_path), parser)
    root = tree.getroot()

    # Seleccionamos solo classCode con el scheme que nos interesa
    classcodes = root.xpath(
        ".//tei:classCode[@scheme=$scheme]",
        namespaces=NSMAP,
        scheme=SCHEME_URI,
    )

    for el in classcodes:
        old_text = (el.text or "").strip()
        if old_text == OLD_QID:
            el.text = NEW_QID
            log_rows.append(
                {
                    "file": input_path.name,
                    "xpath": tree.getpath(el),
                    "old_value": old_text,
                    "new_value": NEW_QID,
                }
            )

    # Escribimos el resultado
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(output_path),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 update_genre_comedia_classcode.py INPUT_DIR OUTPUT_DIR")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not input_dir.is_dir():
        print(f"ERROR: {input_dir} is not a directory")
        sys.exit(1)

    log_rows = []

    for xml_file in sorted(input_dir.glob("*.xml")):
        out_path = output_dir / xml_file.name
        print(f"Processing {xml_file} -> {out_path}")
        process_file(xml_file, out_path, log_rows)

    # Log
    log_path = output_dir / "update_genre_comedia_classcode_log.csv"
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "xpath", "old_value", "new_value"],
        )
        writer.writeheader()
        for row in log_rows:
            writer.writerow(row)

    print(f"\nDone. Log written to: {log_path}")


if __name__ == "__main__":
    main()
