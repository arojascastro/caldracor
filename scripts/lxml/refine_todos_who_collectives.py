#!/usr/bin/env python3
"""
refine_todos_who_collectives.py

Regla editorial:

- Cuando <speaker> contenga "TODOS" y además nombre explícitamente
  un colectivo/anónimo (MÚSICOS, MÚSICA, UNO/S, OTROS, etc.),
  entonces en @who se pueden incluir esos IDs (#musicos, #musica, #uno, #unos, #otros, #dentro, etc.).

- Cuando <speaker> contenga "TODOS" pero NO nombre explícitamente
  a ese colectivo, entonces esos IDs NO deberían aparecer en @who
  y se eliminan.

- Si <speaker> NO contiene "TODOS", NO tocamos nada.

Se aplica a IDs colectivos definidos por la misma heurística que
usábamos antes (is_ignored_id).

INPUT:  directorio con TEI XML (p.ej. caldracor)
OUTPUT: directorio con TEI refinados (p.ej. lxml-output)
También genera un log CSV con los cambios realizados.
"""

import csv
import sys
import unicodedata
from pathlib import Path

from lxml import etree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {"tei": TEI_NS}


# ----------------------------------------------------------------------
# Normalización y detección de IDs colectivos/anónimos
# ----------------------------------------------------------------------

def strip_accents(s: str) -> str:
    """Elimina tildes/acentos de una cadena Unicode."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def norm_text(s: str) -> str:
    """Normaliza a minúsculas y sin acentos."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", s).lower()
    return strip_accents(s)


def tokenize_who(who_value: str):
    """Divide @who en tokens separados por espacios, tal cual."""
    if not who_value:
        return []
    return [t for t in who_value.strip().split() if t]


def is_collective_id(token: str) -> bool:
    """
    Decide si un ID es de tipo colectivo/anónimo (los que hemos estado excluyendo).

    - Normaliza a minúsculas y sin tildes.
    - Ignora si empieza por:
      '#dentro', '#uno', '#unos', '#otros', '#otras',
      '#musico', '#musica', '#musicos',
      '#acompan' (acompañamiento, acompanamiento, etc.).

    Cubre variantes con sufijos: '#musicos-1', '#uno-3', etc.
    """
    if not token:
        return False

    t = norm_text(token.strip())  # p.ej. '#músicos-1' -> '#musicos-1'
    prefixes = (
        "#dentro",
        "#uno",
        "#unos",
        "#otros",
        "#otras",
        "#musico",
        "#musica",
        "#musicos",
        "#acompan",   # acompañamiento, acompanamiento, etc.
    )

    return any(t.startswith(pref) for pref in prefixes)


def collective_base(token: str) -> str:
    """
    Devuelve la "base" del ID colectivo para compararla con el <speaker>.

    Ejemplos:
    '#músicos-1' -> 'musicos'
    '#musica'    -> 'musica'
    '#unos'      -> 'unos'
    """
    if not token:
        return ""
    t = norm_text(token.strip())   # '#músicos-1' -> '#musicos-1'
    if t.startswith("#"):
        t = t[1:]
    base = t.split("-")[0]
    return base  # p.ej. 'musicos', 'musica', 'unos', 'otros'


def sample_sp_text(sp_el, max_len=80):
    """Devuelve un pequeño snippet de texto a partir del primer <l>."""
    first_l = sp_el.xpath(".//tei:l", namespaces=NSMAP)
    if not first_l:
        return ""
    txt = " ".join(first_l[0].itertext()).strip()
    if len(txt) > max_len:
        txt = txt[: max_len - 3] + "..."
    return txt


def get_scene_label(scene_el):
    """Devuelve una etiqueta de escena: preferimos @n si existe."""
    if scene_el is None:
        return ""
    n = scene_el.get("n")
    if n is not None:
        return n
    parent = scene_el.getparent()
    if parent is not None:
        siblings = [
            c for c in parent
            if isinstance(c.tag, str)
            and ET.QName(c).localname == "div"
            and c.get("type") == "scene"
        ]
        try:
            idx = siblings.index(scene_el) + 1
        except ValueError:
            idx = None
        if idx is not None:
            return f"scene_{idx}"
    return ""


def get_act_label(act_el):
    """Devuelve una etiqueta de acto: preferimos @n si existe."""
    if act_el is None:
        return ""
    n = act_el.get("n")
    if n is not None:
        return n
    parent = act_el.getparent()
    if parent is not None:
        siblings = [
            c for c in parent
            if isinstance(c.tag, str)
            and ET.QName(c).localname == "div"
            and c.get("type") == "act"
        ]
        try:
            idx = siblings.index(act_el) + 1
        except ValueError:
            idx = None
        if idx is not None:
            return f"act_{idx}"
    return ""


# ----------------------------------------------------------------------
# Procesado de un fichero
# ----------------------------------------------------------------------

def process_file(input_path: Path, output_path: Path, log_rows: list):
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(input_path), parser)
    root = tree.getroot()

    acts = root.xpath(".//tei:div[@type='act']", namespaces=NSMAP)
    if not acts:
        acts = [root]  # si no hay actos, usamos root como contenedor

    for act in acts:
        act_label = get_act_label(act) if act is not root else ""
        scenes = act.xpath(".//tei:div[@type='scene']", namespaces=NSMAP)

        for scene in scenes:
            scene_label = get_scene_label(scene)
            sps = scene.xpath(".//tei:sp", namespaces=NSMAP)

            for idx, sp in enumerate(sps, start=1):
                # 1) speaker
                speaker_elems = sp.xpath("./tei:speaker", namespaces=NSMAP)
                if not speaker_elems:
                    continue

                speaker_raw = " ".join(speaker_elems[0].itertext()).strip()
                speaker_norm = norm_text(speaker_raw)

                # Solo nos interesan los casos donde aparezca "todos"
                if "todos" not in speaker_norm:
                    continue

                # 2) @who
                who_val = sp.get("who")
                if not who_val:
                    continue

                tokens = tokenize_who(who_val)

                # IDs colectivos presentes en este @who
                collective_tokens = [t for t in tokens if is_collective_id(t)]
                if not collective_tokens:
                    # No hay nada que limpiar en este <sp>
                    continue

                # 3) Decidir qué colectivos se mantienen y cuáles se eliminan
                removed = []
                kept = []

                for tok in collective_tokens:
                    base = collective_base(tok)  # p.ej. 'musicos'
                    # Regla: solo mantenemos el colectivo si SU BASE aparece en el speaker
                    # (p.ej. 'musicos' en "musicos y todos", 'musica' en "musica y todos")
                    if base and base in speaker_norm:
                        kept.append(tok)
                    else:
                        removed.append(tok)

                # Si no se elimina nada, no tocamos el @who
                if not removed:
                    continue

                # 4) Construir nuevo @who sin los colectivos eliminados
                new_tokens = [t for t in tokens if t not in removed]
                if new_tokens:
                    new_who = " ".join(new_tokens)
                    sp.set("who", new_who)
                else:
                    # Si nos hemos quedado sin tokens, eliminamos el atributo @who
                    if "who" in sp.attrib:
                        del sp.attrib["who"]
                    new_who = ""

                snippet = sample_sp_text(sp)

                log_rows.append(
                    {
                        "file": input_path.name,
                        "act": act_label,
                        "scene": scene_label,
                        "sp_index_in_scene": idx,
                        "speaker_raw": speaker_raw,
                        "speaker_norm": speaker_norm,
                        "who_before": who_val,
                        "who_after": new_who,
                        "collective_ids_before": " ".join(collective_tokens),
                        "collective_ids_removed": " ".join(removed),
                        "collective_ids_kept": " ".join(kept),
                        "snippet": snippet,
                    }
                )

    # Escribir TEI transformado
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(output_path),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 refine_todos_who_collectives.py INPUT_DIR OUTPUT_DIR")
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

    # Log de cambios
    log_path = output_dir / "refine_todos_who_collectives_log.csv"
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "act",
                "scene",
                "sp_index_in_scene",
                "speaker_raw",
                "speaker_norm",
                "who_before",
                "who_after",
                "collective_ids_before",
                "collective_ids_removed",
                "collective_ids_kept",
                "snippet",
            ],
        )
        writer.writeheader()
        for row in log_rows:
            writer.writerow(row)

    print(f"\nDone. Log written to: {log_path}")


if __name__ == "__main__":
    main()
