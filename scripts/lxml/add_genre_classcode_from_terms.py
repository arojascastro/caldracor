#!/usr/bin/env python3
"""
add_genre_classcode_from_terms.py

Goal:
- Leer un CSV de mapeo CalDraCor → Wikidata (género).
- Para cada TEI:
    * Encontrar <term source="#kroll" type="main"> dentro de <textClass>.
    * Buscar ese término en el CSV.
    * Si hay mapeo, añadir/actualizar:

        <classCode scheme="http://www.wikidata.org/entity/">Q...</classCode>

      dentro de <textClass>.

- No toca los <term>; solo añade (o sustituye) <classCode> con scheme Wikidata.

Usage:
    python3 add_genre_classcode_from_terms.py INPUT_DIR OUTPUT_DIR MAPPING_CSV
"""

import csv
import sys
import unicodedata
from pathlib import Path

from lxml import etree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {"tei": TEI_NS}


def norm_text(s: str) -> str:
    """Lowercase + quita acentos para comparaciones robustas."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", s).lower()
    # quitar acentos
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def load_mapping(csv_path: Path):
    """
    Lee CSV con columnas:
        main_term, wikidata_qid, normalized_genre

    Devuelve:
        mapping: dict[normalized_main_term] -> {"qid": ..., "label": ...}
    """
    mapping = {}
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_term = (row.get("main_term") or "").strip()
            qid = (row.get("wikidata_qid") or "").strip()
            label = (row.get("normalized_genre") or "").strip()
            if not raw_term or not qid:
                continue
            key = norm_text(raw_term)
            mapping[key] = {"qid": qid, "label": label}
    return mapping


def find_textclass(root):
    """Devuelve el primer <textClass> dentro de <teiHeader>/<profileDesc>, o None."""
    tcs = root.xpath(
        ".//tei:teiHeader//tei:profileDesc//tei:textClass",
        namespaces=NSMAP,
    )
    return tcs[0] if tcs else None


def get_main_genre_term(textclass_el):
    """
    Busca <term source="#kroll" type="main"> dentro de <textClass>.
    Devuelve (raw_text, norm_text) o (None, None) si no hay.
    """
    terms = textclass_el.xpath(
        ".//tei:keywords/tei:term[@source='#kroll' and @type='main']",
        namespaces=NSMAP,
    )
    if not terms:
        return None, None
    term_el = terms[0]
    raw = " ".join(term_el.itertext()).strip()
    return raw, norm_text(raw)


def set_wikidata_classcode(textclass_el, qid: str):
    """
    Elimina cualquier <classCode> existente con scheme="http://www.wikidata.org/entity/"
    y añade uno nuevo con el Q-id dado.
    """
    existing = textclass_el.xpath(
        "tei:classCode[@scheme='http://www.wikidata.org/entity/']",
        namespaces=NSMAP,
    )
    for el in existing:
        textclass_el.remove(el)

    cc = ET.Element("{%s}classCode" % TEI_NS)
    cc.set("scheme", "http://www.wikidata.org/entity/")
    cc.text = qid
    textclass_el.append(cc)


def process_file(input_path: Path, output_path: Path, mapping: dict, log_rows: list):
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(input_path), parser)
    root = tree.getroot()

    textclass_el = find_textclass(root)
    if textclass_el is None:
        log_rows.append({
            "file": input_path.name,
            "main_term_raw": "",
            "main_term_norm": "",
            "match_type": "no_textClass",
            "wikidata_qid": "",
            "normalized_genre": "",
            "action": "skipped",
        })
        # escribir igualmente el XML de salida idéntico al original
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(
            str(output_path),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
        return

    raw_term, norm_term = get_main_genre_term(textclass_el)
    if not raw_term:
        log_rows.append({
            "file": input_path.name,
            "main_term_raw": "",
            "main_term_norm": "",
            "match_type": "no_main_term",
            "wikidata_qid": "",
            "normalized_genre": "",
            "action": "skipped",
        })
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(
            str(output_path),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
        return

    # 1) intento: match exacto normalizado
    match_type = "no_match"
    qid = ""
    label = ""

    if norm_term in mapping:
        qid = mapping[norm_term]["qid"]
        label = mapping[norm_term]["label"]
        match_type = "exact_norm_match"
    else:
        # 2) intento: heurístico: alguna clave contenida en term_norm (por si tienes 'comedia cómica palatina', etc.)
        for key, val in mapping.items():
            if key and key in norm_term:
                qid = val["qid"]
                label = val["label"]
                match_type = f"substring_match:{key}"
                break

    if not qid:
        # Sin mapeo, no tocamos nada
        log_rows.append({
            "file": input_path.name,
            "main_term_raw": raw_term,
            "main_term_norm": norm_term,
            "match_type": match_type,
            "wikidata_qid": "",
            "normalized_genre": "",
            "action": "skipped",
        })
    else:
        # Tenemos Q-id: añadimos/sustituimos classCode
        set_wikidata_classcode(textclass_el, qid)
        log_rows.append({
            "file": input_path.name,
            "main_term_raw": raw_term,
            "main_term_norm": norm_term,
            "match_type": match_type,
            "wikidata_qid": qid,
            "normalized_genre": label,
            "action": "set_classCode",
        })

    # Escribimos el TEI (conservando PIs, etc.)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(output_path),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 add_genre_classcode_from_terms.py INPUT_DIR OUTPUT_DIR MAPPING_CSV")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    mapping_csv = Path(sys.argv[3])

    if not input_dir.is_dir():
        print(f"ERROR: {input_dir} is not a directory")
        sys.exit(1)
    if not mapping_csv.is_file():
        print(f"ERROR: {mapping_csv} is not a file")
        sys.exit(1)

    mapping = load_mapping(mapping_csv)
    print(f"Loaded {len(mapping)} genre mappings from {mapping_csv}")

    log_rows = []

    for xml_file in sorted(input_dir.glob("*.xml")):
        rel = xml_file.name
        out_path = output_dir / rel
        print(f"Processing {xml_file} -> {out_path}")
        process_file(xml_file, out_path, mapping, log_rows)

    # Escribir log
    log_path = output_dir / "add_genre_classcode_log.csv"
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "main_term_raw",
                "main_term_norm",
                "match_type",
                "wikidata_qid",
                "normalized_genre",
                "action",
            ],
        )
        writer.writeheader()
        for row in log_rows:
            writer.writerow(row)

    print(f"\nDone. Log written to: {log_path}")


if __name__ == "__main__":
    main()
