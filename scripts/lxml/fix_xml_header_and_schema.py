#!/usr/bin/env python3
"""
fix_xml_header_and_schema.py

Normaliza la cabecera de todos los TEI:

- Garantiza declaración XML:
    <?xml version="1.0" encoding="UTF-8"?>

- Sustituye cualquier xml-model existente (o ausencia de él) por UNA sola PI:
    <?xml-model href="http://www.tei-c.org/release/xml/tei/custom/schema/relaxng/tei_all.rng"
                type="application/xml"
                schematypens="http://relaxng.org/ns/structure/1.0"?>

No añade Schematron (no se usa en este corpus).

INPUT:  directorio con TEI XML (p.ej. caldracor)
OUTPUT: directorio con TEI corregidos (p.ej. lxml-output)
"""

import sys
from pathlib import Path

from lxml import etree as ET


def fix_file(input_path: Path, output_path: Path):
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(input_path), parser)
    root = tree.getroot()

    # --- CLAVE: crear un NUEVO root sin hermanos ni PIs anteriores ---
    # Serializamos solo el elemento <TEI> y lo volvemos a parsear
    root_bytes = ET.tostring(root)
    new_root = ET.fromstring(root_bytes)

    # Creamos un nuevo árbol con este root limpio
    new_tree = ET.ElementTree(new_root)

    # Creamos la nueva PI xml-model correcta
    pi_data = (
        'href="http://www.tei-c.org/release/xml/tei/custom/schema/relaxng/tei_all.rng" '
        'type="application/xml" '
        'schematypens="http://relaxng.org/ns/structure/1.0"'
    )
    pi_rng = ET.ProcessingInstruction("xml-model", pi_data)

    # Insertamos la PI justo antes del nuevo root <TEI>
    new_root.addprevious(pi_rng)

    # Escribimos salida con declaración XML
    output_path.parent.mkdir(parents=True, exist_ok=True)
    new_tree.write(
        str(output_path),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 fix_xml_header_and_schema.py INPUT_DIR OUTPUT_DIR")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not input_dir.is_dir():
        print(f"ERROR: {input_dir} is not a directory")
        sys.exit(1)

    for xml_file in sorted(input_dir.glob("*.xml")):
        rel = xml_file.name
        out_path = output_dir / rel
        print(f"Processing {xml_file} -> {out_path}")
        fix_file(xml_file, out_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
