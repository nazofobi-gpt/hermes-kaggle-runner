import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.workbook_structure_verifier import compare, workbook_signature

CHART = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:plotArea><c:lineChart><c:ser><c:cat><c:strRef><c:f>'Data'!$A$2:$A$6</c:f></c:strRef></c:cat><c:val><c:numRef><c:f>'Data'!$B$2:$B$6</c:f></c:numRef></c:val></c:ser></c:lineChart></c:plotArea></c:chart></c:chartSpace>'''
SHEET = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><conditionalFormatting sqref="B2:B6"><cfRule type="cellIs" operator="lessThan" priority="1"><formula>100</formula></cfRule></conditionalFormatting></worksheet>'''


def make_xlsx(path: Path, chart=CHART, sheet=SHEET):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/charts/chart1.xml", chart)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


class WorkbookStructureVerifierTest(unittest.TestCase):
    def test_extracts_chart_and_cf_ranges(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.xlsx"
            make_xlsx(p)
            sig = workbook_signature(p)
            self.assertEqual([x["formula"] for x in sig["charts"]], ["'Data'!$A$2:$A$6", "'Data'!$B$2:$B$6"])
            self.assertEqual(sig["conditional_formats"][0]["sqref"], "B2:B6")

    def test_rejects_unexpected_chart_and_cf_changes(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.xlsx", Path(td) / "b.xlsx"
            make_xlsx(a)
            make_xlsx(b, CHART.replace("$B$6", "$B$5"), SHEET.replace("B2:B6", "B2:B5"))
            result = compare(workbook_signature(a), workbook_signature(b))
            self.assertFalse(result["pass"])
            self.assertEqual(result["unexpected_changes"], ["charts", "conditional_formats"])

    def test_allowlist_is_explicit(self):
        before = {"charts": [{"formula": "A1:A2"}], "conditional_formats": []}
        after = {"charts": [{"formula": "A1:A3"}], "conditional_formats": []}
        self.assertFalse(compare(before, after)["pass"])
        self.assertTrue(compare(before, after, {"charts"})["pass"])


if __name__ == "__main__":
    unittest.main()
