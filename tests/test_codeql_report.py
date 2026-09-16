"""The security gate must fail closed when rule metadata cannot be resolved."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("codeql_report_test", ROOT / "scripts" / "check_codeql.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def report(score="7.8", extension=True):
    rule = {"id": "js/example", "properties": {"security-severity": score}}
    result = {"ruleId": "js/example", "locations": [{"physicalLocation": {
        "artifactLocation": {"uri": "example.py"}, "region": {"startLine": 2}}}]}
    driver = {"name": "CodeQL", "rules": [] if extension else [rule]}
    tool = {"driver": driver}
    if extension:
        tool["extensions"] = [{"name": "pack", "rules": [rule]}]
        result["rule"] = {"index": 0, "toolComponent": {"index": 0}}
    else:
        result["ruleIndex"] = 0
    return {"version": "2.1.0", "runs": [{"tool": tool, "results": [result]}]}


class CodeQLReportTests(unittest.TestCase):
    def test_extension_severity_is_not_silently_zero(self):
        self.assertEqual(checker.findings(report())[0]["severity"], 7.8)

    def test_driver_severity(self):
        self.assertEqual(checker.findings(report(extension=False))[0]["severity"], 7.8)

    def test_component_name(self):
        doc = report()
        doc["runs"][0]["results"][0]["rule"]["toolComponent"] = {"name": "pack"}
        self.assertEqual(checker.findings(doc)[0]["severity"], 7.8)

    def test_unique_id_fallback(self):
        doc = report()
        del doc["runs"][0]["results"][0]["rule"]
        self.assertEqual(checker.findings(doc)[0]["severity"], 7.8)

    def test_bad_component_or_rule_reference_fails(self):
        for change in ("component", "rule", "index", "conflict"):
            with self.subTest(change=change):
                doc = report()
                result = doc["runs"][0]["results"][0]
                if change == "component": result["rule"]["toolComponent"]["index"] = 99
                if change == "rule": result["ruleId"] = "unknown"
                if change == "index": result["rule"]["index"] = 99
                if change == "conflict": result["rule"]["id"] = "other"
                with self.assertRaises(checker.ReportError): checker.findings(doc)

    def test_ambiguous_rule_fails(self):
        doc = report()
        del doc["runs"][0]["results"][0]["rule"]
        doc["runs"][0]["tool"]["extensions"].append(copy.deepcopy(doc["runs"][0]["tool"]["extensions"][0]))
        with self.assertRaises(checker.ReportError): checker.findings(doc)

    def test_missing_or_invalid_severity_fails(self):
        for score in (None, "", "oops", "NaN", "Infinity", -1, 11, True):
            with self.subTest(score=score), self.assertRaises(checker.ReportError):
                checker.findings(report(score))

    def test_failed_analysis_fails(self):
        doc = report()
        doc["runs"][0]["invocations"] = [{"executionSuccessful": False}]
        with self.assertRaises(checker.ReportError): checker.findings(doc)

    def test_extraction_error_fails(self):
        doc = report()
        doc["runs"][0]["invocations"] = [{"toolExecutionNotifications": [{"level": "error"}]}]
        with self.assertRaises(checker.ReportError): checker.findings(doc)

    def test_empty_report_fails_but_valid_zero_findings_passes(self):
        with self.assertRaises(checker.ReportError): checker.findings({"version": "2.1.0", "runs": []})
        doc = report()
        doc["runs"][0]["results"] = []
        self.assertEqual(checker.findings(doc), [])

    def test_review_is_bound_to_rule_location_and_entire_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = b"first\nsecond\n"
            (root / "example.py").write_bytes(data)
            row = checker.findings(report())[0]
            review = {key: row[key] for key in ("rule", "path", "line", "severity")}
            review.update(reason="fixture only", classification="false-positive", blob_sha=hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False).hexdigest())
            self.assertTrue(checker.is_reviewed(row, [review], root))
            for key, value in (("line", 3), ("end_line", 3), ("path", "other.py"), ("rule", "py/other"), ("severity", 9.9)):
                self.assertFalse(checker.is_reviewed({**row, key: value}, [review], root))
            self.assertFalse(checker.is_reviewed(row, [{**review, "classification": "unknown"}], root))
            (root / "dependency.py").write_bytes(data)
            review["dependencies"] = {"dependency.py": review["blob_sha"]}
            self.assertTrue(checker.is_reviewed(row, [review], root))
            (root / "dependency.py").write_bytes(data + b"changed\n")
            self.assertFalse(checker.is_reviewed(row, [review], root))
            (root / "dependency.py").write_bytes(data)
            (root / "example.py").write_bytes(data + b"changed\n")
            self.assertFalse(checker.is_reviewed(row, [review], root))

    def test_exit_codes_preserve_security_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(checker.main([temp]), 2)
            path = root / "test.sarif"
            path.write_text(json.dumps(report()), encoding="utf-8")
            self.assertEqual(checker.main([temp]), 1)
            path.write_text(json.dumps(report("3.0")), encoding="utf-8")
            self.assertEqual(checker.main([temp]), 0)
            path.write_text(json.dumps(report(None)), encoding="utf-8")
            self.assertEqual(checker.main([temp]), 2)
