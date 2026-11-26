#!/usr/bin/env python3
"""M3 measurement harness for the full-reactor Train-Ticket comparison.

Modes:
  threads   run the rescued one-pass pipeline with 1, 2 and 4 reactor threads
  compare   run three full-scope baseline and three rescued measurements

The M2 baseline evidence is never overwritten. The full-scope baseline is the
M2 job with FULL_SCOPE=true: PMD skipped, 'mvn test -fae', 626 tests.
"""
import argparse
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
import evidence_paths  # noqa: E402

EVID = os.path.join(ROOT, "evidence", "M3")
RAW = os.path.join(EVID, "raw")
CONTROL_EVID = os.path.join(ROOT, "evidence", "m3-control")
CONTROL_RAW = os.path.join(CONTROL_EVID, "raw")
PIN = "313886e99befb94be6cd45f085c98e0019f59829"
BASELINE_JOB = "train-ticket-baseline"
RESCUE_JOB = "train-ticket"
BUILD_TIMEOUT_S = 2700
ALLOWED_CONTAINERS = {"prk-m1-controller", "prk-m1-agent"}
FULL_TESTS = 626
# M0C recorded 221 failed/errored. The full M3 reactor consistently produces
# 220 because auth.controller.AuthControllerTest.testCreateDefaultUser passes
# here. It appears order-sensitive or flaky; the cause is not proven. This is
# recorded as found, not fixed.
FULL_FAILED_OR_ERRORED = 220
FULL_FAILED_OR_ERRORED_M0C = 221
FULL_MODULES = 43


def write_text(path, text):
    path = evidence_paths.generated_path(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_json(path, value):
    write_text(path, json.dumps(value, indent=2) + "\n")


def cache_mb():
    return m2.cache_mb()


def preflight(evid=EVID):
    rc, ps = m2.docker("ps", "--format", "{{.Names}}")
    if rc != 0:
        raise RuntimeError(f"docker ps failed: {ps.strip()}")
    names = {line.strip() for line in ps.splitlines() if line.strip()}
    unexpected = sorted(names - ALLOWED_CONTAINERS)
    if unexpected:
        raise RuntimeError(f"unexpected running containers: {unexpected}")
    if not ALLOWED_CONTAINERS.issubset(names):
        raise RuntimeError(f"missing project containers: {sorted(ALLOWED_CONTAINERS - names)}")

    source = os.path.join(ROOT, "evidence", "M2", "work", "train-ticket")
    rc, sha = m2.run(["git", "-C", source, "rev-parse", "HEAD"])
    if rc != 0 or sha.strip() != PIN:
        raise RuntimeError(f"pinned source SHA mismatch: {sha.strip()!r}")

    api.wait_controller(120)
    api.wait_agent_online("linux-agent", 120)
    if cache_mb() <= 0:
        raise RuntimeError("Maven cache is not warm; M3 requires the warm M2 cache")

    rc, info = m2.docker("info", "--format",
                         "CPUs={{.NCPU}} MemTotal={{.MemTotal}} Arch={{.Architecture}}")
    rc, stats = m2.docker("stats", "--no-stream", "--format",
                          "{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}")
    rc, disk = m2.run(["df", "-h", ROOT])
    rc, java = m2.docker("exec", "prk-m1-agent", "/opt/java/jdk8/bin/java", "-version")
    rc, maven = m2.docker("exec", "prk-m1-agent", "sh", "-c",
                          "JAVA_HOME=/opt/java/jdk8 /opt/maven/bin/mvn -v")
    lines = [
        "M3 preflight",
        "date UTC: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source: " + source,
        "source HEAD: " + sha.strip(),
        "docker info: " + info.strip(),
        "docker ps: " + ",".join(sorted(names)),
        "docker stats:",
        stats.strip(),
        "disk:",
        disk.strip().splitlines()[-1] if disk.strip() else "(no output)",
        "agent JDK 8:",
        java.strip(),
        "agent Maven on JDK 8:",
        maven.strip(),
        "cache MB: " + str(cache_mb()),
    ]
    write_text(os.path.join(evid, "environment.txt"), "\n".join(lines) + "\n")
    print("\n".join(lines[:8]))


def trigger_build(job, params):
    data = api.get_json(f"/job/{job}/api/json?tree=lastBuild[number,building]")
    last = data.get("lastBuild") or {}
    waited = 0
    while last.get("building") and waited < 120:
        time.sleep(5)
        waited += 5
        data = api.get_json(f"/job/{job}/api/json?tree=lastBuild[number,building]")
        last = data.get("lastBuild") or {}
    if last.get("building"):
        raise RuntimeError(f"{job} is already running")

    before = last.get("number", 0)
    api.post_form(f"/job/{job}/buildWithParameters", params)

    deadline = time.monotonic() + BUILD_TIMEOUT_S
    number = None
    while time.monotonic() < deadline:
        data = api.get_json(
            f"/job/{job}/api/json?tree=lastBuild[number,building]")
        last = data.get("lastBuild") or {}
        if last.get("number", 0) > before:
            number = last["number"]
        if number and not last.get("building"):
            return number
        time.sleep(3)

    if number:
        try:
            api.post(f"/job/{job}/{number}/stop")
        except Exception:
            pass
    raise RuntimeError(f"{job} build timed out after {BUILD_TIMEOUT_S}s")


def fetch_build(job, number):
    build = api.get_json(
        f"/job/{job}/{number}/api/json"
        "?tree=number,result,duration,timestamp,builtOn,displayName")
    status, console, _ = api.request(f"/job/{job}/{number}/consoleText", timeout=60)
    if status != 200:
        raise RuntimeError(f"console log returned {status}")
    return build, console.decode("utf-8", errors="replace")


def fetch_wfapi(job, number):
    status, body, _ = api.request(f"/job/{job}/{number}/wfapi/describe", timeout=30)
    if status != 200:
        return None
    return json.loads(body.decode("utf-8"))


def fetch_test_report(job, number):
    status, body, _ = api.request(
        f"/job/{job}/{number}/testReport/api/json", timeout=60)
    if status != 200:
        return None
    return json.loads(body.decode("utf-8"))


def parse_exits(console):
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"(?:M[23]|PRK)_MAVEN_EXIT_([A-Z_]+)=(-?\d+)", console)}


def parse_maven_command(console):
    match = re.search(r"PRK_MAVEN_COMMAND=(.+)$", console, re.MULTILINE)
    return match.group(1).strip() if match else None


def parse_reactors(console):
    markers = []
    for name in ("Build", "Test", "Verify"):
        pos = console.find(f"({name})")
        if pos >= 0:
            markers.append((pos, name))
    markers.sort()
    segments = []
    if not markers:
        segments.append(("unknown", console))
    else:
        for index, (pos, name) in enumerate(markers):
            end = markers[index + 1][0] if index + 1 < len(markers) else len(console)
            segments.append((name, console[pos:end]))

    reactors = []
    for stage, segment in segments:
        blocks = m2.parse_reactor_blocks(segment)
        for index, modules in enumerate(blocks):
            label = stage.lower()
            if stage == "Test" and len(blocks) > 1:
                label = "pmd" if index < len(blocks) - 1 else "test"
            counts = {}
            for module in modules:
                counts[module["result"]] = counts.get(module["result"], 0) + 1
            reactors.append({
                "phase": label,
                "counts": counts,
                "modules": modules,
            })
    return reactors


def peak_mem_gib(stats_text):
    return m2.peak_mem_gib(stats_text)


def run_one(label, job, params, evid=EVID, raw=RAW):
    raw_dir = os.path.join(raw, label)
    os.makedirs(raw_dir, exist_ok=True)
    before = cache_mb()
    if before <= 0:
        raise RuntimeError(f"{label}: Maven cache is not warm")

    print(f"\n=== {label} ({job} {params}) ===")
    print(f"cache before: {before} MB")
    stop, thread = m2.start_stats(raw_dir)
    started = time.monotonic()
    started_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    try:
        number = trigger_build(job, params)
        build, console = fetch_build(job, number)
        wfapi = fetch_wfapi(job, number)
        report = fetch_test_report(job, number)
    finally:
        stop.set()
        thread.join(timeout=10)
    ended = time.monotonic()
    ended_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    host_wall = round(ended - started, 1)

    write_text(os.path.join(raw_dir, "console.log"), console)
    write_json(os.path.join(raw_dir, "build.json"), build)
    write_json(os.path.join(raw_dir, "wfapi.json"), wfapi)
    write_json(os.path.join(raw_dir, "test-report.json"), report)

    after = cache_mb()
    exits = parse_exits(console)
    stages = m2.parse_stages(wfapi)
    reactors = parse_reactors(console)
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
        "job": job,
        "params": params,
        "maven_command": parse_maven_command(console),
        "build_number": number,
        "result": build.get("result"),
        "started_at": started_at,
        "finished_at": ended_at,
        "host_wall_clock_s": host_wall,
        "jenkins_duration_ms": build.get("duration"),
        "stages": stages,
        "stage_sum_ms": stage_sum,
        "post_estimate_ms": (build.get("duration") or 0) - stage_sum,
        "maven_exit_codes": exits,
        "cache_before_mb": before,
        "cache_after_mb": after,
        "reactors": reactors,
        "tests": tests,
        "peak_container_mem_gib": peak_mem_gib(stats_text),
        "raw_dir": os.path.relpath(raw_dir, ROOT),
    }
    write_json(os.path.join(evid, label + ".json"), data)

    print(f"build #{number}: {data['result']} duration={data['jenkins_duration_ms']} ms "
          f"host={host_wall}s")
    print("stages: " + ", ".join(
        f"{s['name']}={s['duration_ms']}ms/{s['status']}" for s in stages))
    print(f"maven exits: {exits}")
    print(f"tests: {tests['reported']} reported, {tests['passed']} passed, "
          f"{tests['failures']} failures, {tests['errors']} errors, "
          f"{tests['skipped']} skipped")
    print("reactors: " + ", ".join(
        f"{r['phase']}={r['counts']}" for r in reactors))
    print(f"cache: {before} -> {after} MB, peak mem {data['peak_container_mem_gib']} GiB")
    return data


def validate_full_scope(data):
    if data["result"] != "FAILURE":
        raise RuntimeError(f"{data['label']}: expected FAILURE, got {data['result']}")
    tests = data["tests"]
    if tests["reported"] != FULL_TESTS:
        raise RuntimeError(f"{data['label']}: expected {FULL_TESTS} tests, "
                           f"got {tests['reported']}")
    if tests["failures"] + tests["errors"] != FULL_FAILED_OR_ERRORED:
        raise RuntimeError(f"{data['label']}: expected "
                           f"{FULL_FAILED_OR_ERRORED} failed/errored, got "
                           f"{tests['failures'] + tests['errors']}")
    max_modules = max((len(r["modules"]) for r in data["reactors"]), default=0)
    if max_modules != FULL_MODULES:
        raise RuntimeError(f"{data['label']}: expected {FULL_MODULES} reactor "
                           f"entries, got {max_modules}")
    if data["job"] == RESCUE_JOB:
        if data["maven_exit_codes"].get("VERIFY") != 1:
            raise RuntimeError(f"{data['label']}: VERIFY exit "
                               f"{data['maven_exit_codes'].get('VERIFY')}")
    elif data["job"] == BASELINE_JOB:
        if data["maven_exit_codes"].get("BUILD") != 0:
            raise RuntimeError(f"{data['label']}: BUILD exit "
                               f"{data['maven_exit_codes'].get('BUILD')}")
        if data["maven_exit_codes"].get("TEST") != 1:
            raise RuntimeError(f"{data['label']}: TEST exit "
                               f"{data['maven_exit_codes'].get('TEST')}")
        if data["maven_exit_codes"].get("PMD") not in (None, 0):
            raise RuntimeError(f"{data['label']}: unexpected PMD exit")
    else:
        raise RuntimeError(f"{data['label']}: unknown job {data['job']}")


def validate_control(data):
    tests = data["tests"]
    if tests["reported"] != FULL_TESTS:
        raise RuntimeError(f"{data['label']}: expected {FULL_TESTS} tests, "
                           f"got {tests['reported']}")
    if tests["failures"] + tests["errors"] != FULL_FAILED_OR_ERRORED:
        raise RuntimeError(f"{data['label']}: expected "
                           f"{FULL_FAILED_OR_ERRORED} failed/errored, got "
                           f"{tests['failures'] + tests['errors']}")
    max_modules = max((len(r["modules"]) for r in data["reactors"]), default=0)
    if max_modules != FULL_MODULES:
        raise RuntimeError(f"{data['label']}: expected {FULL_MODULES} reactor "
                           f"entries, got {max_modules}")
    if data["params"].get("IGNORE_TEST_FAILURES") != "true":
        raise RuntimeError(f"{data['label']}: failure-ignore parameter missing")


def verify_counts(data):
    for reactor in reversed(data.get("reactors", [])):
        if reactor["phase"] == "verify":
            return reactor["counts"]
    return {}


def stats(values):
    values = [v for v in values if v is not None]
    return {
        "runs": len(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def timing_block(runs, stage):
    values = [stage_ms(r, stage) for r in runs]
    values = [v for v in values if v is not None]
    return {
        "jenkins_duration_ms": stats([r["jenkins_duration_ms"] for r in runs]),
        "host_wall_clock_s": stats([r["host_wall_clock_s"] for r in runs]),
        "stage_ms": stats(values),
        "stage_name": stage,
    }


def test_snapshot(data):
    tests = data["tests"]
    return {k: tests.get(k) for k in
            ("reported", "passed", "failures", "errors", "skipped")}


def control_mode():
    os.makedirs(CONTROL_EVID, exist_ok=True)
    os.makedirs(CONTROL_RAW, exist_ok=True)
    status, body, _ = api.request(f"/job/{RESCUE_JOB}/config.xml", timeout=30)
    if status != 200 or b"IGNORE_TEST_FAILURES" not in body:
        raise RuntimeError(
            f"{RESCUE_JOB} is missing IGNORE_TEST_FAILURES; reload JCasC")
    preflight(CONTROL_EVID)
    params = {
        "REACTOR_THREADS": "2",
        "INCREMENTAL": "false",
        "SOURCE_REPO": "/src/train-ticket",
        "SOURCE_COMMIT": PIN,
        "REFERENCE_COMMIT": PIN,
        "IGNORE_TEST_FAILURES": "true",
    }
    runs = []
    for index in (1, 2, 3):
        label = f"control-{index}"
        data = run_one(label, RESCUE_JOB, params,
                       evid=CONTROL_EVID, raw=CONTROL_RAW)
        validate_control(data)
        runs.append(data)

    baseline = [json.load(open(os.path.join(EVID, f"baseline-{i}.json"),
                               encoding="utf-8")) for i in (1, 2, 3)]
    rescued = [json.load(open(os.path.join(EVID, f"rescue-{i}.json"),
                              encoding="utf-8")) for i in (1, 2, 3)]

    baseline_install = next((r["counts"] for r in baseline[0]["reactors"]
                            if r["phase"] == "build"), {})
    baseline_test = next((r["counts"] for r in baseline[0]["reactors"]
                          if r["phase"] == "test"), {})
    rescue_verify = verify_counts(rescued[0])
    control_counts = [verify_counts(r) for r in runs]
    control_success = [c.get("SUCCESS", 0) for c in control_counts]
    control_failure = [c.get("FAILURE", 0) for c in control_counts]
    control_skipped = [c.get("SKIPPED", 0) for c in control_counts]
    if all(s == FULL_MODULES and f == 0
           for s, f in zip(control_success, control_failure)):
        packaging_assessment = (
            "All three control runs report all 43 reactor entries as SUCCESS "
            "in the verify reactor, so modules whose tests fail still reach "
            "packaging. This is a verify lifecycle, not install. The baseline "
            "also ran clean install; the packaging phase is reached, but the "
            "full workload is not completely equal.")
    elif all(s + f <= FULL_MODULES
             for s, f in zip(control_success, control_failure)):
        packaging_assessment = (
            f"Control packaging is partial: SUCCESS counts {control_success}, "
            f"FAILURE counts {control_failure}, SKIPPED counts "
            f"{control_skipped}. Not all modules whose tests fail reach "
            "packaging.")
    else:
        packaging_assessment = (
            "Control packaging could not be classified from the reactor "
            f"counts: SUCCESS {control_success}, FAILURE {control_failure}, "
            f"SKIPPED {control_skipped}.")

    results = {
        "milestone": "M3 control",
        "status": "PASS",
        "source": {
            "repository": "https://github.com/FudanSELab/train-ticket.git",
            "checkout": "evidence/M2/work/train-ticket",
            "commit": PIN,
        },
        "condition": {
            "job": RESCUE_JOB,
            "params": params,
            "maven_command_expected": (
                "JAVA_HOME=/opt/java/jdk8 /opt/maven/bin/mvn -B -T 2 -fae "
                "-Dmaven.repo.local=/m2/repository "
                "-Dmaven.test.failure.ignore=true verify"),
            "threads": 2,
            "failure_ignore": True,
            "cache": "warm /m2/repository",
            "jdk": "Temurin 1.8.0_512",
            "maven": "Apache Maven 3.9.16",
            "agent": "linux-agent",
        },
        "control_runs": runs,
        "historical_baseline": [
            {"label": r["label"],
             "build_number": r["build_number"],
             "result": r["result"],
             "jenkins_duration_ms": r["jenkins_duration_ms"],
             "host_wall_clock_s": r["host_wall_clock_s"],
             "tests": test_snapshot(r),
             "maven_exit_codes": r.get("maven_exit_codes"),
             "reactors": [{"phase": x["phase"], "counts": x["counts"]}
                          for x in r["reactors"]]}
            for r in baseline
        ],
        "historical_rescued": [
            {"label": r["label"],
             "build_number": r["build_number"],
             "result": r["result"],
             "jenkins_duration_ms": r["jenkins_duration_ms"],
             "host_wall_clock_s": r["host_wall_clock_s"],
             "tests": test_snapshot(r),
             "maven_exit_codes": r.get("maven_exit_codes"),
             "reactors": [{"phase": x["phase"], "counts": x["counts"]}
                          for x in r["reactors"]]}
            for r in rescued
        ],
        "timing": {
            "baseline_full": timing_block(baseline, "Test"),
            "rescued": timing_block(rescued, "Verify"),
            "control": timing_block(runs, "Verify"),
            "baseline_build_plus_test_ms": stats([
                (stage_ms(r, "Build") or 0) + (stage_ms(r, "Test") or 0)
                for r in baseline]),
        },
        "test_inventory": {
            "baseline_full": [test_snapshot(r) for r in baseline],
            "rescued": [test_snapshot(r) for r in rescued],
            "control": [test_snapshot(r) for r in runs],
        },
        "packaging": {
            "baseline_install_counts": baseline_install,
            "baseline_test_counts": baseline_test,
            "rescued_verify_counts": rescue_verify,
            "control_verify_counts": control_counts,
            "control_success_counts": control_success,
            "control_failure_counts": control_failure,
            "control_skipped_counts": control_skipped,
            "assessment": packaging_assessment,
        },
        "maven_and_jenkins": {
            "maven_exit_codes": [r.get("maven_exit_codes") for r in runs],
            "jenkins_results": [r.get("result") for r in runs],
            "maven_commands": [r.get("maven_command") for r in runs],
            "maven_success_despite_test_failures": [
                r.get("maven_exit_codes", {}).get("VERIFY") == 0
                for r in runs],
        },
        "limitations": [
            "Control uses verify, not install. The baseline clean install pass "
            "also installs artifacts.",
            "Control is single-sided; the historical baseline and rescued runs "
            "are comparison data, not rerun.",
            "Warm Maven cache only.",
            "The three -T 1 attribution runs are not included.",
        ],
    }
    write_json(os.path.join(CONTROL_EVID, "results.json"), results)
    post_run(CONTROL_EVID)
    print("\n=== M3 control ===")
    print(json.dumps(results["timing"], indent=2))
    print("results: " + os.path.relpath(
        os.path.join(CONTROL_EVID, "results.json"), ROOT))
    return 0


def stage_ms(data, name):
    return next((s["duration_ms"] for s in data["stages"]
                 if s["name"] == name and s["duration_ms"] is not None), None)


def medians(data, stage_names):
    stages = {}
    for name in stage_names:
        values = [stage_ms(d, name) for d in data]
        values = [v for v in values if v is not None]
        if values:
            stages[name] = round(statistics.median(values), 1)
    return {
        "runs": len(data),
        "jenkins_duration_ms": round(statistics.median(
            [d["jenkins_duration_ms"] for d in data]), 1),
        "host_wall_clock_s": round(statistics.median(
            [d["host_wall_clock_s"] for d in data]), 1),
        "stages_ms": stages,
        "cache_before_mb": round(statistics.median(
            [d["cache_before_mb"] for d in data]), 1),
        "cache_after_mb": round(statistics.median(
            [d["cache_after_mb"] for d in data]), 1),
        "peak_container_mem_gib": round(max(
            d["peak_container_mem_gib"] or 0 for d in data), 3),
    }


def thread_mode():
    runs = []
    errors = []
    for threads in (1, 2, 4):
        label = f"thread-{threads}"
        try:
            data = run_one(label, RESCUE_JOB,
                           {"REACTOR_THREADS": str(threads)})
            validate_full_scope(data)
            runs.append(data)
        except Exception as exc:  # noqa: BLE001
            errors.append({"label": label, "error": str(exc)})
            print(f"{label} failed: {exc}", file=sys.stderr)
    obj = {
        "milestone": "M3",
        "mode": "thread investigation",
        "cache": "warm",
        "runs": runs,
        "errors": errors,
        "chosen_threads": 2,
        "selection_note": "2 is the conservative default for the 3 GiB agent; "
                          "single runs at 1, 2 and 4 are investigation only.",
    }
    write_json(os.path.join(EVID, "threads.json"), obj)
    print("\nthread investigation written to " + os.path.relpath(
        evidence_paths.generated_path(os.path.join(EVID, "threads.json")), ROOT))
    return 0 if len(runs) == 3 else 1


def reparse_threads():
    runs = []
    errors = []
    for threads in (1, 2, 4):
        label = f"thread-{threads}"
        try:
            data = reparse_label(label)
            validate_full_scope(data)
            runs.append(data)
        except Exception as exc:  # noqa: BLE001
            errors.append({"label": label, "error": str(exc)})
            print(f"{label} reparse failed: {exc}", file=sys.stderr)
    obj = {
        "milestone": "M3",
        "mode": "thread investigation",
        "cache": "warm",
        "runs": runs,
        "errors": errors,
        "chosen_threads": 2,
        "selection_note": "2 is the conservative default for the 3 GiB agent; "
                          "single runs at 1, 2 and 4 are investigation only. "
                          "All three runs executed 626 tests and 220 "
                          "failed/errored; M0C recorded 221, with one "
                          "auth test passing here; the cause is not proven.",
    }
    write_json(os.path.join(EVID, "threads.json"), obj)
    print("reparsed 1/2/4 thread runs into " + os.path.relpath(
        evidence_paths.generated_path(os.path.join(EVID, "threads.json")), ROOT))
    return 0 if len(runs) == 3 else 1


def reparse_label(label):
    raw_dir = os.path.join(RAW, label)
    path = evidence_paths.evidence_read(
        os.path.join(EVID, label + ".json"))
    if not os.path.exists(path):
        raise RuntimeError(f"missing {path}")
    console = open(os.path.join(raw_dir, "console.log"),
                   encoding="utf-8", errors="replace").read()
    build = json.load(open(os.path.join(raw_dir, "build.json"), encoding="utf-8"))
    wfapi = json.load(open(os.path.join(raw_dir, "wfapi.json"), encoding="utf-8"))
    report_path = os.path.join(raw_dir, "test-report.json")
    report = json.load(open(report_path, encoding="utf-8")) \
        if os.path.exists(report_path) else None

    data = json.load(open(path, encoding="utf-8"))
    exits = parse_exits(console)
    stages = m2.parse_stages(wfapi)
    reactors = parse_reactors(console)
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
        "reactors": reactors,
        "tests": tests,
    })
    write_json(path, data)
    return data


def compare_mode(threads, resume=False):
    plan = [
        ("baseline-1", BASELINE_JOB, {"FULL_SCOPE": "true"}),
        ("rescue-1", RESCUE_JOB, {"REACTOR_THREADS": str(threads)}),
        ("baseline-2", BASELINE_JOB, {"FULL_SCOPE": "true"}),
        ("rescue-2", RESCUE_JOB, {"REACTOR_THREADS": str(threads)}),
        ("baseline-3", BASELINE_JOB, {"FULL_SCOPE": "true"}),
        ("rescue-3", RESCUE_JOB, {"REACTOR_THREADS": str(threads)}),
    ]
    runs = []
    try:
        for label, job, params in plan:
            path = evidence_paths.evidence_read(
                os.path.join(EVID, label + ".json"))
            if resume and os.path.exists(path):
                data = reparse_label(label)
                validate_full_scope(data)
                runs.append(data)
                print(f"resumed {label}: build #{data['build_number']} "
                      f"{data['result']} {data['jenkins_duration_ms']} ms")
                continue
            data = run_one(label, job, params)
            validate_full_scope(data)
            runs.append(data)
    except Exception as exc:  # noqa: BLE001
        write_json(os.path.join(EVID, "results.json"), {
            "milestone": "M3",
            "status": "BLOCKED",
            "error": str(exc),
            "runs": runs,
            "methodology": methodology(threads),
        })
        raise

    baseline = [r for r in runs if r["job"] == BASELINE_JOB]
    rescue = [r for r in runs if r["job"] == RESCUE_JOB]
    baseline_med = medians(baseline, ("Checkout pinned source", "Build", "Test"))
    rescue_med = medians(rescue, ("Checkout pinned source", "Verify"))
    b_stage = ((baseline_med["stages_ms"].get("Build") or 0)
               + (baseline_med["stages_ms"].get("Test") or 0))
    r_stage = rescue_med["stages_ms"].get("Verify") or 0
    comparison = {
        "baseline_build_plus_test_ms": round(b_stage, 1),
        "rescued_verify_ms": round(r_stage, 1),
        "stage_difference_ms": round(b_stage - r_stage, 1),
        "stage_difference_pct_of_baseline": round(
            (b_stage - r_stage) / b_stage * 100, 1) if b_stage else None,
        "total_difference_ms": round(
            baseline_med["jenkins_duration_ms"]
            - rescue_med["jenkins_duration_ms"], 1),
        "total_difference_pct_of_baseline": round(
            (baseline_med["jenkins_duration_ms"]
             - rescue_med["jenkins_duration_ms"])
            / baseline_med["jenkins_duration_ms"] * 100, 1),
        "tests_equivalent": (
            all(r["tests"]["reported"] == FULL_TESTS for r in runs)
            and all(r["tests"]["failures"] + r["tests"]["errors"]
                    == FULL_FAILED_OR_ERRORED for r in runs)
        ),
        "modules_equivalent": all(
            max((len(x["modules"]) for x in r["reactors"]), default=0)
            == FULL_MODULES for r in runs),
    }

    thread_obj = None
    thread_path = evidence_paths.evidence_read(
        os.path.join(EVID, "threads.json"))
    if os.path.exists(thread_path):
        thread_obj = json.load(open(thread_path, encoding="utf-8"))

    results = {
        "milestone": "M3",
        "status": "PASS",
        "source": {
            "repository": "https://github.com/FudanSELab/train-ticket.git",
            "checkout": "evidence/M2/work/train-ticket",
            "commit": PIN,
        },
        "methodology": methodology(threads),
        "thread_investigation": thread_obj,
        "baseline_full": baseline,
        "rescued": rescue,
        "medians": {
            "baseline_full": baseline_med,
            "rescued": rescue_med,
            "comparison": comparison,
        },
        "test_inventory": {
            "workload": {
                "tests": FULL_TESTS,
                "failed_or_errored": FULL_FAILED_OR_ERRORED,
                "m0c_failed_or_errored": FULL_FAILED_OR_ERRORED_M0C,
                "delta_note": "auth.controller.AuthControllerTest."
                              "testCreateDefaultUser appears order-sensitive and "
                              "passes in the M3 runs; M0C recorded it as an "
                              "InvalidUseOfMatchersException error. The cause "
                              "is not proven.",
                "modules": FULL_MODULES,
            },
            "baseline_full": [
                {"label": r["label"], "tests": r["tests"]} for r in baseline
            ],
            "rescued": [
                {"label": r["label"], "tests": r["tests"]} for r in rescue
            ],
            "m2_baseline_note": "M2 baseline reached only 25 tests and is not "
                                "used for the M3 speed comparison.",
        },
        "limitations": [
            "M2 baseline remains the 25-test early-failing run and is not used "
            "for the speed comparison.",
            "Full-scope baseline is a controlled supplemental mode: M2 job, "
            "FULL_SCOPE=true, PMD skipped, mvn test -fae.",
            "The M3 full reactor reaches 626 tests and 220 failed/errored. M0C "
            "recorded 221; one auth test passes here and its cause is not "
            "proven. The delta is recorded, not fixed.",
            "Rescued pipeline skips the report-only PMD goal; both comparison "
            "sides omit PMD.",
            "Warm Maven cache only; no cold-cache M3 claim.",
            "No M4 incremental scope reduction is included.",
        ],
    }
    write_json(os.path.join(EVID, "results.json"), results)
    write_json(os.path.join(EVID, "test-inventory.json"),
               results["test_inventory"])
    print("\n=== M3 comparison ===")
    print(json.dumps(results["medians"], indent=2))
    print("results: " + os.path.relpath(
        evidence_paths.generated_path(os.path.join(EVID, "results.json")), ROOT))
    return 0


def methodology(threads):
    return {
        "m2_baseline": "The committed M2 baseline, 25 tests, early failure. "
                       "Preserved unchanged and not used for speed comparison.",
        "baseline_full": "M2 baseline job with FULL_SCOPE=true: clean install "
                         "with tests skipped, then mvn test -fae. PMD skipped. "
                         "Warm cache, 626 tests, 43 reactor entries.",
        "rescued": "One mvn verify -fae -T " + str(threads) + " pass. PMD "
                   "skipped. Warm cache, 626 tests, 43 reactor entries.",
        "workload_equivalence": "Both sides run the same 43 reactor entries, "
                                "the same 626 tests and 220 failed/errored "
                                "tests in this environment. M0C recorded 221; "
                                "auth.controller.AuthControllerTest."
                                "testCreateDefaultUser appears order-sensitive "
                                "and passes here; the cause is not proven. The "
                                "one-test delta is recorded, not fixed.",
        "cache": "Warm /m2 cache, no cold-cache M3 claim.",
        "excluded": "PMD report-only goal, Docker build/push, mail and the "
                    "Jenkins JaCoCo status step are excluded from both sides.",
        "thread_choice": "1, 2 and 4 investigated once each; 2 chosen as the "
                         "conservative final setting.",
    }


def post_run(evid=EVID):
    lines = [
        "M3 post-run snapshot",
        "date UTC: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "=== docker ps ===",
    ]
    rc, out = m2.docker("ps", "--format",
                        "{{.Names}} {{.Status}} {{.Ports}}")
    lines.append(out.strip())
    rc, out = m2.docker("stats", "--no-stream", "--format",
                        "{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}")
    lines.append("=== docker stats ===")
    lines.append(out.strip())
    lines.append("=== cache MB ===")
    lines.append(str(cache_mb()))
    rc, out = m2.run(["df", "-h", ROOT])
    lines.append("=== disk ===")
    lines.append(out.strip().splitlines()[-1] if out.strip() else "")
    write_text(os.path.join(evid, "post-run.txt"), "\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("threads", "compare", "reparse-threads", "control"), required=True)
    parser.add_argument("--threads", type=int, default=2, choices=(1, 2, 4))
    parser.add_argument("--resume", action="store_true", help="reparse and skip existing compare labels")
    args = parser.parse_args()
    if args.mode == "reparse-threads":
        return reparse_threads()
    if args.mode == "control":
        try:
            return control_mode()
        except Exception as exc:  # noqa: BLE001
            print(f"STOPPED: {exc}", file=sys.stderr)
            return 1
    os.makedirs(evidence_paths.generated_dir(EVID), exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    preflight()
    try:
        if args.mode == "threads":
            code = thread_mode()
            post_run()
            return code
        code = compare_mode(args.threads, resume=args.resume)
        post_run()
        return code
    except Exception as exc:  # noqa: BLE001
        print(f"STOPPED: {exc}", file=sys.stderr)
        post_run()
        return 1


if __name__ == "__main__":
    sys.exit(main())
