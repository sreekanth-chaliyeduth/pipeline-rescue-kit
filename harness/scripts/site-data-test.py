#!/usr/bin/env python3
"""Validate site/data.json against its authoritative evidence JSON.

Standard library only. The suite reads the same evidence the generator reads,
recomputes representative values, exercises fail-closed inputs in temporary
fixtures and confirms deterministic output. It never touches historical
evidence and never contacts Jenkins, Docker or the network.
"""
import ast
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN = os.path.join(ROOT, "harness", "scripts", "build_site_data.py")
DATA = os.path.join(ROOT, "site", "data.json")
INDEX = os.path.join(ROOT, "site", "index.html")
BASELINE = "harness/pipelines/train-ticket/Jenkinsfile.baseline"

EVIDENCE = [
    "evidence/site/catalog.json",
    "evidence/site/images.json",
    "evidence/site/library-releases.json",
    "evidence/M3/results.json",
    "evidence/M3/test-inventory.json",
    "evidence/m3-control/results.json",
    "evidence/M4/results.json",
    "evidence/M4/scenarios.json",
    "evidence/M5/runs.json",
    "evidence/M6/results.json",
    "evidence/review-fixes/jenkins-runs.json",
    "evidence/v4/task-1.3/jenkins-runs.json",
    "evidence/pr-flow/task-3.1/pr-scenarios.json",
    "evidence/fresh-clone/rerun/verify/verification.json",
    "evidence/pr-flow/task-2.5/verify-local/verification.json",
    "evidence/task-1.3a/immutable-tag.json",
    "evidence/v4/task-1.2/selector-regression/selector-regression.json",
]

CHECKS = 0


def check(condition, label):
    global CHECKS
    if not condition:
        raise AssertionError(label)
    CHECKS += 1
    print("PASS " + label)


def load(rel, root=ROOT):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return json.load(fh)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_generator(root=ROOT):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("JENKINS_") and k != "COMPOSE_PROJECT_NAME"}
    proc = subprocess.run([sys.executable,
                           os.path.join(root, "harness", "scripts",
                                        "build_site_data.py")],
                          cwd=root, text=True, capture_output=True, env=env)
    return proc


def test_source_consistency():
    data = load("site/data.json")
    m3 = load("evidence/M3/results.json")
    test_inventory = load("evidence/M3/test-inventory.json")
    control = load("evidence/m3-control/results.json")
    scenarios_doc = load("evidence/M4/scenarios.json")
    m5 = load("evidence/M5/runs.json")
    pr = load("evidence/pr-flow/task-3.1/pr-scenarios.json")
    libraries = load("evidence/site/library-releases.json")
    fresh = load("evidence/fresh-clone/rerun/verify/verification.json")

    check(data["full_reactor"]["conditions"]["upstream_failed_or_errored"] == 221,
          "upstream failed-or-errored count is 221")
    check(test_inventory["workload"]["m0c_failed_or_errored"] == 221,
          "M0C source records 221 failed-or-errored tests")
    check("evidence/M3/test-inventory.json"
          in data["full_reactor"]["conditions"]["sources"],
          "upstream failure count is sourced from the M3 test inventory")

    runs = data["full_reactor"]["runs"]
    by_key = {(r["variant"], r["label"]): r for r in runs}
    groups = {
        "baseline": m3["baseline_full"],
        "rescued": m3["rescued"],
        "control": control["control_runs"],
    }
    for variant, source_runs in groups.items():
        for source in source_runs:
            generated = by_key[(variant, source["label"])]
            check(generated["build"] == source["build_number"],
                  f"{variant} {source['label']} build matches source")
            check(generated["result"] == source["result"],
                  f"{variant} {source['label']} result matches source")
            check(generated["jenkins_duration_ms"] == source["jenkins_duration_ms"],
                  f"{variant} {source['label']} duration matches source")
            check(generated["host_wall_clock_s"] == source["host_wall_clock_s"],
                  f"{variant} {source['label']} host wall matches source")
    check(len(runs) == 9, "nine full-reactor runs are present")

    for variant in ("baseline", "rescued", "control"):
        durations = [r["jenkins_duration_ms"] for r in runs if r["variant"] == variant]
        hosts = [r["host_wall_clock_s"] for r in runs if r["variant"] == variant]
        generated = data["full_reactor"]["medians"][variant]
        check(generated["median_ms"] == int(statistics.median(durations)),
              f"{variant} median recomputes from runs")
        check(generated["min_ms"] == min(durations),
              f"{variant} minimum recomputes from runs")
        check(generated["max_ms"] == max(durations),
              f"{variant} maximum recomputes from runs")
        check(generated["host_median_s"] == round(statistics.median(hosts), 1),
              f"{variant} host median recomputes from runs")

    comparison = data["full_reactor"]["control_comparison"]
    base = data["full_reactor"]["medians"]["baseline"]
    ctrl = data["full_reactor"]["medians"]["control"]
    difference = base["median_ms"] - ctrl["median_ms"]
    check(comparison["median_difference_ms"] == difference,
          "control difference recomputes from medians")
    check(comparison["median_difference_pct_of_baseline"]
          == round(difference * 100.0 / base["median_ms"], 2),
          "control difference percentage recomputes from medians")
    check(comparison["ranges_overlap"] is True,
          "control and baseline ranges are recorded as overlapping")
    check(comparison["overlap_range_ms"]
          == [max(base["min_ms"], ctrl["min_ms"]), min(base["max_ms"], ctrl["max_ms"])],
          "overlap range recomputes from ranges")

    one = next(c for c in data["selective_builds"]["selector_cases"]
               if c["name"] == "one-service")
    source_one = next(s for s in scenarios_doc["scenarios"] if s["name"] == "one-service")
    check(one["reactor_count"] == source_one["maven_validate"]["reactor_count"],
          "service selector reactor count matches source")
    check(one["selected_modules"] == source_one["maven_validate"]["modules"],
          "service selector modules match source")
    m4 = load("evidence/M4/results.json")
    check(data["selective_builds"]["service_change"]["median_ms"]
          == m4["incremental_medians"]["jenkins_duration_ms"],
          "service-change median matches the incremental evidence")

    root = next(c for c in data["selective_builds"]["selector_cases"]
                if c["name"] == "root-pom")
    source_root = next(s for s in scenarios_doc["scenarios"] if s["name"] == "root-pom")
    check(root["mode"] == "full"
          and root["reactor_count"] == source_root["maven_validate"]["reactor_count"],
          "fail-closed root POM case falls back to the full reactor")
    check(data["selective_builds"]["fail_closed"]["policy"]
          == load("evidence/M4/results.json")["selector"]["safe_fallback"],
          "fail-closed policy text matches source")

    generated_m5 = next(r for r in data["quality_gates"]["train_ticket"]
                        if r["stage"] == "M5" and r["build"] == 18)
    source_m5 = next(r for r in m5 if r["build"] == 18)
    check(generated_m5["result"] == source_m5["result"] == "FAILURE",
          "Train-Ticket coverage violation result matches source")
    check(generated_m5["coverage_state"] == source_m5["coverage"] == "FAIL",
          "Train-Ticket coverage violation state matches source")
    check(generated_m5["coverage_value"] == source_m5["coverage_value"],
          "Train-Ticket coverage violation value matches source")

    pr_data = {s["scenario"]: s for s in data["quality_gates"]["petclinic"]["pr"]}
    pr_source = {s["scenario"]: s for s in pr["scenarios"]}
    for name in pr_data:
        check(pr_data[name]["build"] == pr_source[name]["build"],
              f"PR {name} build matches export")
        check(pr_data[name]["result"] == pr_source[name]["result"],
              f"PR {name} result matches export")
        check(pr_data[name]["project"]["value"] == pr_source[name]["project"]["value"],
              f"PR {name} project coverage matches export")
        check(pr_data[name]["modified_lines"]["gate"]
              == pr_source[name]["modified_lines"]["gate"],
              f"PR {name} modified-lines gate matches export")
        check(pr_data[name]["pmd"]["new"] == pr_source[name]["pmd"]["new"],
              f"PR {name} PMD new count matches export")

    release = next(r for r in data["reproducibility"]["library_releases"]
                   if r["tag"] == "lib-v1.1.1")
    source_release = next(r for r in libraries["releases"] if r["tag"] == "lib-v1.1.1")
    check(release["commit"] == source_release["commit"],
          "library release commit matches source")
    check(release["vars_tree"] == source_release["vars_tree"],
          "library release tree matches source")

    verification = data["reproducibility"]["verification"][0]
    check(verification["passed"] == fresh["passed"] == 67,
          "fresh-clone verification pass count matches source")
    check(verification["failed"] == fresh["failed"] == 0,
          "fresh-clone verification failure count matches source")
    check(verification["checks"] == len(fresh["checks"]) == 67,
          "fresh-clone verification check count matches source")


def test_provenance():
    data = load("site/data.json")
    evidence_root = os.path.realpath(os.path.join(ROOT, "evidence"))
    sources = []

    def walk(node, path="$"):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "source":
                    check(isinstance(value, str), f"source is a string at {path}")
                    check(value.endswith(".json"), f"source is JSON at {path}")
                    resolved = os.path.realpath(os.path.join(ROOT, value))
                    check(resolved.startswith(evidence_root + os.sep),
                          f"source stays under evidence at {path}")
                    check(os.path.isfile(resolved), f"source exists at {path}")
                    sources.append(value)
                else:
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(data)
    check(len(sources) == 110, "record-level source inventory is 110")
    check(len(set(sources)) == 14, "record-level distinct sources is 14")

    loaded = set(data["provenance"]["sources"])
    check(len(loaded) == 17, "generator loaded 17 evidence JSON files")
    check(loaded - set(sources)
          == {"evidence/v4/task-1.2/selector-regression/selector-regression.json",
              "evidence/site/images.json",
              "evidence/M3/test-inventory.json"},
          "the non-record-level load sources are the selector regression, image catalog and upstream inventory")

    for problem in data["problems"]:
        path = os.path.join(ROOT, problem["source_file"])
        lines = open(path, encoding="utf-8").read().splitlines()
        check(lines[problem["source_line"] - 1].strip() == problem["text"],
              f"problem {problem['id']} line text matches provenance")

    for record in data["full_reactor"]["runs"]:
        check("source" in record and record["classification"] == "historical measurement",
              f"full-reactor run {record['label']} is classified historical")
    for record in data["quality_gates"]["train_ticket"]:
        if record["stage"] == "M5":
            check(record["classification"] == "historical milestone evidence",
                  f"M5 gate build {record['build']} is classified historical")
    for record in data["quality_gates"]["petclinic"]["pr"]:
        check(record["classification"] == "current acceptance",
              f"PR {record['scenario']} is current acceptance evidence")
        check(record["source"] == "evidence/pr-flow/task-3.1/pr-scenarios.json",
              f"PR {record['scenario']} uses the acceptance export")
    pmd = [r for r in data["quality_gates"]["petclinic"]["pr"]
           if r["scenario"].startswith("pmd")]
    check(all(r["modified_lines"]["gate"] == "SUCCESS" for r in pmd),
          "PMD scenarios are the corrected runs, not the diagnostic coverage failures")
    small = [r for r in data["quality_gates"]["petclinic"]["pr"]
             if r["scenario"].startswith("small")]
    check(all(r["failing_gates"] == ["modified lines"] for r in small),
          "small scenarios fail on modified lines only")
    check(load("evidence/pr-flow/task-3.1/pr-scenarios.json")["suite"]
          .startswith("petclinic multibranch PR acceptance"),
          "PR export is marked as the acceptance suite")


def test_determinism():
    before = sha256(DATA)
    first = run_generator()
    check(first.returncode == 0, "generator runs without Jenkins or the network")
    check(sha256(DATA) == before, "first regeneration is byte-identical")
    second = run_generator()
    check(second.returncode == 0, "generator runs a second time")
    check(sha256(DATA) == before, "second regeneration is byte-identical")
    check(before == "5bc6e56d5e2c085e19a98905462ba35ebeeda8332810a02007f14ed27ef0d59e",
          "output hash matches the corrected Phase 4 hash")

    tree = ast.parse(open(GEN, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    check(not imported & {"urllib", "requests", "socket", "http", "ssl", "ftplib"},
          "generator imports no network modules")


def make_fixture(tmp):
    target = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(target, "harness", "scripts"))
    shutil.copy2(GEN, os.path.join(target, "harness", "scripts", "build_site_data.py"))
    for rel in EVIDENCE:
        dst = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)
    baseline = os.path.join(target, BASELINE)
    os.makedirs(os.path.dirname(baseline), exist_ok=True)
    shutil.copy2(os.path.join(ROOT, BASELINE), baseline)
    assets = os.path.join(ROOT, "site", "assets")
    if os.path.isdir(assets):
        shutil.copytree(assets, os.path.join(target, "site", "assets"))
    return target


def expect_failure(label, mutate, fragment):
    with tempfile.TemporaryDirectory(prefix="prk-site-test-") as tmp:
        target = make_fixture(tmp)
        mutate(target)
        proc = subprocess.run(
            [sys.executable,
             os.path.join(target, "harness", "scripts", "build_site_data.py")],
            cwd=target, text=True, capture_output=True)
        check(proc.returncode != 0, f"{label} fails with a nonzero exit code")
        check(fragment in (proc.stderr + proc.stdout),
              f"{label} explains the failure")


def rewrite(path, fn):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    fn(data)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def test_failures():
    def missing(target):
        os.remove(os.path.join(target, "evidence/M4/scenarios.json"))

    def invalid_json(target):
        with open(os.path.join(target, "evidence/M5/runs.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")

    def missing_field(target):
        def mutate(data):
            del data["baseline_full"][0]["build_number"]
        rewrite(os.path.join(target, "evidence/M3/results.json"), mutate)

    def bad_duration(target):
        def mutate(data):
            data["baseline_full"][0]["jenkins_duration_ms"] = "fast"
        rewrite(os.path.join(target, "evidence/M3/results.json"), mutate)

    def wrong_median(target):
        def mutate(data):
            data["medians"]["baseline_full"]["jenkins_duration_ms"] = 1
        rewrite(os.path.join(target, "evidence/M3/results.json"), mutate)

    def bad_percentage(target):
        def mutate(data):
            for entry in data["scenarios"]:
                if entry["scenario"] == "small-untested-change-1":
                    entry["project"]["value"] = "120%"
        rewrite(os.path.join(target, "evidence/pr-flow/task-3.1/pr-scenarios.json"),
                mutate)

    def broken_review_source(target):
        def mutate(data):
            data["reviews"][0]["regression_evidence"] = ["evidence/does-not-exist.json"]
        rewrite(os.path.join(target, "evidence/site/catalog.json"), mutate)

    expect_failure("missing required evidence", missing,
                   "missing required evidence file")
    expect_failure("invalid JSON syntax", invalid_json, "invalid JSON")
    expect_failure("missing mandatory field", missing_field, "missing field")
    expect_failure("non-numeric duration", bad_duration, "non-numeric")
    expect_failure("incorrect recorded median", wrong_median,
                   "recorded median does not match")
    expect_failure("invalid coverage percentage", bad_percentage,
                   "percentage out of range")
    expect_failure("broken source reference", broken_review_source,
                   "references missing evidence")


def test_static_copy():
    html = open(INDEX, encoding="utf-8").read().lower()
    for phrase in ("build accelerator", "3 of 43", "nine measured", "nine measured runs",
                   "7 reproduced", "seven reproduced", "five corrections", "two gates",
                   "two independent", "seven recorded", "all nine runs",
                   "all seven recorded", "inspect the five", "five selector",
                   "43 entries", "3 entries", "29 lines", "medians of three runs",
                   "one new pmd finding"):
        check(phrase not in html,
              f"index.html does not duplicate measured copy: {phrase}")


def test_presentation():
    data = load("site/data.json")
    text = open(DATA, encoding="utf-8").read()
    pr = {s["scenario"]: s for s in data["quality_gates"]["petclinic"]["pr"]}
    check(set(pr) == {"main", "small-untested-change-1", "small-untested-change-2",
                      "pmd-violation-1", "pmd-violation-2", "fixed", "docs-only"},
          "all seven PetClinic scenarios are present")
    for name in ("pmd-violation-1", "pmd-violation-2"):
        check(pr[name]["project"]["gate"] == "SUCCESS",
              f"{name} project coverage passes")
        check(pr[name]["modified_lines"]["gate"] == "SUCCESS",
              f"{name} modified-lines coverage passes")
        check(pr[name]["pmd"]["new"] == 1, f"{name} reports exactly one new PMD issue")
        check(pr[name]["failing_gates"] == ["pmd"],
              f"{name} fails on PMD only")
    for name in ("small-untested-change-1", "small-untested-change-2"):
        check(pr[name]["project"]["gate"] == "SUCCESS",
              f"{name} project coverage passes")
        check(pr[name]["modified_lines"]["gate"] == "FAILURE",
              f"{name} modified-lines coverage fails")
    check(pr["docs-only"]["modified_lines"]["no_modified_lines"] is True,
          "docs-only records no modified lines")
    check(pr["docs-only"]["modified_lines"]["value"] is None,
          "docs-only does not fabricate a coverage percentage")
    check(pr["fixed"]["result"] == "SUCCESS" and not pr["fixed"]["failing_gates"],
          "fixed scenario passes all gates")
    check(len(data["full_reactor"]["runs"]) == 9,
          "nine benchmark runs remain visible")
    check("38.9" not in text, "the withdrawn 38.9% headline is absent")
    check("no same-workload speed-up is claimed"
          in data["full_reactor"]["control_comparison"]["correction"],
          "the correction states that no same-workload speed-up is claimed")
    check(data["full_reactor"]["control_comparison"]["ranges_overlap"] is True,
          "the control comparison keeps the overlapping-range qualification")
    for record in data["full_reactor"]["runs"]:
        check(isinstance(record.get("source"), str),
              f"benchmark run {record['label']} keeps an evidence source")


def test_reactor_identity():
    """Lock the recorded Maven reactor counts without deduplicating labels."""
    data = load("site/data.json")
    cases = {case["name"]: case for case in data["selective_builds"]["selector_cases"]}
    building = re.compile(r"^\[INFO\] Building (.+?) (\S+) +\[(\d+)/(\d+)\]")

    def parse(rel):
        entries = []
        lines = open(os.path.join(ROOT, rel), encoding="utf-8").read().splitlines()
        for index, line in enumerate(lines):
            match = building.match(line)
            if not match:
                continue
            path = None
            if index + 1 < len(lines):
                source = re.match(r"^\[INFO\]\s+from (.+)$", lines[index + 1])
                if source:
                    path = source.group(1).strip()
            entries.append({"label": match.group(1).strip() + " " + match.group(2),
                            "path": path, "total": int(match.group(4))})
        return entries

    expected = {
        "ts-common": {"entries": 42, "unique_paths": 42, "unique_labels": 41,
                      "gateway": False},
        "root-pom": {"entries": 43, "unique_paths": 43, "unique_labels": 42,
                     "gateway": True},
    }
    parsed = {}
    for name, wanted in expected.items():
        entries = parse(f"evidence/M4/raw/scenarios/{name}.log")
        parsed[name] = entries
        labels = [entry["label"] for entry in entries]
        paths = [entry["path"] for entry in entries]
        check(len(entries) == wanted["entries"],
              f"{name} raw log records {wanted['entries']} reactor entries")
        check(len(set(paths)) == wanted["unique_paths"] and None not in paths,
              f"{name} raw log records {wanted['unique_paths']} distinct module paths")
        check(len(set(labels)) == wanted["unique_labels"],
              f"{name} raw log records {wanted['unique_labels']} distinct display labels")
        check(all(entry["total"] == wanted["entries"] for entry in entries),
              f"{name} reactor summary totals agree with the entry count")
        check(cases[name]["reactor_count"] == wanted["entries"],
              f"{name} site data keeps the recorded reactor count")
        check(cases[name]["selected_modules"] == labels,
              f"{name} site data copies the reactor summary without deduplication")
        check(("ts-gateway-service 1.0" in labels) is wanted["gateway"],
              f"{name} gateway presence matches the recorded downstream set")

    ts_common = parsed["ts-common"]
    duplicates = [entry for entry in ts_common
                  if entry["label"] == "ts-consign-price-service 1.0"]
    check(len(duplicates) == 2,
          "the shared-module reactor has two ts-consign-price-service display labels")
    check({entry["path"] for entry in duplicates} ==
          {"ts-consign-price-service/pom.xml", "ts-consign-service/pom.xml"},
          "the duplicate labels come from two distinct module paths")
    check(cases["ts-common"]["selected_modules"].count("ts-consign-price-service 1.0") == 2,
          "site data keeps both recorded ts-common module entries")
    check(not any("ts-consign-service" in module
                  for module in cases["ts-common"]["selected_modules"]),
          "site data does not invent the hidden artifactId label")
    consign = open(os.path.join(
        ROOT, "evidence/site/evidence-in-motion-validation/ts-common/ts-consign-service-pom.xml"),
        encoding="utf-8").read()
    gateway = open(os.path.join(
        ROOT, "evidence/site/evidence-in-motion-validation/ts-common/ts-gateway-service-pom.xml"),
        encoding="utf-8").read()
    check("<artifactId>ts-consign-service</artifactId>" in consign
          and "<name>ts-consign-price-service</name>" in consign,
          "ts-consign-service proves the artifactId and display name differ")
    check("<artifactId>ts-common</artifactId>" not in gateway,
          "ts-gateway-service does not depend on ts-common")
    check(cases["root-pom"]["reactor_count"] == 43
          and cases["ts-common"]["reactor_count"] == 42,
          "the 43-entry full reactor and 42-entry dependent reactor remain distinct")


def test_images():
    data = load("site/data.json")
    catalog = load("evidence/site/images.json")
    pr = load("evidence/pr-flow/task-3.1/pr-scenarios.json")
    m4 = load("evidence/M4/results.json")
    entries = data["images"]["entries"]
    check(catalog["catalog"] is not None, "image catalog has a description")
    check(4 <= len(entries) <= 6, "four to six screenshots are published")
    check({e["id"] for e in entries} == {
        "multibranch-branches", "coverage-overview",
        "coverage-modified-lines", "pmd-new-issue", "selector-decision"},
        "all five approved screenshots are present")
    pr_by = {s["scenario"]: s for s in pr["scenarios"]}
    m4_runs = {r["build_number"]: r for r in m4["incremental_runs"]}
    for entry in entries:
        check(set(entry["widths"]) == {"800", "1600"},
              f"image {entry['id']} has both widths")
        for width, rel in entry["widths"].items():
            path = os.path.join(ROOT, "site", rel)
            check(os.path.isfile(path), f"image {entry['id']} {width} exists")
            check(os.path.getsize(path) < 200000,
                  f"image {entry['id']} {width} is under 200 KB")
        check(len(entry["alt"]) > 30, f"image {entry['id']} has descriptive alt text")
        check(bool(entry["caption"]), f"image {entry['id']} has a caption")
        check(entry["metadata_source"] == "evidence/site/images.json",
              f"image {entry['id']} uses the evidence catalog")
        if entry["source"] == "evidence/pr-flow/task-3.1/pr-scenarios.json":
            scenario = pr_by[entry["scenario"]]
            check(scenario["build"] == entry["build"],
                  f"image {entry['id']} build matches its scenario")
        else:
            run = m4_runs[entry["build"]]
            check(run["label"] == entry["scenario"],
                  f"image {entry['id']} build matches the M4 run")
    decisions = open(os.path.join(ROOT, "docs/decisions.md"), encoding="utf-8").read()
    check("7ee38b4ecfccfe4ad116044204d2f5a7aa02cd5dcdb164a6df0c6c35790f1d05" in decisions,
          "the original Task 3.1 data hash is preserved in the decision record")


def main():
    print("== source-to-output consistency ==")
    test_source_consistency()
    print("== provenance integrity ==")
    test_provenance()
    print("== deterministic generation ==")
    test_determinism()
    print("== failure behavior ==")
    test_failures()
    print("== reactor identity ==")
    test_reactor_identity()
    print("== screenshot metadata ==")
    test_images()
    print("== presentation integrity ==")
    test_static_copy()
    test_presentation()
    print(f"all site data checks passed: {CHECKS}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        sys.exit(1)
