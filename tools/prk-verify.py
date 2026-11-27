#!/usr/bin/env python3
"""Compare two Maven Surefire report trees by test identity and outcome.

Standard library only. Exit codes: 0 parity, 1 regression, 2 invalid input.

Identity is (module, test class, test case). The module is derived from the
path segment before target/surefire-reports; the class from the testcase
classname or the suite name.

Supported report layouts:

- module/target/surefire-reports/TEST-*.xml
- module/surefire-reports/TEST-*.xml
- flat/TEST-*.xml, where the module identity is "."

The module identity is path-based. Reports copied into one flat directory lose
their module identity, and duplicate class and test names can then make the
input INVALID. The comparison cannot establish report freshness, artifact
provenance, or whether a report came from a restored cache.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

PASS, FAILED, ERROR, SKIPPED = "PASS", "FAIL", "ERROR", "SKIPPED"


def status_of(case):
    if case.find("error") is not None:
        return ERROR
    if case.find("failure") is not None:
        return FAILED
    if case.find("skipped") is not None:
        return SKIPPED
    return PASS


def module_for(path, root):
    parts = os.path.normpath(os.path.relpath(path, root)).split(os.sep)
    if "target" in parts:
        index = parts.index("target")
        if index:
            return "/".join(parts[:index])
    if len(parts) > 1:
        return parts[0]
    return "."


def _walk_error(error):
    raise ValueError("cannot traverse %s: %s" % (getattr(error, "filename", "?"), error))


def load(root):
    if not os.path.isdir(root):
        raise ValueError("not a directory: %s" % root)
    cases = {}
    files = 0
    for directory, _, names in os.walk(root, onerror=_walk_error):
        for name in names:
            if not name.startswith("TEST-") or not name.endswith(".xml"):
                continue
            path = os.path.join(directory, name)
            try:
                tree = ET.parse(path)
            except (ET.ParseError, OSError) as exc:
                raise ValueError("unreadable or malformed XML %s: %s" % (path, exc))
            files += 1
            module = module_for(path, root)
            suites = tree.getroot()
            if suites.tag == "testsuite":
                suites = [suites]
            elif suites.tag != "testsuites":
                raise ValueError("unexpected root element in %s" % path)
            for suite in suites:
                suite_name = suite.get("name", "")
                for case in suite.findall("testcase"):
                    case_name = case.get("name")
                    class_name = case.get("classname") or suite_name
                    if not case_name:
                        raise ValueError("missing test case name in %s" % path)
                    if not class_name:
                        raise ValueError("missing test class name in %s" % path)
                    identity = (module, class_name, case_name)
                    if identity in cases:
                        raise ValueError("duplicate test identity: %r" % (identity,))
                    cases[identity] = status_of(case)
    if not files:
        raise ValueError("no TEST-*.xml files under %s" % root)
    if not cases:
        raise ValueError("no test cases under %s" % root)
    return cases


def compare(baseline, candidate):
    missing = sorted(set(baseline) - set(candidate))
    added = sorted(set(candidate) - set(baseline))
    common = sorted(set(baseline) & set(candidate))
    failed = []
    improvements = []
    additions = []
    transitions = []

    for identity in missing:
        failed.append(("missing baseline test", identity, baseline[identity], None))
    for identity in added:
        status = candidate[identity]
        if status in (FAILED, ERROR):
            failed.append(("new failing test", identity, None, status))
        else:
            additions.append((identity, status))
    for identity in common:
        before, after = baseline[identity], candidate[identity]
        if before == after:
            continue
        if before == PASS and after in (FAILED, ERROR, SKIPPED):
            failed.append(("previously passing test changed", identity, before, after))
        elif after in (FAILED, ERROR) and before not in (FAILED, ERROR):
            failed.append(("newly failing or erroring test", identity, before, after))
        elif before in (FAILED, ERROR) and after == SKIPPED:
            failed.append(("previously failing or erroring test skipped", identity,
                           before, after))
        elif before in (FAILED, ERROR) and after == PASS:
            improvements.append((identity, before, after))
        else:
            transitions.append((identity, before, after))

    verdict = "FAIL" if failed else "PASS"
    return {
        "verdict": verdict,
        "parity": baseline == candidate,
        "baseline": len(baseline),
        "candidate": len(candidate),
        "missing": [[i[0], i[1], i[2], baseline[i]] for i in missing],
        "added": [list(i) for i in added],
        "failed": [[r, list(i), b, a] for r, i, b, a in failed],
        "improvements": [list(i) + [b, a] for i, b, a in improvements],
        "additions": [list(i) + [s] for i, s in additions],
        "transitions": [list(i) + [b, a] for i, b, a in transitions],
        "health": {
            "baseline": {s: sum(1 for v in baseline.values() if v == s)
                         for s in (PASS, FAILED, ERROR, SKIPPED)},
            "candidate": {s: sum(1 for v in candidate.values() if v == s)
                          for s in (PASS, FAILED, ERROR, SKIPPED)},
        },
    }


def print_report(result):
    health = result["health"]
    print("baseline cases: %d  candidate cases: %d" %
          (result["baseline"], result["candidate"]))
    for label in ("baseline", "candidate"):
        counts = health[label]
        print("%s health: %d passed, %d failed, %d errored, %d skipped" %
              (label, counts[PASS], counts[FAILED], counts[ERROR], counts[SKIPPED]))
    if result["verdict"] == "FAIL":
        detail = "regression detected"
    elif result["parity"]:
        detail = "exact identity and outcome parity"
    else:
        detail = ("no regression; %d additions, %d improvements, %d transitions"
                  % (len(result["additions"]), len(result["improvements"]),
                     len(result["transitions"])))
    print("parity: %s" % ("yes" if result["parity"] else "no"))
    print("verdict: %s (%s)" % (result["verdict"], detail))
    for reason, identity, before, after in result["failed"]:
        print("FAIL  %s: %s | %s | %s -> %s" %
              (reason, identity[0], identity[1] + "|" + identity[2], before, after))
    for identity, before, after in result["improvements"]:
        print("IMPROVEMENT %s | %s | %s -> %s" %
              (identity[0], identity[1] + "|" + identity[2], before, after))
    for identity, status in result["additions"]:
        print("ADDITION %s | %s | %s" %
              (identity[0], identity[1] + "|" + identity[2], status))
    for identity, before, after in result["transitions"]:
        print("TRANSITION %s | %s | %s -> %s" %
              (identity[0], identity[1] + "|" + identity[2], before, after))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)
    try:
        baseline = load(args.baseline)
        candidate = load(args.candidate)
    except ValueError as exc:
        print("INVALID: %s" % exc, file=sys.stderr)
        return 2
    result = compare(baseline, candidate)
    print_report(result)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
