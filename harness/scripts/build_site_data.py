#!/usr/bin/env python3
"""Build deterministic website data from verified evidence JSON.

Every measurement in site/data.json comes from evidence/**/*.json. The script
fails loudly when a required evidence file or field is missing, when a recorded
median does not match its runs, or when a numeric value is out of range. It does
not contact Jenkins or the network.
"""
import json
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "site", "data.json")

CATALOG = "evidence/site/catalog.json"
IMAGES = "evidence/site/images.json"
LIBRARIES = "evidence/site/library-releases.json"
M3 = "evidence/M3/results.json"
M3_TEST_INVENTORY = "evidence/M3/test-inventory.json"
CONTROL = "evidence/m3-control/results.json"
M4 = "evidence/M4/results.json"
M4_SCENARIOS = "evidence/M4/scenarios.json"
M5 = "evidence/M5/runs.json"
M6 = "evidence/M6/results.json"
REVIEW_RUNS = "evidence/review-fixes/jenkins-runs.json"
V4_RUNS = "evidence/v4/task-1.3/jenkins-runs.json"
PR = "evidence/pr-flow/task-3.1/pr-scenarios.json"
FRESH = "evidence/fresh-clone/rerun/verify/verification.json"
DEMO_VERIFY = "evidence/pr-flow/task-2.5/verify-local/verification.json"
IMMUTABLE = "evidence/task-1.3a/immutable-tag.json"
SELECTOR_REGRESSION = "evidence/v4/task-1.2/selector-regression/selector-regression.json"

REQUIRED = [CATALOG, IMAGES, LIBRARIES, M3, M3_TEST_INVENTORY, CONTROL, M4, M4_SCENARIOS, M5, M6,
            REVIEW_RUNS, V4_RUNS, PR, FRESH, DEMO_VERIFY, IMMUTABLE,
            SELECTOR_REGRESSION]
PCT = re.compile(r"^(\d+(?:\.\d+)?)%$")

USED = set()


def fail(message):
    raise RuntimeError("build_site_data: " + message)


def load(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        fail(f"missing required evidence file: {rel}")
    USED.add(rel)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {rel}: {exc}")


def require(record, fields, where):
    for field in fields:
        if field not in record or record[field] is None:
            fail(f"missing field '{field}' in {where}")


def number(value, where, minimum=0):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        fail(f"non-numeric value in {where}: {value!r}")
    if value < minimum:
        fail(f"out-of-range numeric value in {where}: {value!r}")
    return value


def percent(value, where):
    match = PCT.match(value) if isinstance(value, str) else None
    if not match:
        fail(f"invalid percentage in {where}: {value!r}")
    parsed = float(match.group(1))
    if not 0.0 <= parsed <= 100.0:
        fail(f"percentage out of range in {where}: {value!r}")
    return parsed


def source(rel):
    if rel not in USED:
        fail(f"record source was not loaded: {rel}")
    return rel


def problems(catalog):
    records = catalog.get("pipeline_problems")
    if not records:
        fail("catalog has no pipeline_problems")
    out = []
    for item in records:
        require(item, ["id", "source_file", "source_line", "text", "explanation",
                       "evidence_reference"], "pipeline problem")
        path = os.path.join(ROOT, item["source_file"])
        if not os.path.isfile(path):
            fail(f"problem {item['id']} references missing source file "
                 f"{item['source_file']}")
        lines = open(path, encoding="utf-8").read().splitlines()
        index = item["source_line"]
        if not isinstance(index, int) or not 1 <= index <= len(lines):
            fail(f"problem {item['id']} has invalid source_line {index!r}")
        if lines[index - 1].strip() != item["text"]:
            fail(f"problem {item['id']} source text does not match "
                 f"{item['source_file']}:{index}")
        out.append({
            "id": item["id"],
            "source_file": item["source_file"],
            "source_line": index,
            "text": item["text"],
            "explanation": item["explanation"],
            "evidence_reference": item["evidence_reference"],
            "source": source(CATALOG),
        })
    return out


def runs_of(runs, variant, rel):
    out = []
    for run in runs:
        require(run, ["label", "job", "build_number", "result",
                      "jenkins_duration_ms", "host_wall_clock_s"],
                f"{variant} run in {rel}")
        out.append({
            "variant": variant,
            "classification": "historical measurement",
            "label": run["label"],
            "job": run["job"],
            "build": run["build_number"],
            "result": run["result"],
            "jenkins_duration_ms": number(run["jenkins_duration_ms"],
                                          f"{rel} {run['label']} duration", 1),
            "host_wall_clock_s": number(run["host_wall_clock_s"],
                                        f"{rel} {run['label']} host wall", 0.001),
            "source": source(rel),
        })
    return out


def median_stats(runs, recorded, where):
    durations = [run["jenkins_duration_ms"] for run in runs]
    hosts = [run["host_wall_clock_s"] for run in runs]
    if len(durations) != 3:
        fail(f"{where} must have exactly three runs, found {len(durations)}")
    computed = {
        "runs": len(durations),
        "median_ms": int(statistics.median(durations)),
        "min_ms": min(durations),
        "max_ms": max(durations),
        "host_median_s": round(statistics.median(hosts), 1),
    }
    duration = recorded["jenkins_duration_ms"]
    recorded_median = duration["median"] if isinstance(duration, dict) else duration
    if int(recorded_median) != computed["median_ms"]:
        fail(f"{where} recorded median does not match its runs")
    if isinstance(duration, dict):
        if int(duration["min"]) != computed["min_ms"]:
            fail(f"{where} recorded minimum does not match its runs")
        if int(duration["max"]) != computed["max_ms"]:
            fail(f"{where} recorded maximum does not match its runs")
    return computed


def full_reactor(m3, control, test_inventory):
    baseline = runs_of(m3["baseline_full"], "baseline", M3)
    rescued = runs_of(m3["rescued"], "rescued", M3)
    control_runs = runs_of(control["control_runs"], "control", CONTROL)
    runs = baseline + rescued + control_runs
    if len(runs) != 9:
        fail(f"expected nine full-reactor runs, found {len(runs)}")

    medians = {
        "baseline": median_stats(baseline, m3["medians"]["baseline_full"],
                                 "M3 baseline"),
        "rescued": median_stats(rescued, m3["medians"]["rescued"],
                                "M3 rescued"),
        "control": median_stats(control_runs, control["timing"]["control"],
                                "packaging control"),
    }
    workload = m3["test_inventory"]["workload"]
    upstream = test_inventory.get("workload", {})
    require(upstream, ["m0c_failed_or_errored"], "M3 upstream test inventory")
    if int(workload["modules"]) != 43:
        fail("M3 workload module count is not 43")
    if int(workload["tests"]) != 626:
        fail("M3 workload test count is not 626")

    base = medians["baseline"]
    ctrl = medians["control"]
    difference_ms = base["median_ms"] - ctrl["median_ms"]
    difference_pct = round(difference_ms * 100.0 / base["median_ms"], 2)
    overlaps = base["min_ms"] <= ctrl["max_ms"] and ctrl["min_ms"] <= base["max_ms"]

    packaging = control["packaging"]
    return {
        "conditions": {
            "pinned_commit": m3["source"]["commit"],
            "reactor_entries": int(workload["modules"]),
            "tests": int(workload["tests"]),
            "failed_or_errored": int(workload["failed_or_errored"]),
            "upstream_failed_or_errored": int(upstream["m0c_failed_or_errored"]),
            "threads": control["condition"]["threads"],
            "maven_command": control["condition"]["maven_command_expected"],
            "cache": m3["methodology"]["cache"],
            "workload_note": m3["methodology"]["workload_equivalence"],
            "sources": [M3, CONTROL, M3_TEST_INVENTORY],
        },
        "runs": runs,
        "medians": medians,
        "control_comparison": {
            "median_difference_ms": difference_ms,
            "median_difference_pct_of_baseline": difference_pct,
            "baseline_range_ms": [base["min_ms"], base["max_ms"]],
            "control_range_ms": [ctrl["min_ms"], ctrl["max_ms"]],
            "ranges_overlap": overlaps,
            "overlap_range_ms": [max(base["min_ms"], ctrl["min_ms"]),
                                 min(base["max_ms"], ctrl["max_ms"])] if overlaps else None,
            "packaging": {
                "baseline_install_counts": packaging["baseline_install_counts"],
                "baseline_test_counts": packaging["baseline_test_counts"],
                "rescued_verify_counts": packaging["rescued_verify_counts"],
                "control_verify_counts": packaging["control_verify_counts"],
                "assessment": packaging["assessment"],
                "failing_module_example": packaging.get("failing_module_example"),
            },
            "correction": (
                "The packaging workload is only partially equal: the baseline "
                "installs all 43 entries in a separate pass, the control uses "
                "verify without install, and the observed ranges overlap. The "
                "same-workload time saving could not be isolated with confidence "
                "on this codebase; no same-workload speed-up is claimed."
            ),
            "source": source(CONTROL),
        },
        "limitations": [{"text": text, "source": source(CONTROL)}
                        for text in control.get("limitations", [])]
                       + [{"text": text, "source": source(M3)}
                          for text in m3.get("limitations", [])],
        "sources": [M3, CONTROL],
    }


def selective(m4, scenarios_doc):
    require(m4, ["selector", "incremental_runs", "incremental_medians",
                 "scope_comparison", "test_inventory", "m3_full_scope_reference"],
            "M4 results")
    cases = []
    for scenario in scenarios_doc.get("scenarios", []):
        require(scenario, ["name", "changed", "selector", "maven_validate"],
                "M4 scenario")
        sel = scenario["selector"]
        validate = scenario["maven_validate"]
        cases.append({
            "name": scenario["name"],
            "changed_path": scenario["changed"],
            "mode": sel.get("M4_MODE"),
            "reason": sel.get("M4_REASON"),
            "modules_flag": sel.get("M4_PL"),
            "upstream": sel.get("M4_AM") == "1",
            "downstream": sel.get("M4_AMD") == "1",
            "reactor_count": validate.get("reactor_count"),
            "exit_code": validate.get("exit_code"),
            "selected_modules": list(validate.get("modules", [])),
            "source": source(M4_SCENARIOS),
        })
    if len(cases) != 5:
        fail(f"expected five selector cases, found {len(cases)}")

    incremental = m4["incremental_runs"]
    if len(incremental) != 3:
        fail("expected three incremental runs")
    first = incremental[0]
    reactor = (first.get("reactors") or [{}])[0]
    modules = [m["display_name"] for m in reactor.get("modules", [])]
    runs = []
    for run in incremental:
        require(run, ["label", "build_number", "result", "jenkins_duration_ms",
                      "host_wall_clock_s", "selection", "reactors"],
                "incremental run")
        runs.append({
            "classification": "historical measurement",
            "label": run["label"],
            "build": run["build_number"],
            "result": run["result"],
            "jenkins_duration_ms": number(run["jenkins_duration_ms"],
                                          "incremental duration", 1),
            "host_wall_clock_s": number(run["host_wall_clock_s"],
                                        "incremental host wall", 0.001),
            "selection": run["selection"],
            "source": source(M4),
        })

    median = number(m4["incremental_medians"]["jenkins_duration_ms"],
                    "incremental median", 1)
    computed = int(statistics.median([r["jenkins_duration_ms"] for r in runs]))
    if computed != median:
        fail("recorded incremental median does not match its runs")

    return {
        "full_reactor": {
            "reactor_entries": 43,
            "tests": m4["m3_full_scope_reference"]["tests"],
            "median_ms": number(m4["m3_full_scope_reference"]["rescued_median_ms"],
                                "full-scope median", 1),
            "source": source(M4),
        },
        "service_change": {
            "reactor_entries": len(modules),
            "selected_modules": modules,
            "tests": m4["test_inventory"]["incremental"]["tests"],
            "median_ms": median,
            "runs": runs,
            "source": source(M4),
        },
        "selector_cases": cases,
        "fail_closed": {
            "policy": m4["selector"]["safe_fallback"],
            "method": m4["selector"]["method"],
            "source": source(M4),
        },
        "comparison": dict(m4["scope_comparison"], source=source(M4)),
        "limitations": [{"text": text, "source": source(M4)}
                        for text in m4.get("limitations", [])],
        "sources": [M4, M4_SCENARIOS],
    }


def train_ticket_gates(m5, review, v4):
    out = []
    for run in m5:
        require(run, ["scenario", "build", "result", "coverage",
                      "coverage_value", "static", "static_value", "decision"], "M5 run")
        out.append({
            "stage": "M5", "classification": "historical milestone evidence",
            "scenario": run["scenario"], "job": run.get("job"),
            "branch": run.get("branch"),
            "build": run["build"], "result": run["result"],
            "coverage_state": run["coverage"],
            "coverage_value": run["coverage_value"],
            "static_state": run["static"],
            "static_value": run["static_value"],
            "decision": run["decision"],
            "source": source(M5),
        })
    for run in review.get("runs", []):
        require(run, ["milestone", "scenario", "job", "build", "result",
                      "decision"], "review run")
        out.append({
            "stage": "review " + run["milestone"],
            "classification": "review revalidation",
            "scenario": run["scenario"],
            "job": run["job"], "build": run["build"], "result": run["result"],
            "coverage_state": run.get("coverage"),
            "coverage_value": run.get("coverage_value"),
            "static_state": run.get("static"),
            "static_value": run.get("static_value"),
            "decision": run["decision"],
            "guard": run["decision"] == "BLOCKED_BY_GUARD",
            "reference_build": run.get("reference_build"),
            "reference_job": run.get("reference_job"),
            "source": source(REVIEW_RUNS),
        })
    for run in v4.get("runs", []):
        require(run, ["application", "job", "build", "result", "duration_ms",
                      "summary"], "v4 run")
        summary = run["summary"]
        out.append({
            "stage": "current verification",
            "classification": "current verification",
            "scenario": run["job"],
            "job": run["job"], "build": run["build"], "result": run["result"],
            "duration_ms": number(run["duration_ms"], "v4 duration", 1),
            "coverage_state": summary.get("coverage_state"),
            "coverage_value": summary.get("coverage_value"),
            "static_state": summary.get("static_state"),
            "static_value": summary.get("static_value"),
            "decision": "PASS" if run["result"] == "SUCCESS" else "BLOCK",
            "source": source(V4_RUNS),
        })
    if len(out) != 29:
        fail(f"expected 29 Train-Ticket gate records, found {len(out)}")
    return out


def petclinic_gates(m6, pr):
    m6_runs = []
    for run in m6["scenarios"]:
        require(run, ["scenario", "branch", "build", "result", "coverage",
                      "coverage_value", "static", "static_value", "decision"], "M6 run")
        m6_runs.append({
            "stage": "M6", "classification": "historical milestone evidence",
            "scenario": run["scenario"], "job": "petclinic",
            "branch": run["branch"], "build": run["build"],
            "result": run["result"],
            "coverage_state": run["coverage"],
            "coverage_value": run["coverage_value"],
            "static_state": run["static"],
            "static_value": run["static_value"],
            "decision": run["decision"],
            "coverage_threshold": m6["coverage_threshold_percent"],
            "static_new_issue_threshold": m6["static_new_issue_threshold"],
            "source": source(M6),
        })
    if len(m6_runs) != 5:
        fail("expected five M6 gate scenarios")

    scenarios = pr.get("scenarios", [])
    expected = {"main", "small-untested-change-1", "small-untested-change-2",
                "pmd-violation-1", "pmd-violation-2", "fixed", "docs-only"}
    names = {s.get("scenario") for s in scenarios}
    if names != expected:
        fail(f"unexpected PetClinic PR scenario set: {sorted(names)}")
    pr_runs = []
    main_build = next(s["build"] for s in scenarios if s["scenario"] == "main")
    for entry in scenarios:
        require(entry, ["scenario", "job", "build", "result", "revision",
                        "library", "project", "modified_lines", "pmd",
                        "decision", "failing_gates"], "PR scenario")
        if "reference_build" not in entry:
            fail(f"PR {entry['scenario']} has no reference_build field")
        percent(entry["project"]["value"], f"PR {entry['scenario']} project")
        if entry["modified_lines"]["value"] is not None:
            percent(entry["modified_lines"]["value"],
                    f"PR {entry['scenario']} modified lines")
        number(entry["pmd"]["total"], f"PR {entry['scenario']} pmd total")
        number(entry["pmd"]["new"], f"PR {entry['scenario']} pmd new")
        if entry["scenario"] == "main":
            if entry["result"] != "SUCCESS" or entry["decision"] != "PASS":
                fail("PetClinic main acceptance build is not a clean pass")
            if entry["reference_build"] is not None:
                fail("PetClinic main must not reference another build")
        else:
            if entry["reference_build"] != main_build:
                fail(f"PR {entry['scenario']} does not reference main #{main_build}")
            if not str(entry["library"]).startswith("prk@lib-v1."):
                fail(f"PR {entry['scenario']} library is not a project release")
        if entry["scenario"].startswith("small-"):
            if entry["result"] != "FAILURE" or entry["failing_gates"] != ["modified lines"]:
                fail("small-untested-change does not fail on modified lines only")
        if entry["scenario"].startswith("pmd-"):
            if entry["result"] != "FAILURE" or entry["failing_gates"] != ["pmd"]:
                fail("pmd-violation does not fail on PMD only")
            if entry["pmd"]["new"] != 1:
                fail("pmd-violation does not report exactly one new issue")
            if entry["modified_lines"]["gate"] != "SUCCESS":
                fail("pmd-violation modified-lines gate did not pass")
        if entry["scenario"] == "fixed":
            if entry["result"] != "SUCCESS" or entry["failing_gates"]:
                fail("fixed branch is not a clean pass")
        if entry["scenario"] == "docs-only":
            if entry["result"] != "SUCCESS" or not entry["modified_lines"]["no_modified_lines"]:
                fail("docs-only does not report no modified lines")
        pr_runs.append(dict(entry, classification="current acceptance",
                            source=source(PR)))
    return {"m6": m6_runs, "pr": pr_runs, "pr_export": pr.get("export")}


IMAGE_SECTIONS = {"problem", "benchmark", "selective", "gates", "review",
                  "implementation", "method"}


def images(catalog, pr, m4):
    """Validate the screenshot catalog against the recorded build evidence."""
    entries = catalog.get("images")
    if not entries:
        fail("image catalog has no entries")
    if not 4 <= len(entries) <= 6:
        fail(f"expected 4 to 6 screenshot entries, found {len(entries)}")
    out = []
    seen = set()
    pr_by_name = {s["scenario"]: s for s in pr["scenarios"]}
    m4_runs = {r["build_number"]: r for r in m4["incremental_runs"]}
    for entry in entries:
        require(entry, ["id", "section", "job", "scenario", "build",
                        "capture_date", "alt", "caption", "widths", "source"],
                "image entry")
        if entry["id"] in seen:
            fail(f"duplicate image id: {entry['id']}")
        seen.add(entry["id"])
        if entry["section"] not in IMAGE_SECTIONS:
            fail(f"image {entry['id']} has an unknown section")
        if not isinstance(entry["build"], int) or entry["build"] < 1:
            fail(f"image {entry['id']} has an invalid build number")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["capture_date"]):
            fail(f"image {entry['id']} has an invalid capture date")
        if len(entry["alt"]) < 30 or not entry["caption"]:
            fail(f"image {entry['id']} needs a descriptive alt and caption")
        widths = entry["widths"]
        if set(widths) != {"800", "1600"}:
            fail(f"image {entry['id']} needs 800 and 1600 variants")
        for width, rel in widths.items():
            if not rel.startswith("assets/") or not rel.endswith(".webp"):
                fail(f"image {entry['id']} has an invalid asset path")
            path = os.path.join(ROOT, "site", rel)
            if not os.path.isfile(path):
                fail(f"image {entry['id']} asset is missing: {rel}")
            if os.path.getsize(path) >= 200000:
                fail(f"image {entry['id']} asset is 200 KB or larger: {rel}")
        if entry["source"] == PR:
            scenario = pr_by_name.get(entry["scenario"])
            if not scenario:
                fail(f"image {entry['id']} references an unknown PR scenario")
            if scenario["build"] != entry["build"]:
                fail(f"image {entry['id']} build does not match {entry['scenario']}")
            if not scenario["job"].startswith(entry["job"]):
                fail(f"image {entry['id']} job does not match its scenario")
        elif entry["source"] == M4:
            run = m4_runs.get(entry["build"])
            if not run or run["label"] != entry["scenario"]:
                fail(f"image {entry['id']} build does not match the M4 run")
        else:
            fail(f"image {entry['id']} source is not a validated build record")
        if entry["source"] not in USED:
            fail(f"image {entry['id']} source was not loaded: {entry['source']}")
        out.append({
            "id": entry["id"],
            "section": entry["section"],
            "job": entry["job"],
            "scenario": entry["scenario"],
            "build": entry["build"],
            "capture_date": entry["capture_date"],
            "alt": entry["alt"],
            "caption": entry["caption"],
            "width": entry.get("width"),
            "height": entry.get("height"),
            "widths": dict(widths),
            "source": source(entry["source"]),
            "metadata_source": source(IMAGES),
        })
    return {"catalog": catalog.get("catalog"), "capture_environment": catalog.get("capture_environment"), "entries": out}


def reviews(catalog):
    out = []
    for item in catalog.get("reviews", []):
        require(item, ["id", "finding", "correction", "regression_evidence"],
                "review")
        for ref in item["regression_evidence"]:
            if not os.path.isfile(os.path.join(ROOT, ref)):
                fail(f"review {item['id']} references missing evidence: {ref}")
            if ref not in USED:
                fail(f"review {item['id']} references unloaded evidence: {ref}")
        out.append({
            "id": item["id"],
            "classification": "review correction",
            "finding": item["finding"],
            "correction": item["correction"],
            "regression_evidence": item["regression_evidence"],
            "source": source(CATALOG),
        })
    if len(out) != 5:
        fail("expected five review records")
    return out


def reproducibility(catalog, fresh, demo_verify, libraries, immutable, m3, m6):
    passed = int(fresh.get("passed", -1))
    failed = int(fresh.get("failed", -1))
    if passed < 1 or failed != 0:
        fail("fresh-clone verification is not a clean pass")
    checks = len(fresh.get("checks", []))
    details = fresh.get("details", {})
    demo_passed = int(demo_verify.get("passed", -1))
    if demo_passed < 1 or int(demo_verify.get("failed", -1)) != 0:
        fail("demo verification is not a clean pass")

    releases = []
    for release in libraries.get("releases", []):
        require(release, ["tag", "tag_object", "commit", "vars_tree",
                          "jenkins_lib_tree"], "library release")
        releases.append(dict(release, source=source(LIBRARIES)))
    if {r["tag"] for r in releases} != {"lib-v1.0.0", "lib-v1.1.0", "lib-v1.1.1"}:
        fail("library release set is incomplete")

    if immutable.get("double_run_no_op") is not True:
        fail("immutable-tag evidence does not prove a no-op repeated preparation")
    if immutable["after_run_2"]["tag_commit"] != immutable["tag_commit"]:
        fail("immutable-tag evidence shows a moved tag")

    limitations = [{"text": item, "source": source(CATALOG)}
                   for item in catalog.get("limitations", [])]
    if not limitations:
        fail("catalog has no limitations")

    port = (details.get("controller_port_bindings") or [{}])[0]
    return {
        "environment": {
            "jenkins_version": details.get("jenkins_version"),
            "controller_image": details.get("controller_image"),
            "agent_image": details.get("agent_image"),
            "agent_labels": details.get("agent_labels"),
            "host_port": port.get("host_port"),
            "source": source(FRESH),
        },
        "fresh_clone": {
            "passed": passed,
            "failed": failed,
            "checks": checks,
            "timestamp": fresh.get("timestamp_utc"),
            "source": source(FRESH),
        },
        "verification": [
            {"name": "fresh clone rerun", "passed": passed, "failed": failed,
             "checks": checks, "source": source(FRESH)},
            {"name": "phase 2 demo local", "passed": demo_passed,
             "failed": int(demo_verify.get("failed", 0)),
             "checks": len(demo_verify.get("checks", [])),
             "source": source(DEMO_VERIFY)},
        ],
        "library_releases": releases,
        "immutable_tag_check": {
            "tag": immutable["tag"],
            "commit": immutable["tag_commit"],
            "tree": immutable["tag_tree"],
            "repeat_preparation_no_op": immutable["double_run_no_op"],
            "source": source(IMMUTABLE),
        },
        "pinned_sources": {
            "train_ticket": m3["source"]["commit"],
            "petclinic": m6["reference"],
        },
        "limitations": limitations,
    }


def main():
    catalog = load(CATALOG)
    image_catalog = load(IMAGES)
    libraries = load(LIBRARIES)
    m3 = load(M3)
    test_inventory = load(M3_TEST_INVENTORY)
    control = load(CONTROL)
    m4 = load(M4)
    scenarios_doc = load(M4_SCENARIOS)
    m5 = load(M5)
    m6 = load(M6)
    review = load(REVIEW_RUNS)
    v4 = load(V4_RUNS)
    pr = load(PR)
    fresh = load(FRESH)
    demo_verify = load(DEMO_VERIFY)
    immutable = load(IMMUTABLE)
    load(SELECTOR_REGRESSION)

    data = {
        "schema_version": 1,
        "project": "Pipeline Rescue Kit",
        "provenance": {
            "rule": "every measurement comes from evidence/**/*.json",
            "sources": sorted(USED | {CATALOG, LIBRARIES}),
        },
        "problems": problems(catalog),
        "full_reactor": full_reactor(m3, control, test_inventory),
        "selective_builds": selective(m4, scenarios_doc),
        "quality_gates": {
            "train_ticket": train_ticket_gates(m5, review, v4),
            "petclinic": petclinic_gates(m6, pr),
        },
        "images": images(image_catalog, pr, m4),
        "reviews": reviews(catalog),
        "reproducibility": reproducibility(catalog, fresh, demo_verify,
                                           libraries, immutable, m3, m6),
    }

    # Every record that represents a measurement or finding must carry a source.
    def walk(node, path="$"):
        if isinstance(node, dict):
            if {"label", "build", "scenario", "id", "tag"} & set(node):
                if "source" not in node and not path.endswith("conditions"):
                    if not (path.startswith("$.full_reactor.medians")):
                        fail(f"record without source at {path}")
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(data)
    for rel in USED:
        if not os.path.isfile(os.path.join(ROOT, rel)):
            fail(f"source does not exist: {rel}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
    print(f"sections: {len(data['problems'])} problems, "
          f"{len(data['full_reactor']['runs'])} full-reactor runs, "
          f"{len(data['selective_builds']['selector_cases'])} selector cases, "
          f"{len(data['quality_gates']['train_ticket'])} Train-Ticket gates, "
          f"{len(data['quality_gates']['petclinic']['m6'])} M6 gates, "
          f"{len(data['quality_gates']['petclinic']['pr'])} PR scenarios, "
          f"{len(data['reviews'])} reviews, "
          f"{len(data['reproducibility']['library_releases'])} releases")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
