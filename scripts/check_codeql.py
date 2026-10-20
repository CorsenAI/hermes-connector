"""Validate CodeQL SARIF metadata and reject unreviewed high-severity results.

Reports are not filtered or rewritten. A reviewed result remains visible with its
real severity and must match an exact source file, line and Git blob checksum.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


class ReportError(ValueError):
    pass


def rule_for(run: dict, result: dict) -> dict:
    tool = run.get("tool", {})
    driver = tool.get("driver")
    extensions = tool.get("extensions", [])
    if not isinstance(driver, dict) or not isinstance(extensions, list):
        raise ReportError("missing or invalid tool metadata")
    reference = result.get("rule", {})
    if not isinstance(reference, dict):
        raise ReportError("invalid rule reference")
    rule_id = result.get("ruleId", reference.get("id"))
    if result.get("ruleId") and reference.get("id") and result["ruleId"] != reference["id"]:
        raise ReportError("conflicting rule identifiers")
    component_ref = reference.get("toolComponent")
    components = [driver, *extensions]
    if component_ref is not None:
        if not isinstance(component_ref, dict):
            raise ReportError("invalid component reference")
        if "index" in component_ref:
            index = component_ref["index"]
            if type(index) is not int or not 0 <= index < len(extensions):
                raise ReportError("component index out of range")
            components = [extensions[index]]
        else:
            keys = [key for key in ("name", "guid") if component_ref.get(key)]
            if not keys:
                raise ReportError("empty component reference")
            components = [component for component in components
                          if all(component.get(key) == component_ref[key] for key in keys)]
        if len(components) != 1 or any(
            component_ref.get(key) and component_ref[key] != components[0].get(key)
            for key in ("name", "guid")
        ):
            raise ReportError("unresolved or conflicting component reference")
    if rule_id:
        matches = [rule for component in components for rule in component.get("rules", [])
                   if rule.get("id") == rule_id]
        if len(matches) != 1:
            raise ReportError(f"unresolved or ambiguous rule: {rule_id}")
        rule = matches[0]
        index = reference.get("index", result.get("ruleIndex"))
        if index is not None and (component_ref is not None or driver.get("rules")):
            rules = components[0].get("rules", [])
            if type(index) is not int or not 0 <= index < len(rules) or rules[index] != rule:
                raise ReportError(f"conflicting rule index: {rule_id}")
        return rule
    index = reference.get("index", result.get("ruleIndex"))
    rules = components[0].get("rules", [])
    if type(index) is not int or not 0 <= index < len(rules):
        raise ReportError("result has no resolvable rule")
    return rules[index]


def findings(document: dict) -> list[dict]:
    if document.get("version") != "2.1.0" or not document.get("runs"):
        raise ReportError("expected a non-empty SARIF 2.1.0 report")
    found = []
    for run in document["runs"]:
        if not isinstance(run.get("tool", {}).get("driver"), dict):
            raise ReportError("run has no tool driver")
        for invocation in run.get("invocations", []):
            if invocation.get("executionSuccessful") is False or any(
                item.get("level") == "error"
                for item in invocation.get("toolExecutionNotifications", [])
            ):
                raise ReportError("analysis reported an execution or extraction error")
        for result in run.get("results", []):
            rule = rule_for(run, result)
            raw = rule.get("properties", {}).get("security-severity")
            if raw is None or isinstance(raw, bool):
                raise ReportError(f"unknown security severity: {rule.get('id')}")
            try:
                severity = float(raw)
            except (ValueError, TypeError) as exc:
                raise ReportError(f"invalid security severity: {rule.get('id')}") from exc
            if not math.isfinite(severity) or not 0 <= severity <= 10:
                raise ReportError(f"invalid security severity: {rule.get('id')}")
            locations = result.get("locations", [])
            physical = locations[0].get("physicalLocation", {}) if len(locations) == 1 else {}
            region = physical.get("region", {})
            found.append({"rule": rule.get("id"), "severity": severity,
                          "path": physical.get("artifactLocation", {}).get("uri", ""),
                          "line": region.get("startLine"),
                          "end_line": region.get("endLine", region.get("startLine"))})
    return found


def source_matches(root: Path, path: str, expected_sha: str) -> bool:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReportError("review path must be repository-relative")
    source = (root / relative).resolve()
    if not source.is_relative_to(root.resolve()) or not source.is_file():
        return False
    data = source.read_bytes()
    # Git object identity, not a cryptographic signature or password digest.
    digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data,
                          usedforsecurity=False).hexdigest()
    return digest == expected_sha


def is_reviewed(finding: dict, reviews: list[dict], root: Path) -> bool:
    for review in reviews:
        if review.get("classification") not in ("false-positive", "intentional-output"):
            continue
        if not review.get("reason") or any(finding.get(key) != review.get(key)
                                          for key in ("rule", "path", "line", "severity")):
            continue
        if finding.get("end_line") != finding.get("line"):
            continue
        dependencies = review.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ReportError("review dependencies must map source paths to Git blob IDs")
        if source_matches(root, review["path"], review.get("blob_sha")) and all(
            source_matches(root, path, sha) for path, sha in dependencies.items()
        ):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sarif_dir", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args(argv)
    try:
        paths = sorted(args.sarif_dir.glob("*.sarif"))
        if not paths:
            raise ReportError("CodeQL produced no SARIF report")
        reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else []
        if not isinstance(reviews, list):
            raise ReportError("review file must contain a list")
        rows = [row for path in paths for row in findings(json.loads(path.read_text(encoding="utf-8"))) ]
        high = reviewed = blocked = 0
        for row in rows:
            accepted = is_reviewed(row, reviews, args.root)
            high += row["severity"] >= 7
            reviewed += accepted
            blocked += row["severity"] >= 7 and not accepted
            status = "reviewed; see source-bound disposition" if accepted else "unreviewed"
            print(f"Finding: {row['rule']}; security severity: {row['severity']}; "
                  f"{row['path']}:{row['line']}; {status}")
        print(f"CodeQL findings: {len(rows)}; high or critical: {high}; "
              f"reviewed: {reviewed}; blocking: {blocked}")
        return 1 if blocked else 0
    except (ReportError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"CodeQL verification failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
