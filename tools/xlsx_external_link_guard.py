#!/usr/bin/env python3
"""Fail-closed external-link verifier for XLSX workbooks.

This tool does not edit a workbook. It only classifies external-link fidelity risk:
- PASS_NO_EXTERNAL_LINKS
- PASS_RESOLVED_EXTERNAL_LINK_METADATA
- BLOCK_UNRESOLVED_EXTERNAL_LINK

A workbook is blocked when an external-workbook formula is present but the XLSX
package has no externalLink metadata, or the cached formula result is #REF!.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

FORMULA_EXT_RE = re.compile(r"\[(?P<book>[^\]]+)\]")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def verify(path: str) -> dict:
    p = Path(path)
    formulas = []
    cached_ref_errors = []

    with zipfile.ZipFile(p, "r") as z:
        names = set(z.namelist())
        external_parts = sorted(
            n for n in names
            if n.startswith("xl/externalLinks/") and n.endswith(".xml")
        )

        worksheet_parts = sorted(
            n for n in names
            if n.startswith("xl/worksheets/") and n.endswith(".xml")
        )
        for name in worksheet_parts:
            root = ET.fromstring(z.read(name))
            for cell in root.findall(".//m:c", NS):
                f = cell.find("m:f", NS)
                if f is None or not (f.text or ""):
                    continue

                formula = f.text or ""
                books = FORMULA_EXT_RE.findall(formula)
                if not books:
                    continue

                formulas.append({
                    "sheet_part": name,
                    "cell": cell.attrib.get("r"),
                    "formula": formula,
                    "books": books,
                })

                value = cell.find("m:v", NS)
                if value is not None and (value.text or "").strip() == "#REF!":
                    cached_ref_errors.append({
                        "sheet_part": name,
                        "cell": cell.attrib.get("r"),
                    })

    if not formulas and not external_parts:
        status = "PASS_NO_EXTERNAL_LINKS"
    elif formulas and external_parts and not cached_ref_errors:
        status = "PASS_RESOLVED_EXTERNAL_LINK_METADATA"
    else:
        status = "BLOCK_UNRESOLVED_EXTERNAL_LINK"

    return {
        "file": p.name,
        "status": status,
        "external_formula_count": len(formulas),
        "external_books": sorted({b for x in formulas for b in x["books"]}),
        "external_link_parts": external_parts,
        "cached_ref_errors": cached_ref_errors,
        "formulas": formulas,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    results = [verify(p) for p in args.paths]
    print(json.dumps(results, indent=2, ensure_ascii=False))

    if any(r["status"] == "BLOCK_UNRESOLVED_EXTERNAL_LINK" for r in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
