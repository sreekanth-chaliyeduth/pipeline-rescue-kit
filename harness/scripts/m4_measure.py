#!/usr/bin/env python3
"""M4 incremental Jenkins measurement and docs-skip verification."""
import datetime
import json
import os
import re
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jenkins_api as api  # noqa: E402
import m2_measure as m2  # noqa: E402
import m3_measure as m3  # noqa: E402
import evidence_paths  # noqa: E402

EVID = os.path.join(ROOT, "evidence", "M4")
RAW = os.path.join(EVID, "raw")
REPO = os.path.join(EVID, "work", "train-ticket")
JOB = "train-ticket"
PIN = "313886e99befb94be6cd45f085c98e0019f59829"
SOURCE_REPO = "/src/train-ticket-m4"
ALLOWED_CONTAINERS = {"prk-m1-controller", "prk-m1-agent"}
SERVICE_BRANCH = "m4-service"
DOCS_BRANCH = "m4-docs"


def write_text(path, text):
    path = evidence_paths.generated_path(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_json(path, value):
    write_text(path, json.dumps(value, indent=2) + "\n")


def grep_value(console, key):
    match = re.search(rf"^(?:\[[^\]]+\]\s*)?{re.escape(key)}=(.*)$",
                      console, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip("'").strip('"')


def parse_m4_exits(console):
    return {m.group(1): (int(m.group(2)) if m.group(2).isdigit() else m.group(2))
            for m in re.finditer(r"PRK_MAVEN_EXIT_([A-Z_]+)=([^\s]+)", console)}


def branch_sha(branch):
    rc, out = m2.run(["git", "-C", REPO, "rev-parse", branch])
    if rc != 0:
        raise RuntimeError(out)
    return out.strip()


def preflight():
    rc, ps = m2.docker("ps", "--format", "{{.Names}}")
    if rc != 0:
        raise RuntimeError(f"docker ps failed: {ps.strip()}")
    names = {line.strip() for line in ps.splitlines() if line.strip()}
    unexpected = sorted(names - ALLOWED_CONTAINERS)
    if unexpected:
        raise RuntimeError(f"unexpected running containers: {unexpected}")
    api.wait_controller(120)
    api.wait_agent_online("linux-agent", 120)
    if m2.cache_mb() <= 0:
        raise RuntimeError("Maven cache is not warm")
    rc, sha = m2.run(["git", "-C", REPO, "rev-parse", "HEAD"])
    rc, service = m2.run(["git", "-C", REPO, "rev-parse", SERVICE_BRANCH])
    rc, docs = m2.run(["git", "-C", REPO, "rev-parse", DOCS_BRANCH])
    rc, stats = m2.docker("stats", "--no-stream", "--format",
                          "{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}")
    rc, disk = m2.run(["df", "-h", ROOT])
    lines = [
        "M4 preflight",
        "date UTC: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference/base: " + PIN,
        "source copy HEAD: " + sha.strip(),
        "service branch: " + SERVICE_BRANCH + " " + service.strip(),
        "docs branch: " + DOCS_BRANCH + " " + docs.strip(),
        "source mount: " + SOURCE_REPO,
        "docker ps: " + ",".join(sorted(names)),
        "docker stats:",
        stats.strip(),
        "cache MB: " + str(m2.cache_mb()),
        "disk:",
        disk.strip().splitlines()[-1] if disk.strip() else "",
    ]
    write_text(os.path.join(EVID, "environment.txt"), "\n".join(lines) + "\n")
    print("\n".join(lines[:8]))


def run_one(label, source_commit, expected_mode):
    raw_dir = os.path.join(RAW, label)
    os.makedirs(raw_dir, exist_ok=True)
    before = m2.cache_mb()
    print(f"\n=== {label} ({expected_mode}) ===")
    stop, thread = m2.start_stats(raw_dir)
    started = time.monotonic()
    started_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    try:
        number = m3.trigger_build(JOB, {
            "INCREMENTAL": "true",
            "SOURCE_REPO": SOURCE_REPO,
            "SOURCE_COMMIT": source_commit,
            "REFERENCE_COMMIT": PIN,
            "REACTOR_THREADS": "2",
        })
        build, console = m3.fetch_build(JOB, number)
        wfapi = m3.fetch_wfapi(JOB, number)
        report = m3.fetch_test_report(JOB, number)
    finally:
        stop.set()
        thread.join(timeout=10)
    ended = time.monotonic()
    finished_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    host_wall = round(ended - started, 1)

    write_text(os.path.join(raw_dir, "console.log"), console)
    write_json(os.path.join(raw_dir, "build.json"), build)
    write_json(os.path.join(raw_dir, "wfapi.json"), wfapi)
    write_json(os.path.join(raw_dir, "test-report.json"), report)

    after = m2.cache_mb()
    exits = parse_m4_exits(console)
    stages = m2.parse_stages(wfapi)
    reactors = m3.parse_reactors(console)
    report_tests = m2.parse_test_report(report)
    console_tests = m2.parse_console_tests(console)
    tests = console_tests if console_tests["reported"] else report_tests
    tests["jenkins_reported"] = report_tests["reported"]
    if report_tests["failed_cases"]:
        tests["failed_cases"] = report_tests["failed_cases"]
    m2.annotate_failed_cases(tests, console_tests)
    stage_sum = sum(s["duration_ms"] for s in stages
                    if s.get("duration_ms") is not None)
    rc, stats_text = m2.run(["cat", os.path.join(raw_dir, "docker-stats.log")])
    data = {
        "label": label,
        "source_commit": source_commit,
        "reference": PIN,
        "expected_mode": expected_mode,
        "build_number": number,
        "result": build.get("result"),
        "started_at": started_at,
        "finished_at": finished_at,
        "host_wall_clock_s": host_wall,
        "jenkins_duration_ms": build.get("duration"),
        "stages": stages,
        "stage_sum_ms": stage_sum,
        "post_estimate_ms": (build.get("duration") or 0) - stage_sum,
        "maven_exit_codes": exits,
        "selection": {
            "mode": grep_value(console, "PRK_MODE"),
            "pl": grep_value(console, "PRK_PL"),
            "reason": grep_value(console, "PRK_REASON"),
            "changed": grep_value(console, "PRK_CHANGED"),
            "reference": grep_value(console, "PRK_REFERENCE"),
            "head": grep_value(console, "PRK_HEAD"),
            "command": grep_value(console, "PRK_MAVEN_COMMAND"),
        },
        "reactors": reactors,
        "tests": tests,
        "cache_before_mb": before,
        "cache_after_mb": after,
        "peak_container_mem_gib": m2.peak_mem_gib(stats_text),
        "raw_dir": os.path.relpath(raw_dir, ROOT),
    }
    write_json(os.path.join(EVID, label + ".json"), data)

    print(f"build #{number}: {data['result']} duration={data['jenkins_duration_ms']} ms "
          f"host={host_wall}s")
    print("stages: " + ", ".join(
        f"{s['name']}={s['duration_ms']}ms/{s['status']}" for s in stages))
    print(f"selection: {data['selection']}")
    print(f"maven exits: {exits}")
    print(f"tests: {tests['reported']} reported, {tests['passed']} passed, "
          f"{tests['failures']} failures, {tests['errors']} errors, "
          f"{tests['skipped']} skipped")
    print("reactors: " + ", ".join(
        f"{r['phase']}={r['counts']}" for r in reactors))
    print(f"cache: {before} -> {after} MB, peak {data['peak_container_mem_gib']} GiB")

    if expected_mode == "modules":
        if data["result"] != "FAILURE":
            raise RuntimeError(f"{label}: expected FAILURE, got {data['result']}")
        if data["selection"]["mode"] != "modules":
            raise RuntimeError(f"{label}: expected modules mode")
        if "ts-order-service" not in (data["selection"]["pl"] or ""):
            raise RuntimeError(f"{label}: ts-order-service not selected")
        if data["maven_exit_codes"].get("VERIFY") != 1:
            raise RuntimeError(f"{label}: VERIFY exit "
                               f"{data['maven_exit_codes'].get('VERIFY')}")
        if data["selection"]["head"] != source_commit:
            raise RuntimeError(f"{label}: selector HEAD mismatch")
        if data["selection"]["reference"] != PIN:
            raise RuntimeError(f"{label}: selector reference mismatch")
        if not data["tests"]["reported"]:
            raise RuntimeError(f"{label}: no tests reported")
    else:
        if data["result"] != "SUCCESS":
            raise RuntimeError(f"{label}: expected docs skip SUCCESS, got "
                               f"{data['result']}")
        if data["selection"]["mode"] != "none":
            raise RuntimeError(f"{label}: expected none mode")
        if data["maven_exit_codes"].get("VERIFY") != "SKIP":
            raise RuntimeError(f"{label}: expected SKIP Maven marker")
        if "PRK_SKIP_MAVEN" not in console:
            raise RuntimeError(f"{label}: PRK_SKIP_MAVEN missing")
    return data


def validate_incremental(data, expected_mode):
    if expected_mode == "modules":
        if data["result"] != "FAILURE":
            raise RuntimeError(f"{data['label']}: expected FAILURE, got {data['result']}")
        if data["selection"]["mode"] != "modules":
            raise RuntimeError(f"{data['label']}: expected modules mode")
        if "ts-order-service" not in (data["selection"]["pl"] or ""):
            raise RuntimeError(f"{data['label']}: ts-order-service not selected")
        if data["maven_exit_codes"].get("VERIFY") != 1:
            raise RuntimeError(f"{data['label']}: VERIFY exit "
                               f"{data['maven_exit_codes'].get('VERIFY')}")
        if data["selection"]["head"] != data["source_commit"]:
            raise RuntimeError(f"{data['label']}: selector HEAD mismatch")
        if data["selection"]["reference"] != PIN:
            raise RuntimeError(f"{data['label']}: selector reference mismatch")
        if not data["tests"]["reported"]:
            raise RuntimeError(f"{data['label']}: no tests reported")
    else:
        if data["result"] != "SUCCESS":
            raise RuntimeError(f"{data['label']}: expected docs skip SUCCESS, got "
                               f"{data['result']}")
        if data["selection"]["mode"] != "none":
            raise RuntimeError(f"{data['label']}: expected none mode")
        if data["maven_exit_codes"].get("VERIFY") != "SKIP":
            raise RuntimeError(f"{data['label']}: expected SKIP Maven marker")
        if "PRK_SKIP_MAVEN" not in data.get("_console", ""):
            raise RuntimeError(f"{data['label']}: PRK_SKIP_MAVEN missing")


def reparse_run(label, expected_mode):
    raw_dir = os.path.join(RAW, label)
    path = evidence_paths.evidence_read(os.path.join(EVID, label + ".json"))
    data = json.load(open(path, encoding="utf-8"))
    console = open(os.path.join(raw_dir, "console.log"),
                   encoding="utf-8", errors="replace").read()
    build = json.load(open(os.path.join(raw_dir, "build.json"), encoding="utf-8"))
    wfapi = json.load(open(os.path.join(raw_dir, "wfapi.json"), encoding="utf-8"))
    report_path = os.path.join(raw_dir, "test-report.json")
    report = json.load(open(report_path, encoding="utf-8")) \
        if os.path.exists(report_path) else None

    exits = parse_m4_exits(console)
    stages = m2.parse_stages(wfapi)
    reactors = m3.parse_reactors(console)
    report_tests = m2.parse_test_report(report)
    console_tests = m2.parse_console_tests(console)
    tests = console_tests if console_tests["reported"] else report_tests
    tests["jenkins_reported"] = report_tests["reported"]
    if report_tests["failed_cases"]:
        tests["failed_cases"] = report_tests["failed_cases"]
    m2.annotate_failed_cases(tests, console_tests)
    stage_sum = sum(s["duration_ms"] for s in stages
                    if s.get("duration_ms") is not None)
    data.update({
        "result": build.get("result"),
        "jenkins_duration_ms": build.get("duration"),
        "stages": stages,
        "stage_sum_ms": stage_sum,
        "post_estimate_ms": (build.get("duration") or 0) - stage_sum,
        "maven_exit_codes": exits,
        "selection": {
            "mode": grep_value(console, "PRK_MODE"),
            "pl": grep_value(console, "PRK_PL"),
            "reason": grep_value(console, "PRK_REASON"),
            "changed": grep_value(console, "PRK_CHANGED"),
            "reference": grep_value(console, "PRK_REFERENCE"),
            "head": grep_value(console, "PRK_HEAD"),
            "command": grep_value(console, "PRK_MAVEN_COMMAND"),
        },
        "reactors": reactors,
        "tests": tests,
        "_console": console,
    })
    write_json(path, data)
    validate_incremental(data, expected_mode)
    data.pop("_console", None)
    write_json(path, data)
    print(f"reparsed {label}: build #{data['build_number']} "
          f"{data['result']} {data['jenkins_duration_ms']} ms")
    return data


def medians(runs):
    def med(key):
        return round(statistics.median([r[key] for r in runs]), 1)
    stages = {}
    for name in ("Checkout pinned source", "Select modules", "Verify"):
        vals = [next((s["duration_ms"] for s in r["stages"]
                      if s["name"] == name and s["duration_ms"] is not None), None)
                for r in runs]
        vals = [v for v in vals if v is not None]
        if vals:
            stages[name] = round(statistics.median(vals), 1)
    return {
        "runs": len(runs),
        "jenkins_duration_ms": med("jenkins_duration_ms"),
        "host_wall_clock_s": med("host_wall_clock_s"),
        "stages_ms": stages,
        "cache_before_mb": med("cache_before_mb"),
        "cache_after_mb": med("cache_after_mb"),
        "peak_container_mem_gib": round(max(
            r["peak_container_mem_gib"] or 0 for r in runs), 3),
    }


def main():
    os.makedirs(evidence_paths.generated_dir(EVID), exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    preflight()
    service_sha = branch_sha(SERVICE_BRANCH)
    docs_sha = branch_sha(DOCS_BRANCH)
    resume = "--resume" in sys.argv[1:]

    runs = []
    try:
        for index in (1, 2, 3):
            label = f"incremental-{index}"
            if resume and os.path.exists(evidence_paths.evidence_read(
                    os.path.join(EVID, label + ".json"))):
                runs.append(reparse_run(label, "modules"))
            else:
                runs.append(run_one(label, service_sha, "modules"))
        docs_label = "jenkins-docs-skip"
        if resume and os.path.exists(evidence_paths.evidence_read(
                os.path.join(EVID, docs_label + ".json"))):
            docs = reparse_run(docs_label, "none")
        else:
            docs = run_one(docs_label, docs_sha, "none")
    except Exception as exc:  # noqa: BLE001
        write_json(os.path.join(EVID, "results.json"), {
            "milestone": "M4",
            "status": "BLOCKED",
            "error": str(exc),
            "incremental_runs": runs,
        })
        print(f"STOPPED: {exc}", file=sys.stderr)
        return 1

    scenarios = json.load(open(evidence_paths.evidence_read(
        os.path.join(EVID, "scenarios.json")), encoding="utf-8"))
    m3_results = json.load(open(evidence_paths.evidence_read(
        os.path.join(ROOT, "evidence", "M3", "results.json")), encoding="utf-8"))
    m3_median = m3_results["medians"]["rescued"]["jenkins_duration_ms"]
    inc_median = statistics.median([r["jenkins_duration_ms"] for r in runs])
    diff = m3_median - inc_median
    results = {
        "milestone": "M4",
        "status": "PASS",
        "source": {
            "reference": PIN,
            "source_repo": "evidence/M4/work/train-ticket",
            "jenkins_source_mount": SOURCE_REPO,
            "service_branch": SERVICE_BRANCH,
            "service_sha": service_sha,
            "docs_branch": DOCS_BRANCH,
            "docs_sha": docs_sha,
        },
        "selector": {
            "script": "tools/select-modules.sh",
            "method": "git diff plus Maven -pl/-am/-amd",
            "safe_fallback": "full scope on root build files, unknown POMs or selector failure",
        },
        "scenarios": scenarios,
        "incremental_runs": runs,
        "incremental_medians": medians(runs),
        "jenkins_docs_skip": docs,
        "m3_full_scope_reference": {
            "rescued_median_ms": m3_median,
            "tests": 626,
            "source": "evidence/M3/results.json",
        },
        "scope_comparison": {
            "incremental_median_ms": round(inc_median, 1),
            "full_scope_median_ms": m3_median,
            "difference_ms": round(diff, 1),
            "difference_pct_of_full_scope": round(diff / m3_median * 100, 1),
            "same_workload": False,
            "note": "M4 incremental runs execute only ts-order-service and its "
                    "required upstream modules. M3 executed 626 tests across 43 "
                    "modules. This is a scope saving, not a same-workload speed "
                    "comparison.",
        },
        "test_inventory": {
            "incremental": {
                "tests": runs[0]["tests"]["reported"],
                "passed": runs[0]["tests"]["passed"],
                "failures": runs[0]["tests"]["failures"],
                "errors": runs[0]["tests"]["errors"],
                "skipped": runs[0]["tests"]["skipped"],
            },
            "full_scope": {"tests": 626, "failed_or_errored": 220},
            "equivalent": False,
            "note": "A smaller incremental test inventory is not equivalent to "
                    "the full reactor and is not counted as such.",
        },
        "limitations": [
            "The selector is path-based and delegates dependency expansion to "
            "Maven -am and -amd; it is not a general dependency-analysis engine.",
            "The ts-common scenario selects 42 dependent module entries; the "
            "aggregator root is not in that reactor.",
            "Incremental timing covers only the changed service and required "
            "upstream modules, so it is scope savings, not a same-workload "
            "comparison with M3.",
            "Warm cache only.",
            "The M4 source branches are disposable test branches in a clone, "
            "not changes to the pinned upstream checkout.",
            "No application test was excluded, repaired or suppressed.",
            "M5, quality gates and the shared library are not started.",
        ],
    }
    write_json(os.path.join(EVID, "results.json"), results)
    write_json(os.path.join(EVID, "test-inventory.json"),
               results["test_inventory"])
    print("\n=== M4 result ===")
    print(json.dumps({
        "incremental_median_ms": results["scope_comparison"]["incremental_median_ms"],
        "full_scope_median_ms": m3_median,
        "difference_pct": results["scope_comparison"]["difference_pct_of_full_scope"],
        "tests": results["test_inventory"]["incremental"],
        "docs_skip": docs["result"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
