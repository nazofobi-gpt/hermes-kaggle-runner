#!/usr/bin/env python3
"""Deterministic XLSX structural verifier for chart and conditional-format ranges.

Uses only Python stdlib. It inspects OOXML formulas/ranges without executing macros.
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def workbook_signature(path: str | Path) -> dict[str, list[dict[str, str]]]:
    charts: list[dict[str, str]] = []
    conditional_formats: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            if name.startswith("xl/charts/") and name.endswith(".xml"):
                root = ET.fromstring(zf.read(name))
                formulas = sorted(
                    node.text.strip()
                    for node in root.findall(f".//{{{CHART_NS}}}f")
                    if node.text and node.text.strip()
                )
                for formula in formulas:
                    charts.append({"part": name, "formula": formula})
            elif name.startswith("xl/worksheets/") and name.endswith(".xml"):
                root = ET.fromstring(zf.read(name))
                for node in root.findall(f".//{{{SHEET_NS}}}conditionalFormatting"):
                    sqref = (node.attrib.get("sqref") or "").strip()
                    if sqref:
                        conditional_formats.append({"part": name, "sqref": sqref})
    return {
        "charts": charts,
        "conditional_formats": sorted(
            conditional_formats, key=lambda x: (x["part"], x["sqref"])
        ),
    }


def compare(before: dict, after: dict, allow: set[str] | None = None) -> dict:
    allow = allow or set()
    changed = []
    for key in ("charts", "conditional_formats"):
        if before.get(key) != after.get(key) and key not in allow:
            changed.append(key)
    return {"pass": not changed, "unexpected_changes": changed}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--allow", action="append", choices=["charts", "conditional_formats"], default=[])
    args = p.parse_args()
    result = compare(workbook_signature(args.before), workbook_signature(args.after), set(args.allow))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
