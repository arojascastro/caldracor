#!/usr/bin/env python3
"""
apply_person_wikidata_and_role.py (v3)

Lee un CSV maestro y aplica en TEI <listPerson>/<person>:

- wikidata_qid -> <idno type="wikidata">Q...</idno>
- alternative_wikidata_qid -> <idno type="alternative_wikidata">Q...</idno>
- role -> <trait type="role"><desc>...</desc></trait>
- secondary_role -> <trait type="secondary_role"><desc>...</desc></trait>

Reglas:
- Ignora columnas status y notes.
- No toca <trait> existentes con @resp/@source (u otros tipos). Solo gestiona los
  <trait> con @type="role" y @type="secondary_role".
- No toca persName/@ref.
- Si un campo viene vacío en el CSV, elimina el elemento controlado correspondiente
  si existía (idno/trait), sin afectar otros elementos.

Uso:
    python3 apply_person_wikidata_and_role.py INPUT_DIR OUTPUT_DIR MAPPING_CSV
"""

import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {"tei": TEI_NS}
XMLID = "{http://www.w3.org/XML/1998/namespace}id"


def _t(tag: str) -> str:
    return f"{{{TEI_NS}}}{tag}"


def load_mapping(csv_path: Path) -> List[Dict[str, str]]:
    """
    Devuelve filas útiles del CSV. Ignora status y notes.
    Requiere: file, xml_id.
    """
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            file_ = (row.get("file") or "").strip()
            xml_id = (row.get("xml_id") or "").strip()

            if not file_ or not xml_id:
                continue

            out = {
                "file": file_,
                "xml_id": xml_id,
                "persName": (row.get("persName") or "").strip(),
                "wikidata_qid": (row.get("wikidata_qid") or "").strip(),
                "alternative_wikidata_qid": (row.get("alternative_wikidata_qid") or "").strip(),
                "role": (row.get("role") or "").strip(),
                "secondary_role": (row.get("secondary_role") or "").strip(),
            }

            # Solo procesar si hay algo que aplicar (o borrar)
            if out["wikidata_qid"] or out["alternative_wikidata_qid"] or out["role"] or out["secondary_role"]:
                rows.append(out)

    return rows


def find_child(parent: ET._Element, tag: str, **attrs) -> Optional[ET._Element]:
    """
    Encuentra un hijo directo con el tag y atributos dados.
    """
    for ch in parent:
        if ch.tag != _t(tag):
            continue
        ok = True
        for k, v in attrs.items():
            if ch.get(k) != v:
                ok = False
                break
        if ok:
            return ch
    return None


def ensure_idno(person_el: ET._Element, idno_type: str, value: str) -> Tuple[str, str]:
    """
    Crea/actualiza/elimina <idno type="...">value</idno>.
    Devuelve (old, new).
    """
    el = find_child(person_el, "idno", type=idno_type)
    old = (el.text or "").strip() if el is not None and el.text else ""
    value = (value or "").strip()

    if not value:
        if el is not None:
            person_el.remove(el)
        return old, ""

    if el is None:
        el = ET.Element(_t("idno"))
        el.set("type", idno_type)
        el.text = value
        # insertar tras el último <persName> si existe
        children = list(person_el)
        last_pers_idx = -1
        for i, ch in enumerate(children):
            if ch.tag == _t("persName"):
                last_pers_idx = i
        insert_pos = last_pers_idx + 1 if last_pers_idx >= 0 else 0
        person_el.insert(insert_pos, el)
    else:
        el.text = value

    return old, value


def get_trait_value(trait_el: ET._Element) -> str:
    d = trait_el.find("tei:desc", namespaces=NSMAP)
    if d is None or d.text is None:
        return ""
    return d.text.strip()


def ensure_trait(person_el: ET._Element, trait_type: str, value: str) -> Tuple[str, str]:
    """
    Crea/actualiza/elimina <trait type="..."><desc>value</desc></trait>.
    Solo gestiona traits con @type = trait_type.
    Devuelve (old, new).
    """
    trait_el = find_child(person_el, "trait", type=trait_type)
    old = get_trait_value(trait_el) if trait_el is not None else ""
    value = (value or "").strip()

    if not value:
        if trait_el is not None:
            person_el.remove(trait_el)
        return old, ""

    if trait_el is None:
        trait_el = ET.Element(_t("trait"))
        trait_el.set("type", trait_type)
        desc_el = ET.SubElement(trait_el, _t("desc"))
        desc_el.text = value
        person_el.append(trait_el)
    else:
        desc_el = trait_el.find("tei:desc", namespaces=NSMAP)
        if desc_el is None:
            desc_el = ET.SubElement(trait_el, _t("desc"))
        desc_el.text = value

    return old, value


def process_file(
    input_dir: Path,
    output_dir: Path,
    file_name: str,
    targets: List[Dict[str, str]],
    log_rows: List[Dict[str, str]],
) -> None:
    xml_path = input_dir / file_name
    if not xml_path.is_file():
        for t in targets:
            log_rows.append({**t, "action": "file_not_found"})
        return

    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(xml_path), parser)
    root = tree.getroot()

    persons = root.xpath(".//tei:listPerson//tei:person", namespaces=NSMAP)
    person_by_id: Dict[str, ET._Element] = {}
    for p in persons:
        xid = p.get(XMLID)
        if xid:
            person_by_id[xid] = p

    for t in targets:
        xml_id = t["xml_id"]
        person_el = person_by_id.get(xml_id)
        if person_el is None:
            log_rows.append({**t, "action": "person_not_found"})
            continue

        old_wd, new_wd = ensure_idno(person_el, "wikidata", t["wikidata_qid"])
        old_alt, new_alt = ensure_idno(person_el, "alternative_wikidata", t["alternative_wikidata_qid"])
        old_role, new_role = ensure_trait(person_el, "role", t["role"])
        old_sec, new_sec = ensure_trait(person_el, "secondary_role", t["secondary_role"])

        changes = []
        if old_wd != new_wd:
            changes.append("idno:wikidata")
        if old_alt != new_alt:
            changes.append("idno:alternative_wikidata")
        if old_role != new_role:
            changes.append("trait:role")
        if old_sec != new_sec:
            changes.append("trait:secondary_role")

        log_rows.append(
            {
                **t,
                "old_wikidata": old_wd,
                "new_wikidata": new_wd,
                "old_alternative_wikidata": old_alt,
                "new_alternative_wikidata": new_alt,
                "old_role": old_role,
                "new_role": new_role,
                "old_secondary_role": old_sec,
                "new_secondary_role": new_sec,
                "action": "no_change" if not changes else "updated:" + ",".join(changes),
            }
        )

    output_path = output_dir / file_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path), encoding="UTF-8", xml_declaration=True, pretty_print=True)


def main() -> None:
    if len(sys.argv) != 4:
        print("Usage: python3 apply_person_wikidata_and_role.py INPUT_DIR OUTPUT_DIR MAPPING_CSV")
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

    mapping_rows = load_mapping(mapping_csv)
    print(f"Loaded {len(mapping_rows)} mapping rows from {mapping_csv}")

    by_file: Dict[str, List[Dict[str, str]]] = {}
    for r in mapping_rows:
        by_file.setdefault(r["file"], []).append(r)

    log_rows: List[Dict[str, str]] = []

    for file_name, targets in sorted(by_file.items()):
        print(f"Processing {file_name} ({len(targets)} persons)")
        process_file(input_dir, output_dir, file_name, targets, log_rows)

    log_path = output_dir / "apply_person_wikidata_and_role_log.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "file",
            "xml_id",
            "persName",
            "wikidata_qid",
            "alternative_wikidata_qid",
            "role",
            "secondary_role",
            "old_wikidata",
            "new_wikidata",
            "old_alternative_wikidata",
            "new_alternative_wikidata",
            "old_role",
            "new_role",
            "old_secondary_role",
            "new_secondary_role",
            "action",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in log_rows:
            for fn in fieldnames:
                row.setdefault(fn, "")
            writer.writerow(row)

    print(f"Done. Log written to: {log_path}")


if __name__ == "__main__":
    main()
