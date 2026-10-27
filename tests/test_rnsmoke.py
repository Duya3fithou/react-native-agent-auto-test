"""Unit tests for the rnsmoke package (no device or Maestro needed).

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "rn-smoke-test" / "scripts"))

from rnsmoke import report, runner, template, testcases  # noqa: E402
from rnsmoke.workspace import Workspace, select_cases  # noqa: E402

HEADER = ["Test ID", "Platform", "Section", "Description", "Expected result", "Actual result", "Result",
          "IOS", "ANDROID", "Test data", "Note ", "Tester"]
CASES = [
    ("App / iOS / ANDROID", "Registration", "Register without first and last name",
     '"First name is required" popup appears\n"Last name is required" popup appears'),
    ("App / iOS / ANDROID", None, "Register with mismatching passwords", '"Passwords do not match" is displayed'),
    ("App / iOS / ANDROID", "Login", "Login with valid credentials", "Home screen is displayed"),
    ("iOS", "Login", "Login with a wrong password", '"Invalid credentials" popup appears'),
    ("ANDROID", "Home", "Home screen for a user with 2 profiles", "1. Facility switcher\n2. Profile switcher"),
    ("App / iOS / ANDROID", "Home", "Switch facility", "A list of linked facilities is displayed"),
]
SUMMARY = [
    ["Name", "Demo Smoke Test Checklist"],
    ["Test cases Version", "v1.0 Checklist"],
    ["Sprint", None, "All Cases", "=COUNT(A12:A1782)"],
    ["Build version"],
    ["Pre-condition "],
    ["Pass Cases ", '=COUNTIF(G2:G1782, "Pass")', "Unavailabe Cases", '=COUNTIF(H2:H1782, "Unavailable")'],
    [None, None, "Fail Cases", '=COUNTIF(H2:H1782, "Fail")'],
    ["Tested by", "QA"],
    ["Test Date", dt.datetime(2026, 4, 2)],
]


def make_sheet(ws, with_result_header=True, dv_values='"PASS,FAIL"'):
    for r, values in enumerate(SUMMARY, start=1):
        for c, value in enumerate(values, start=1):
            if value is not None:
                ws.cell(r, c, value)
        if values and values[0] is not None:
            ws.cell(r, 1).fill = PatternFill("solid", start_color="FF3C78D8", end_color="FF3C78D8")
            ws.cell(r, 1).font = Font(name="Arial", size=10, bold=True, color="FFFFFFFF")
    for r in (1, 2, 4, 5, 8, 9):
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
    for c, value in enumerate(HEADER, start=1):
        if value == "Result" and not with_result_header:
            continue
        ws.cell(10, c, value)
    for i, (platform, section, desc, expected) in enumerate(CASES):
        row = 11 + i
        ws.cell(row, 2, platform)
        if section:
            ws.cell(row, 3, section)
        ws.cell(row, 4, desc)
        ws.cell(row, 5, expected)
        ws.cell(row, 7, "PASS")
        ws.cell(row, 9, "ANDROID_old.mov")
    ws.cell(11, 8, "https://example.com/old-video")
    ws.cell(11, 8).hyperlink = "https://example.com/old-video"
    ws.merge_cells("H11:H13")
    ws.cell(14, 11, "Known flaky on Android")
    ws.column_dimensions["D"].width = 41.25
    ws.column_dimensions["E"].width = 55.88
    ws.freeze_panes = "A11"
    dv = DataValidation(type="list", formula1=dv_values, allow_blank=True)
    dv.add("G11:G1000")
    ws.add_data_validation(dv)
    ws.conditional_formatting.add("G11:G1000", CellIsRule(operator="equal", formula=['"PASS"'],
                                  fill=PatternFill("solid", start_color="FFB7E1CD", end_color="FFB7E1CD")))


def make_workbook(path: Path) -> Path:
    wb = Workbook()
    history = wb.active
    history.title = "1712"
    make_sheet(history, with_result_header=False)
    history.sheet_state = "hidden"
    make_sheet(wb.create_sheet("app"))
    wb.active = 0          # Google exports leave the (hidden) first tab active ...
    wb.views = []          # ... and write no <bookViews> at all
    wb.save(path)
    return path


def make_csv(path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Name", "Demo Smoke Test Checklist ", "", "", "", "", "", "", "", "", "", ""])
        writer.writerow(["Test cases Version", "v1.0 Checklist", "", ""])
        writer.writerow(["Sprint", "", "All Cases", "0"])
        writer.writerow(["Build version", "", "", ""])
        writer.writerow(["Pre-condition ", "", "", ""])
        writer.writerow(["Pass Cases ", "6", "Unavailabe Cases", "0"])
        writer.writerow(["", "", "Fail Cases", "0"])
        writer.writerow(["Tested by", "QA", "", ""])
        writer.writerow(["Test Date", "Apr 02, 2026", "", ""])
        writer.writerow(HEADER)
        last_section = None
        for platform, section, desc, expected in CASES:
            last_section = section or last_section
            writer.writerow(["", platform, section or "", desc, expected, "", "PASS", "", "", "", "", ""])
    return path


def fake_run(cases_doc, platform, statuses, run_dir: Path) -> dict:
    results = {}
    for case, status in zip(cases_doc["cases"], statuses):
        if status is None:
            continue
        rec = {"id": case["id"], "section": case["section"], "row": case["row"], "status": status,
               "message": "" if status == "pass" else f"{status} message for {case['id']}", "duration_s": 12.0}
        if status in ("pass", "fail"):
            evidence = run_dir / "evidence" / platform / f"{case['id'].lower()}.png"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(b"png")
            rec["evidence"] = evidence.relative_to(run_dir).as_posix()
        results[case["key"]] = rec
    return {"platform": platform, "started_at": "2026-10-27T10:00:00+07:00",
            "app": {"version": "1.2.3", "build": "45"}, "results": results}


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_xlsx_picks_visible_tab_and_maps_columns(self):
        doc = testcases.load_cases(make_workbook(self.dir / "Demo.xlsx"))
        src = doc["source"]
        self.assertEqual(src["sheet"], "app")
        self.assertEqual(src["header_row"], 10)
        self.assertEqual(src["columns"]["result"], 7)
        self.assertEqual(src["columns"]["ios"], 8)
        self.assertEqual(src["columns"]["note"], 11)
        self.assertEqual(len(doc["cases"]), len(CASES))
        self.assertEqual([c["id"] for c in doc["cases"][:3]], ["TC-001", "TC-002", "TC-003"])
        self.assertEqual(doc["cases"][1]["section"], "Registration")  # carried forward
        self.assertEqual(doc["cases"][3]["platforms"], ["ios"])
        self.assertEqual(doc["cases"][4]["platforms"], ["android"])

    def test_hidden_tab_without_result_header_uses_validation_column(self):
        doc = testcases.load_cases(make_workbook(self.dir / "Demo.xlsx"), sheet="1712")
        self.assertEqual(doc["source"]["columns"]["result"], 7)

    def test_csv_and_xlsx_produce_the_same_keys(self):
        x = testcases.load_cases(make_workbook(self.dir / "Demo.xlsx"))
        c = testcases.load_cases(make_csv(self.dir / "Demo - app.csv"))
        self.assertEqual(c["source"]["sheet"], "app")
        self.assertEqual([k["key"] for k in x["cases"]], [k["key"] for k in c["cases"]])

    def test_header_aliases(self):
        self.assertEqual(testcases.header_field("Evidence Android(dd/mm/yyyy)"), "android")
        self.assertEqual(testcases.header_field("Evidence IOS  (dd/mm/yyyy)"), "ios")
        self.assertEqual(testcases.header_field("Kết quả mong đợi"), "expected")
        self.assertEqual(testcases.header_field("Status"), "result")
        self.assertIsNone(testcases.header_field("Test cases Version"))

    def test_standard_template_roundtrip(self):
        generated = [{"section": "Login", "description": "Login with valid credentials", "expected": "Home shown"},
                     {"section": "Login", "description": "Wrong password", "expected": "Error toast"}]
        path = template.write_template(self.dir / "gen.xlsx", "Demo Smoke Test Checklist", generated)
        doc = testcases.load_cases(path)
        self.assertEqual(doc["source"]["header_row"], template.STANDARD_HEADER_ROW)
        self.assertEqual(len(doc["cases"]), 2)
        ws = load_workbook(path)["Test cases"]
        self.assertEqual(ws["A1"].fill.fgColor.rgb, template.BLUE)
        self.assertIsNone(ws["B1"].fill.fgColor.rgb if ws["B1"].fill.fill_type else None)
        self.assertTrue(ws["B6"].value.startswith("=COUNTIF(G11:G12"))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.run_dir = self.dir / "runs" / "2026-10-27_100000"
        self.run_dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_xlsx_export_adds_dated_tab_with_identical_layout(self):
        source = make_workbook(self.dir / "Demo.xlsx")
        doc = testcases.load_cases(source)
        run = fake_run(doc, "ios", ["pass", "fail", "blocked", "manual", "skipped", None], self.run_dir)
        out = report.export(doc, [run], self.run_dir, tester="Bot", run_date=dt.date(2026, 10, 27))
        self.assertTrue(out["output"].endswith("Demo - 2710.xlsx"))
        self.assertEqual(out["counts"], {"PASS": 1, "FAIL": 1, "PENDING": 4})
        self.assertEqual(report.verify(Path(out["output"]), out["sheet"], doc), out["counts"])

        wb = load_workbook(out["output"])
        self.assertEqual(wb.sheetnames, ["1712", "app", "2710"])
        self.assertEqual(wb.active.title, "2710")
        new, src = wb["2710"], wb["app"]
        self.assertEqual(new.sheet_state, "visible")
        self.assertEqual(new.freeze_panes, "A11")
        self.assertEqual(new.column_dimensions["E"].width, src.column_dimensions["E"].width)
        self.assertEqual(new["A1"].fill.fgColor.rgb, "FF3C78D8")
        # results
        self.assertEqual([new.cell(r, 7).value for r in range(11, 17)], ["PASS", "FAIL", "PENDING", "PENDING", "PENDING", "PENDING"])
        self.assertEqual(new["F11"].value, "As expected")
        self.assertIn("fail message", new["F12"].value)
        self.assertEqual(new["A11"].value, "TC-001")
        self.assertEqual(new["H11"].value, "evidence/ios/tc-001.png")
        self.assertEqual(new["H11"].hyperlink.target, "evidence/ios/tc-001.png")
        self.assertIsNone(new["I11"].value)                      # old Android evidence cleared
        self.assertIn("[Blocked]", new["K13"].value)
        self.assertTrue(new["K14"].value.startswith("Known flaky on Android\n[Manual]"))
        self.assertEqual(new["L11"].value, "Maestro (auto)")
        self.assertIsNone(new["L13"].value)
        # evidence merge split, summary merges kept
        merged = {str(m) for m in new.merged_cells.ranges}
        self.assertNotIn("H11:H13", merged)
        self.assertIn("B8:D8", merged)
        # dropdown extended with PENDING, colouring copied
        self.assertIn("PENDING", new.data_validations.dataValidation[0].formula1)
        self.assertEqual(len(list(new.conditional_formatting)), 1)
        # summary block
        self.assertEqual(new["B8"].value, "Bot")
        self.assertEqual(new["B9"].value, dt.datetime(2026, 10, 27))
        self.assertEqual(new["B4"].value, "iOS 1.2.3 (45)")
        self.assertEqual(new["B6"].value, '=COUNTIF(G11:G16,"PASS")')
        self.assertEqual(new["D6"].value, '=COUNTIF(G11:G16,"PENDING")')
        self.assertEqual(new["D7"].value, '=COUNTIF(G11:G16,"FAIL")')
        self.assertEqual(new["D3"].value, "=COUNTA(D11:D16)")
        # the source tab is untouched
        self.assertEqual(src["G12"].value, "PASS")
        self.assertIn("H11:H13", {str(m) for m in src.merged_cells.ranges})

    def test_second_export_same_day_gets_unique_tab(self):
        source = make_workbook(self.dir / "Demo.xlsx")
        doc = testcases.load_cases(source)
        run = fake_run(doc, "ios", ["pass"] * 6, self.run_dir)
        first = report.export(doc, [run], self.run_dir, run_date=dt.date(2026, 10, 27))
        doc2 = dict(doc, source=dict(doc["source"], path=first["output"]))
        second = report.export(doc2, [run], self.run_dir, out_path=self.dir / "again.xlsx",
                               run_date=dt.date(2026, 10, 27))
        self.assertEqual(second["sheet"], "2710 (2)")

    def test_csv_export_and_only_new_tab(self):
        source = make_csv(self.dir / "Demo - app.csv")
        doc = testcases.load_cases(source)
        run = fake_run(doc, "android", ["pass", "pass", "fail", "pass", "pass", "error"], self.run_dir)
        out = report.export(doc, [run], self.run_dir, run_date=dt.date(2026, 10, 27), only_new_tab=True)
        wb = load_workbook(out["output"])
        self.assertEqual(wb.sheetnames, ["2710"])
        ws = wb["2710"]
        self.assertEqual(ws["G11"].value, "PASS")
        self.assertEqual(ws["I11"].value, "evidence/android/tc-001.png")   # Android evidence column
        self.assertEqual(ws["G16"].value, "PENDING")
        self.assertIn("[Automation error]", ws["K16"].value)
        self.assertEqual(ws["A1"].fill.fgColor.rgb, template.BLUE)
        self.assertEqual(ws["A10"].fill.fgColor.rgb, template.GREY)
        self.assertEqual(ws.freeze_panes, "A11")
        self.assertTrue(any("PENDING" in (dv.formula1 or "") for dv in ws.data_validations.dataValidation))

    def test_combine_multi_platform(self):
        case = {"key": "k1", "id": "TC-001"}
        ios = {"platform": "ios", "results": {"k1": {"status": "pass", "evidence": "evidence/ios/a.png"}}}
        android_fail = {"platform": "android", "results": {"k1": {"status": "fail", "message": "boom"}}}
        android_skip = {"platform": "android", "results": {"k1": {"status": "skipped"}}}
        android_missing = {"platform": "android", "results": {}}
        partial = {"platform": "ios", "results": {"k1": {"status": "pass", "coverage": "partial", "uncovered": "email"}}}
        self.assertEqual(report.combine(case, [ios]).status, "PASS")
        verdict = report.combine(case, [ios, android_fail])
        self.assertEqual(verdict.status, "FAIL")
        self.assertIn("Android: boom", verdict.actual)
        self.assertEqual(report.combine(case, [ios, android_skip]).status, "PASS")
        self.assertEqual(report.combine(case, [ios, android_missing]).status, "PENDING")
        verdict = report.combine(case, [partial])
        self.assertEqual(verdict.status, "PENDING")
        self.assertIn("verify manually: email", verdict.note)
        manual = {"status": "manual", "message": "Needs the OTP email"}
        verdict = report.combine(case, [{"platform": "ios", "results": {"k1": manual}},
                                        {"platform": "android", "results": {"k1": dict(manual)}}])
        self.assertEqual(verdict.note, "[Manual] Needs the OTP email")          # said once, no platform prefix


class RunnerHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_junit_and_artifacts(self):
        junit = self.dir / "report.xml"
        junit.write_text("""<?xml version='1.0' encoding='UTF-8'?>
<testsuites><testsuite name="Test Suite" tests="2" failures="1">
  <testcase id="A" name="Login - ok" classname="Login - ok" file="ok.yaml" time="11.4" status="SUCCESS"/>
  <testcase id="B" name="Login - bad" classname="Login - bad" file="bad.yaml" time="6.4" status="ERROR">
    <failure>Assertion is false: "Welcome" is visible</failure>
  </testcase>
</testsuite></testsuites>""", encoding="utf-8")
        reports = runner.parse_junit(junit)
        self.assertEqual([(r["name"], r["failed"]) for r in reports], [("Login - ok", False), ("Login - bad", True)])
        self.assertIn("Welcome", reports[1]["message"])

        flow_dir = self.dir / "2026-10-27_110000" / "Login - bad"
        (flow_dir / "screenshots").mkdir(parents=True)
        (flow_dir / "takeScreenshot").mkdir()
        (flow_dir / "screenshots" / "step-004-assert.png").write_bytes(b"x")
        (flow_dir / "takeScreenshot" / "evidence.png").write_bytes(b"x")
        (flow_dir / "commands.json").write_text(json.dumps([
            {"command": {"tapOnElement": {"selector": {"textRegex": "Sign in"}}}, "metadata": {"status": "COMPLETED", "sequenceNumber": 2}},
            {"command": {"assertConditionCommand": {"condition": {"visible": {"textRegex": "Welcome"}}}},
             "metadata": {"status": "FAILED", "sequenceNumber": 3}},
        ]), encoding="utf-8")
        found = runner.find_artifacts(self.dir, "Login - bad")
        self.assertEqual(found, flow_dir)
        self.assertEqual(runner.pick_screenshot(found, "fail").name, "step-004-assert.png")
        self.assertEqual(runner.pick_screenshot(found, "pass").name, "evidence.png")
        self.assertEqual(runner.describe_failed_step(found), '#4 assertCondition "Welcome"')

    def test_classify_failure(self):
        art = self.dir / "flow"
        (art / "screen-hierarchy").mkdir(parents=True)
        (art / "screen-hierarchy" / "step.json").write_text('{"text": "Could not connect to development server"}')
        self.assertEqual(runner.classify_failure("Element not found", art, "").status, "error")
        self.assertEqual(runner.classify_failure("Unknown Property: timeout at x.yaml", None, "").status, "error")
        self.assertFalse(runner.classify_failure("Unknown Property: timeout", None, "").retryable)
        self.assertEqual(runner.classify_failure('Assertion is false: "x" is visible', None, "").status, "fail")
        self.assertEqual(runner.classify_failure("", None, "Running flow a.yaml\n[Failed] a (3s) (x)").status, "fail")

    def test_flow_name(self):
        flow = self.dir / "f.yaml"
        flow.write_text('appId: ${APP_ID}\nname: "Login - ok"\n---\n- launchApp\n', encoding="utf-8")
        self.assertEqual(runner.flow_name(flow), "Login - ok")
        flow.write_text("appId: x\n---\n- launchApp\n", encoding="utf-8")
        self.assertEqual(runner.flow_name(flow), "f")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "package.json").write_text('{"name": "demo"}', encoding="utf-8")
        self.ws = Workspace(str(self.dir))
        self.ws.ensure()
        self.doc = testcases.load_cases(make_workbook(self.dir / "Demo.xlsx"))
        self.ws.save_cases(self.doc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_select_cases(self):
        cases = self.doc["cases"]
        self.assertEqual([c["id"] for c in select_cases(cases, ["TC-002..TC-004"])], ["TC-002", "TC-003", "TC-004"])
        self.assertEqual(len(select_cases(cases, None, ["login"])), 2)
        self.assertEqual(select_cases(cases, ["row:12"])[0]["id"], "TC-002")
        extra = cases + [dict(cases[-1], id="TC-099", key="k99", section="Home - My Booking")]
        self.assertEqual(len(select_cases(extra, None, ["Home"])), 2)              # exact name wins
        self.assertEqual(len(select_cases(extra, None, ["my booking"])), 1)        # substring fallback

    def test_mark_status_and_relink(self):
        flow = self.ws.flows_dir / "login" / "ok.yaml"
        flow.parent.mkdir(parents=True)
        flow.write_text("appId: ${APP_ID}\n---\n- launchApp\n- takeScreenshot: evidence\n", encoding="utf-8")
        self.ws.mark(select_cases(self.doc["cases"], ["TC-003"]), "automated", flow="flows/login/ok.yaml")
        self.ws.mark(select_cases(self.doc["cases"], ["TC-001"]), "manual", reason="email")
        report_rows = {r["id"]: r for r in self.ws.status_report()["cases"]}
        self.assertEqual(report_rows["TC-003"]["status"], "automated")
        self.assertEqual(report_rows["TC-001"]["reason"], "email")
        self.assertEqual(report_rows["TC-002"]["status"], "todo")

        edited = json.loads(json.dumps(self.doc))
        target = edited["cases"][2]
        target["description"] = "Login with valid credentials."            # small edit -> new key
        target["key"] = testcases.case_key(target["section"], target["description"], target["expected"])
        moved = self.ws.relink(edited["cases"])
        self.assertEqual(moved[0][0], "TC-003")
        self.assertEqual(self.ws.load_manifest()["cases"][target["key"]]["flow"], "flows/login/ok.yaml")

    def test_env_file(self):
        self.ws.env_path.write_text('# comment\nTEST_EMAIL="a@b.c"\nexport TEST_PASSWORD=p=1\nBAD KEY=x\n', encoding="utf-8")
        self.assertEqual(self.ws.env_vars(), {"TEST_EMAIL": "a@b.c", "TEST_PASSWORD": "p=1"})

    def test_init_copies_templates(self):
        self.assertTrue((self.ws.subflows_dir / "launch-clean.yaml").exists())
        self.assertTrue((self.ws.subflows_dir / "hide-keyboard.yaml").exists())
        self.assertTrue((self.ws.subflows_dir / "scroll-until-visible.yaml").exists())
        self.assertIn(".env", (self.ws.root / ".gitignore").read_text())
        self.assertTrue(self.ws.status_report()["warnings"])   # FIRST_SCREEN_TEXT placeholder flagged


if __name__ == "__main__":
    unittest.main()
