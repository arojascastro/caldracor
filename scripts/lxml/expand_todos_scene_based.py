#!/usr/bin/env python3
"""
expand_todos_scene_based.py

Scene-based expansion of sp[@who='#todos'] and sp[@who='#todas'] in TEI plays (CalDraCor style).

- For each <div type="scene">:
    * Collects all @who IDs appearing in <sp> (excluding '#todos' and '#todas').
    * For each <sp> where @who contains '#todos':
        - If it's not a "crowd/offstage" case:
            -> Replaces '#todos' by the set of present IDs in that scene (all sexes),
               or, if empty, by the present IDs of the previous scene in the same act (fallback).
    * For each <sp> where @who contains '#todas':
        - If it's not a "crowd/offstage" case:
            -> Replaces '#todas' by the set of present IDs in that scene whose @sex='FEMALE',
               or, if empty, by the female IDs from the previous scene in the same act (fallback).

    * If it looks like an offstage/crowd "Dentro" case:
        -> Leaves '#todos' / '#todas' as-is.

- Writes transformed TEI files to an output directory.
- Writes a CSV log with one row per <sp> that contained '#todos' or '#todas'.

Features:
- Only expands to IDs that exist in <listPerson> (<person> or <personGrp>).
- Uses @sex on <person> to select candidates for '#todas'.
- Robust ignoring of generic IDs like 'músico', 'música', 'acompañamiento', 'uno-1', etc.
- Keeps 'crowd/offstage' cases unexpanded.
- Uses scene-fallback within the same act when present_ids is empty.
- Logs all decisions in a CSV, including present_ids_count.
"""

import csv
import sys
import unicodedata
from pathlib import Path

from lxml import etree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {"tei": TEI_NS}
XMLID = "{http://www.w3.org/XML/1998/namespace}id"

# ----------------------------------------------------------------------
# CONFIGURACIÓN EDITORIAL
# ----------------------------------------------------------------------

def strip_accents(s: str) -> str:
    """Elimina tildes/acentos de una cadena Unicode."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

def is_ignored_id(token: str) -> bool:
    """
    Decide si un ID debe ser ignorado como candidato en #todos/#todas.

    Lógica:
    - Normaliza a minúsculas.
    - Elimina tildes.
    - Ignora si empieza por:
      '#dentro', '#uno', '#unos', '#otros',
      '#musico', '#musica', '#musicos',
      '#acompan' (acompañamiento, acompanamiento, etc.).
    Esto cubre variantes con sufijos tipo '-1', '-2', etc.
    """
    if not token:
        return False

    t = token.strip()
    # Normalizamos: NFC, minúsculas, sin acentos
    t = unicodedata.normalize("NFC", t).lower()
    t_noacc = strip_accents(t)

    prefixes = (
        "#dentro",
        "#uno",
        "#unos",
        "#otros",
        "#musico",
        "#musica",
        "#musicos",
        "#acompan",   # acompañamiento, acompanamiento, etc.
    )

    return any(t_noacc.startswith(pref) for pref in prefixes)


# Palabras clave en <stage> inmediatamente anterior que indican "crowd/offstage"
CROWD_STAGE_KEYWORDS = {
    "dentro",
    # puedes añadir: "gente", "alboroto", "ruido", etc.
}


# ----------------------------------------------------------------------
# FUNCIONES AUXILIARES
# ----------------------------------------------------------------------

def tokenize_who(who_value: str):
    """Split @who attribute into tokens (keep the leading '#')."""
    if not who_value:
        return []
    return [t for t in who_value.strip().split() if t]


def get_valid_speaker_ids_and_sex(root):
    """
    Build:
    - a set of valid speaker IDs (from <listPerson>: <person>, <personGrp>) as '#xmlid'
    - a dict sex_by_id: '#xmlid' -> 'MALE' / 'FEMALE' / None

    For <personGrp> we usually won't have @sex, so it will be None.
    """
    valid_ids = set()
    sex_by_id = {}

    persons = root.xpath(
        ".//tei:listPerson//tei:person | .//tei:listPerson//tei:personGrp",
        namespaces=NSMAP,
    )
    for el in persons:
        xmlid = el.get(XMLID)
        if not xmlid:
            continue
        key = f"#{xmlid}"
        valid_ids.add(key)

        # Solo <person> suele tener @sex; en <personGrp> normalmente None
        sex_attr = el.get("sex")
        if sex_attr is not None:
            sex_by_id[key] = sex_attr.upper()
        else:
            sex_by_id[key] = None

    return valid_ids, sex_by_id


def get_scene_present_ids(scene_el, valid_ids):
    """
    Collect all IDs that appear in @who of <sp> inside this scene,
    excluding '#todos' and '#todas' and any ID not in valid_ids
    or explicitly ignored.
    """
    present = set()
    for sp in scene_el.xpath(".//tei:sp[@who]", namespaces=NSMAP):
        who_val = sp.get("who", "").strip()
        tokens = tokenize_who(who_val)
        for t in tokens:
            if t in ("#todos", "#todas"):
                continue
            if is_ignored_id(t):
                continue
            if t not in valid_ids:
                # ID no definido en listPerson: lo ignoramos para la expansión.
                continue
            present.add(t)
    return present


def is_crowd_or_offstage(sp_el):
    """
    Heuristic: decide if an sp[@who contains '#todos'/'#todas'] looks like anonymous crowd/offstage.

    Rule:
    - If immediately previous element sibling is <stage> and its text
      contains any keyword in CROWD_STAGE_KEYWORDS (case-insensitive),
      treat as crowd/offstage.
    """
    prev = sp_el.getprevious()
    # Saltar nodos de texto en blanco
    while prev is not None and not isinstance(prev.tag, str):
        prev = prev.getprevious()

    if prev is not None and ET.QName(prev).localname == "stage":
        text = "".join(prev.itertext()).strip().lower()
        for kw in CROWD_STAGE_KEYWORDS:
            if kw in text:
                return True

    return False


def sample_sp_text(sp_el, max_len=80):
    """Return a small text snippet from the first <l> inside this sp."""
    first_l = sp_el.xpath(".//tei:l", namespaces=NSMAP)
    if not first_l:
        return ""
    txt = " ".join(first_l[0].itertext()).strip()
    if len(txt) > max_len:
        txt = txt[: max_len - 3] + "..."
    return txt


def process_special_sp(sp, input_filename, scene_n, idx,
                       present_ids, fallback_ids, sex_by_id, log_rows):
    """
    Maneja un <sp> que contiene '#todos' o '#todas', usando:
    - present_ids: IDs presentes en la escena
    - fallback_ids: IDs de la escena anterior (mismo acto) si present_ids está vacío
    """
    who_val = sp.get("who", "")
    tokens = tokenize_who(who_val)

    has_todos = "#todos" in tokens
    has_todas = "#todas" in tokens
    snippet = sample_sp_text(sp)
    crowd = is_crowd_or_offstage(sp)

    # default values
    new_who_str = who_val
    present_str = ""
    present_count = 0
    action = "no_change"

    # Identificar etiqueta objetivo
    target_label = None
    if has_todos and not has_todas:
        target_label = "#todos"
    elif has_todas and not has_todos:
        target_label = "#todas"
    elif has_todos and has_todas:
        # Caso muy raro; lo marcamos en el log
        target_label = "both"

    # Filtramos también el fallback para excluir IDs ignorados
    filtered_fallback = {pid for pid in fallback_ids if not is_ignored_id(pid)}

    # seleccionamos el conjunto base: primero escena, si vacío, fallback filtrado
    base_ids = present_ids if present_ids else filtered_fallback

    if target_label is None:
        action = "ignored_no_todos_todas"

    else:
        if crowd:
            if target_label == "#todos":
                action = "kept_as_todos_crowd_offstage"
            elif target_label == "#todas":
                action = "kept_as_todas_crowd_offstage"
            else:
                action = "kept_as_both_crowd_offstage"
        else:
            if base_ids:
                # Tenemos algo con lo que trabajar: escena o fallback
                candidate_ids = base_ids

                if target_label in ("#todas", "both"):
                    female_ids = {
                        pid
                        for pid in candidate_ids
                        if sex_by_id.get(pid) == "FEMALE"
                    }
                    if female_ids:
                        sorted_ids = sorted(female_ids)
                        other_tokens = [
                            t for t in tokens if t not in ("#todas", "#todos")
                        ]
                        # normalizar: eliminar duplicados y ordenar
                        final_tokens = sorted(set(other_tokens + sorted_ids))
                        new_who_str = " ".join(final_tokens)
                        sp.set("who", new_who_str)

                        # sp.set("resp", "#rojas")
                        # sp.set("cert", "medium")

                        if present_ids:
                            action = "expanded_todas_to_scene_female_ids"
                        else:
                            action = "expanded_todas_to_fallback_female_ids"

                        present_str = " ".join(sorted_ids)
                        present_count = len(sorted_ids)
                    else:
                        action = "todas_no_female_candidates"

                if target_label == "#todos":
                    sorted_ids = sorted(candidate_ids)
                    other_tokens = [t for t in tokens if t != "#todos"]
                    final_tokens = sorted(set(other_tokens + sorted_ids))
                    new_who_str = " ".join(final_tokens)
                    sp.set("who", new_who_str)

                    # sp.set("resp", "#rojas")
                    # sp.set("cert", "medium")

                    if present_ids:
                        action = "expanded_todos_to_scene_present_ids"
                    else:
                        action = "expanded_todos_to_fallback_present_ids"

                    present_str = " ".join(sorted_ids)
                    present_count = len(sorted_ids)
            else:
                # ni escena ni fallback tienen candidatos
                if target_label == "#todos":
                    action = "todos_only_in_scene_no_fallback"
                elif target_label == "#todas":
                    action = "todas_only_in_scene_no_fallback"
                else:
                    action = "todos_todas_only_in_scene_no_fallback"

    log_rows.append(
        {
            "file": input_filename,
            "scene_n": scene_n,
            "sp_index_in_scene": idx,
            "action": action,
            "crowd_or_offstage": crowd,
            "present_ids": present_str,
            "present_ids_count": present_count,
            "new_who": new_who_str,
            "snippet": snippet,
        }
    )


def process_file(input_path: Path, output_path: Path, log_rows: list):
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(input_path), parser)
    root = tree.getroot()

    # Conjunto de IDs válidos y mapa de sexo según <listPerson>
    valid_ids, sex_by_id = get_valid_speaker_ids_and_sex(root)

    # Trabajamos acto por acto para que el "fallback" no salte de un acto a otro
    acts = root.xpath(".//tei:div[@type='act']", namespaces=NSMAP)
    if not acts:
        # Si no hay <div type="act">, usamos el root como contenedor de escenas
        acts = [root]

    for act in acts:
        scenes = act.xpath(".//tei:div[@type='scene']", namespaces=NSMAP)

        # memoria de la escena anterior en ESTE acto
        prev_scene_present_ids = set()

        for scene in scenes:
            scene_n = scene.get("n", "")
            present_ids = get_scene_present_ids(scene, valid_ids)

            # Si esta escena no tiene candidatos, usamos como fallback los de la escena anterior
            if present_ids:
                fallback_ids = present_ids
            else:
                fallback_ids = prev_scene_present_ids

            # All <sp> in this scene that contain '#todos' or '#todas' in @who
            sps_special = scene.xpath(
                ".//tei:sp[contains(@who, '#todos') or contains(@who, '#todas')]",
                namespaces=NSMAP,
            )

            for idx, sp in enumerate(sps_special, start=1):
                process_special_sp(
                    sp=sp,
                    input_filename=input_path.name,
                    scene_n=scene_n,
                    idx=idx,
                    present_ids=present_ids,
                    fallback_ids=fallback_ids,
                    sex_by_id=sex_by_id,
                    log_rows=log_rows,
                )

            # Al final de la escena, actualizamos la memoria para la siguiente
            prev_scene_present_ids = present_ids if present_ids else prev_scene_present_ids

    # Escribir TEI transformado
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(output_path),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 expand_todos_scene_based.py INPUT_DIR OUTPUT_DIR")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not input_dir.is_dir():
        print(f"ERROR: {input_dir} is not a directory")
        sys.exit(1)

    log_rows = []

    for xml_file in sorted(input_dir.glob("*.xml")):
        rel = xml_file.name
        out_path = output_dir / rel
        print(f"Processing {xml_file} -> {out_path}")
        process_file(xml_file, out_path, log_rows)

    # Escribir log CSV
    log_path = output_dir / "expand_todos_log.csv"
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "scene_n",
                "sp_index_in_scene",
                "action",
                "crowd_or_offstage",
                "present_ids",
                "present_ids_count",
                "new_who",
                "snippet",
            ],
        )
        writer.writeheader()
        for row in log_rows:
            writer.writerow(row)

    print(f"\nDone. Log written to: {log_path}")


if __name__ == "__main__":
    main()
