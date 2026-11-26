#!/usr/bin/env python3
"""M2 baseline measurement: three cold-cache and three warm-cache builds.

Runs only the train-ticket-baseline job, sequentially. Raw console logs stay
under evidence/M2/raw/ (gitignored); sanitized machine-readable results are
written under evidence/M2/work/generated/ (gitignored).
"""
import datetime
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jenkins_api as api  # noqa: E402
import evidence_paths  # noqa: E402

EVID = os.path.join(ROOT, "evidence", "M2")
RAW = os.path.join(EVID, "raw")
JOB = "train-ticket-baseline"
PIN = "313886e99befb94be6cd45f085c98e0019f59829"
RUNS = [(1, "cold"), (2, "cold"), (3, "cold"),
        (4, "warm"), (5, "warm"), (6, "warm")]
ALLOWED_CONTAINERS = {"prk-m1-controller", "prk-m1-agent"}
BUILD_TIMEOUT_S = 1800
MAX_RUNS = 6


def run(cmd, timeout=120, cwd=ROOT):
    try:
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True,
                              timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"
    except OSError as exc:
        return 127, str(exc)


def docker(*args, timeout=120):
    return run(["docker", *args], timeout=timeout, cwd=ROOT)


def write_text(path, text):
    path = evidence_paths.generated_path(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_json(path, value):
    write_text(path, json.dumps(value, indent=2) + "\n")


def cache_mb():
    rc, out = docker("exec", "prk-m1-agent", "sh", "-c",
                     "if [ -d /m2/repository ]; then du -sm /m2/repository | cut -f1; else echo 0; fi")
    if rc != 0:
        raise RuntimeError(f"cannot read Maven cache size: {out.strip()}")
    return int(out.strip() or "0")


def clear_cache():
    rc, out = docker("exec", "prk-m1-agent", "sh", "-c", "rm -rf /m2/repository")
    if rc != 0:
        raise RuntimeError(f"cannot clear Maven cache: {out.strip()}")
    return cache_mb()


def preflight():
    rc, ps = docker("ps", "--format", "{{.Names}}")
    if rc != 0:
        raise RuntimeError(f"docker ps failed: {ps.strip()}")
    names = {line.strip() for line in ps.splitlines() if line.strip()}
    unexpected = sorted(names - ALLOWED_CONTAINERS)
    if unexpected:
        raise RuntimeError(f"unexpected running containers: {unexpected}")
    if not ALLOWED_CONTAINERS.issubset(names):
        raise RuntimeError(f"missing project containers: {sorted(ALLOWED_CONTAINERS - names)}")

    source = os.path.join(EVID, "work", "train-ticket")
    rc, sha = run(["git", "-C", source, "rev-parse", "HEAD"])
    if rc != 0 or sha.strip() != PIN:
        raise RuntimeError(f"pinned source SHA mismatch: {sha.strip()!r}")

    api.wait_controller(120)
    api.wait_agent_online("linux-agent", 120)

    rc, info = docker("info", "--format",
                      "CPUs={{.NCPU}} MemTotal={{.MemTotal}} Arch={{.Architecture}}")
    rc, stats = docker("stats", "--no-stream", "--format",
                       "{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}")
    rc, disk = run(["df", "-h", ROOT])
    rc, java = docker("exec", "prk-m1-agent", "/opt/java/jdk8/bin/java", "-version")
    rc, maven = docker("exec", "prk-m1-agent", "sh", "-c",
                       "JAVA_HOME=/opt/java/jdk8 /opt/maven/bin/mvn -v")

    lines = [
        "M2 preflight",
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
        "cache MB before series: " + str(cache_mb()),
    ]
    write_text(os.path.join(EVID, "environment.txt"), "\n".join(lines) + "\n")
    print("\n".join(lines[:8]))
    return names


def start_stats(raw_dir):
    stop = threading.Event()
    path = os.path.join(raw_dir, "docker-stats.log")

    def sample():
        with open(path, "w", encoding="utf-8") as fh:
            while not stop.is_set():
                rc, out = docker("stats", "--no-stream", "--format",
                                 "{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}")
                if rc == 0:
                    fh.write(out)
                    fh.flush()
                stop.wait(15)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    return stop, thread


def parse_exits(console):
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"PRK_MAVEN_EXIT_([A-Z_]+)=(-?\d+)", console)}


def parse_stages(wf):
    stages = []
    for stage in (wf or {}).get("stages", []):
        stages.append({
            "name": stage.get("name"),
            "status": stage.get("status"),
            "duration_ms": stage.get("durationMillis"),
        })
    return stages


def parse_reactor_blocks(text):
    lines = text.splitlines()
    blocks = []
    i = 0
    pattern = re.compile(
        r"^(?:\[[^\]]+\]\s*)?\[INFO\] (.+?) \.{3,} "
        r"(SUCCESS|FAILURE|SKIPPED) \[\s*(?:([0-9.]+) s|([0-9]+):([0-9]{2}) min)\]")
    while i < len(lines):
        if "Reactor Summary" in lines[i]:
            modules = []
            j = i + 1
            while j < len(lines) and "BUILD " not in lines[j]:
                match = pattern.match(lines[j])
                if match:
                    if match.group(3) is not None:
                        seconds = float(match.group(3))
                    else:
                        seconds = int(match.group(4)) * 60 + int(match.group(5))
                    modules.append({
                        "display_name": match.group(1).strip(),
                        "result": match.group(2),
                        "seconds": seconds,
                    })
                j += 1
            blocks.append(modules)
            i = j
        i += 1
    return blocks


def parse_reactors(console):
    build_at = console.find("(Build)")
    test_at = console.find("(Test)")
    segments = []
    if build_at >= 0 and test_at > build_at:
        segments.append(("build", console[build_at:test_at]))
        segments.append(("test", console[test_at:]))
    else:
        segments.append(("unknown", console))

    reactors = []
    for stage, segment in segments:
        blocks = parse_reactor_blocks(segment)
        for index, modules in enumerate(blocks):
            label = stage
            if stage == "test" and len(blocks) > 1:
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


def parse_test_report(report):
    if not report:
        return {"reported": 0, "passed": 0, "failures": 0, "errors": 0,
                "skipped": 0, "failed_cases": []}
    reported = report.get("totalCount")
    if reported is None:
        reported = (report.get("passCount", 0)
                    + report.get("failCount", 0)
                    + report.get("skipCount", 0))
    totals = {
        "reported": reported,
        "passed": report.get("passCount", 0),
        # The JUnit API merges failures and errors into failCount. The
        # console parser below provides the failure/error split.
        "failures": report.get("failCount", 0),
        "errors": 0,
        "skipped": report.get("skipCount", 0),
        "failed_cases": [],
    }
    for suite in report.get("suites", []):
        for case in suite.get("cases", []):
            status = (case.get("status") or "").upper()
            if status in ("FAILED", "ERROR", "REGRESSION"):
                totals["failed_cases"].append({
                    "class": case.get("className"),
                    "test": case.get("name"),
                    "status": status,
                })
    return totals


def parse_console_tests(console):
    pattern = re.compile(
        r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+), "
        r"Time elapsed: [0-9.]+ s(?: <<< [^ ]+!)? - in (\S+)")
    rows = []
    for match in pattern.finditer(console):
        rows.append({
            "class": match.group(5),
            "tests": int(match.group(1)),
            "failures": int(match.group(2)),
            "errors": int(match.group(3)),
            "skipped": int(match.group(4)),
        })
    return {
        "reported": sum(r["tests"] for r in rows),
        "passed": sum(r["tests"] - r["failures"] - r["errors"] - r["skipped"]
                      for r in rows),
        "failures": sum(r["failures"] for r in rows),
        "errors": sum(r["errors"] for r in rows),
        "skipped": sum(r["skipped"] for r in rows),
        "failed_cases": [],
        "per_class": rows,
    }


def annotate_failed_cases(tests, console_tests):
    rows = {row["class"]: row for row in console_tests.get("per_class", [])}
    for case in tests.get("failed_cases", []):
        row = rows.get(case.get("class"))
        if not row:
            continue
        if row.get("errors", 0) > 0:
            case["status"] = "ERROR"
        elif row.get("failures", 0) > 0:
            case["status"] = "FAILED"
    return tests


def trigger_build():
    data = api.get_json(f"/job/{JOB}/api/json?tree=lastBuild[number,building]")
    last = data.get("lastBuild") or {}
    waited = 0
    while last.get("building") and waited < 120:
        time.sleep(5)
        waited += 5
        data = api.get_json(f"/job/{JOB}/api/json?tree=lastBuild[number,building]")
        last = data.get("lastBuild") or {}
    if last.get("building"):
        raise RuntimeError("baseline job is already running")

    before = last.get("number", 0)
    api.post(f"/job/{JOB}/build")

    deadline = time.monotonic() + BUILD_TIMEOUT_S
    number = None
    while time.monotonic() < deadline:
        data = api.get_json(
            f"/job/{JOB}/api/json?tree=lastBuild[number,building]")
        last = data.get("lastBuild") or {}
        if last.get("number", 0) > before:
            number = last["number"]
        if number and not last.get("building"):
            return number
        time.sleep(3)

    if number:
        try:
            api.post(f"/job/{JOB}/{number}/stop")
        except Exception:
            pass
    raise RuntimeError(f"baseline build timed out after {BUILD_TIMEOUT_S}s")


def fetch_build(number):
    build = api.get_json(
        f"/job/{JOB}/{number}/api/json"
        "?tree=number,result,duration,timestamp,builtOn,displayName")
    status, console, _ = api.request(f"/job/{JOB}/{number}/consoleText", timeout=60)
    if status != 200:
        raise RuntimeError(f"console log returned {status}")
    return build, console.decode("utf-8", errors="replace")


def fetch_wfapi(number):
    status, body, _ = api.request(f"/job/{JOB}/{number}/wfapi/describe", timeout=30)
    if status != 200:
        return None
    return json.loads(body.decode("utf-8"))


def fetch_test_report(number):
    status, body, _ = api.request(
        f"/job/{JOB}/{number}/testReport/api/json", timeout=60)
    if status != 200:
        return None
    return json.loads(body.decode("utf-8"))


def peak_mem_gib(stats_text):
    values = []
    for value, unit in re.findall(r"mem=([0-9.]+)([KMG])iB", stats_text):
        factor = {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1.0}[unit]
        values.append(float(value) * factor)
    return round(max(values), 3) if values else None


def run_one(index, state):
    label = f"run-{index:02d}-{state}"
    raw_dir = os.path.join(RAW, label)
    os.makedirs(raw_dir, exist_ok=True)
    print(f"\n=== {label} ===")

    if state == "cold":
        before = clear_cache()
        print(f"cache cleared: {before} MB")
        if before != 0:
            raise RuntimeError("cold cache is not empty")
    else:
        before = cache_mb()
        if before == 0:
            raise RuntimeError("warm cache is empty")
        print(f"warm cache: {before} MB")

    stop, thread = start_stats(raw_dir)
    started = time.monotonic()
    started_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    try:
        number = trigger_build()
        build, console = fetch_build(number)
        wfapi = fetch_wfapi(number)
        report = fetch_test_report(number)
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
    stages = parse_stages(wfapi)
    reactors = parse_reactors(console)
    report_tests = parse_test_report(report)
    console_tests = parse_console_tests(console)
    tests = console_tests if console_tests["reported"] else report_tests
    tests["jenkins_reported"] = report_tests["reported"]
    if report_tests["failed_cases"]:
        tests["failed_cases"] = report_tests["failed_cases"]
    annotate_failed_cases(tests, console_tests)

    rc, stats_text = run(["cat", os.path.join(raw_dir, "docker-stats.log")])
    peak = peak_mem_gib(stats_text)

    stage_sum = sum(s["duration_ms"] for s in stages
                    if s.get("duration_ms") is not None)
    run_data = {
        "run": index,
        "label": label,
        "cache": state,
        "build_number": number,
        "result": build.get("result"),
        "jenkins_duration_ms": build.get("duration"),
        "jenkins_timestamp_ms": build.get("timestamp"),
        "started_at": started_at,
        "finished_at": ended_at,
        "host_wall_clock_s": host_wall,
        "stages": stages,
        "stage_sum_ms": stage_sum,
        "post_estimate_ms": (build.get("duration") or 0) - stage_sum,
        "maven_exit_codes": exits,
        "cache_before_mb": before,
        "cache_after_mb": after,
        "reactors": reactors,
        "tests": tests,
        "peak_container_mem_gib": peak,
        "raw_dir": os.path.relpath(raw_dir, ROOT),
    }
    write_json(os.path.join(EVID, label + ".json"), run_data)

    print(f"build #{number}: {build.get('result')} "
          f"duration={build.get('duration')} ms host={host_wall}s")
    print(f"stages: " + ", ".join(
        f"{s['name']}={s['duration_ms']}ms/{s['status']}" for s in stages))
    print(f"maven exits: {exits}")
    print(f"tests: {tests['reported']} reported, {tests['failures']} failures, "
          f"{tests['errors']} errors, {tests['skipped']} skipped")
    print(f"cache: {before} -> {after} MB, peak mem {peak} GiB")

    return run_data


def validate_run(data):
    if data["result"] == "SUCCESS":
        raise RuntimeError(f"{data['label']}: unexpected SUCCESS; tests may have been skipped")
    if data["result"] not in ("FAILURE", "UNSTABLE"):
        raise RuntimeError(f"{data['label']}: unexpected result {data['result']}")
    exits = data["maven_exit_codes"]
    if exits.get("BUILD") != 0:
        raise RuntimeError(f"{data['label']}: build Maven exit {exits.get('BUILD')}")
    if exits.get("PMD") not in (None, 0):
        raise RuntimeError(f"{data['label']}: PMD Maven exit {exits.get('PMD')}")
    if exits.get("TEST") in (None, 0):
        raise RuntimeError(f"{data['label']}: test Maven exit {exits.get('TEST')}")


def medians(runs):
    result = {}
    for state in ("cold", "warm"):
        subset = [r for r in runs if r["cache"] == state]
        if not subset:
            continue
        stages = {}
        for name in ("Checkout pinned source", "Build", "Test"):
            values = [next((s["duration_ms"] for s in r["stages"]
                            if s["name"] == name and s["duration_ms"] is not None),
                           None) for r in subset]
            values = [v for v in values if v is not None]
            if values:
                stages[name] = round(statistics.median(values), 1)
        result[state] = {
            "runs": len(subset),
            "host_wall_clock_s": round(statistics.median(
                [r["host_wall_clock_s"] for r in subset]), 1),
            "jenkins_duration_ms": round(statistics.median(
                [r["jenkins_duration_ms"] for r in subset]), 1),
            "stages_ms": stages,
            "cache_before_mb": round(statistics.median(
                [r["cache_before_mb"] for r in subset]), 1),
            "cache_after_mb": round(statistics.median(
                [r["cache_after_mb"] for r in subset]), 1),
        }
    return result


def write_known_inventory():
    m0c = json.load(open(os.path.join(ROOT, "evidence", "M0C",
                                      "reactor-results.json"), encoding="utf-8"))
    known = {
        "source": "evidence/M0C/reactor-results.json",
        "source_sha": PIN,
        "totals": m0c["totals"],
        "failed_or_errored": len(m0c["failing_cases"]),
        "failing_cases": m0c["failing_cases"],
    }
    write_json(os.path.join(EVID, "known-failure-inventory.json"), known)
    return known


def write_aggregate(runs, status, error, known):
    results = {
        "milestone": "M2",
        "status": status,
        "measurement_status": status,
        "baseline_build_outcome": (
            "FAILURE" if runs and all(r["result"] == "FAILURE" for r in runs)
            else (runs[-1]["result"] if runs else None)
        ),
        "measured_runs": len(runs),
        "error": error,
        "source": {
            "repository": "https://github.com/FudanSELab/train-ticket.git",
            "checkout": "evidence/M2/work/train-ticket",
            "commit": PIN,
            "upstream_jenkinsfile": "jenkins-ci/Jenkinsfile",
        },
        "pipeline": "harness/pipelines/train-ticket/Jenkinsfile.baseline",
        "runs": runs,
        "medians": medians(runs),
        "known_full_inventory": {
            "source": known["source"],
            "totals": known["totals"],
            "failed_or_errored": known["failed_or_errored"],
        },
        "baseline_build_results": sorted({r["result"] for r in runs}),
        "aborted_attempts": [
            json.load(open(evidence_paths.evidence_read(
                os.path.join(EVID, name)), encoding="utf-8"))
            for name in sorted({
                name
                for base in (evidence_paths.generated_dir(EVID), EVID)
                if os.path.isdir(base)
                for name in os.listdir(base)
                if name.startswith("attempt-") and name.endswith(".json")
            })
        ],
    }
    write_json(os.path.join(EVID, "results.json"), results)

    baseline_tests = {
        "known_full_inventory": {
            "source": known["source"],
            "totals": known["totals"],
            "failed_or_errored": known["failed_or_errored"],
        },
        "baseline_runs": {
            r["label"]: {
                "build_number": r["build_number"],
                "result": r["result"],
                "tests": r["tests"],
            } for r in runs
        },
    }
    write_json(os.path.join(EVID, "test-inventory.json"), baseline_tests)

    print("\n=== M2 summary ===")
    print(f"status: {status}")
    print(json.dumps(results["medians"], indent=2))
    print("results: " + os.path.relpath(
        evidence_paths.generated_path(os.path.join(EVID, "results.json")), ROOT))
    return 0 if status == "PASS" else 1


def reparse():
    """Rebuild sanitized results from the raw logs of the six completed runs."""
    known = write_known_inventory()
    runs = []
    for index, state in RUNS:
        label = f"run-{index:02d}-{state}"
        raw_dir = os.path.join(RAW, label)
        result_path = evidence_paths.evidence_read(
            os.path.join(EVID, label + ".json"))
        if not os.path.exists(result_path):
            raise SystemExit(f"missing {result_path}")
        run_data = json.load(open(result_path, encoding="utf-8"))
        console = open(os.path.join(raw_dir, "console.log"),
                       encoding="utf-8", errors="replace").read()
        build = json.load(open(os.path.join(raw_dir, "build.json"),
                               encoding="utf-8"))
        wfapi = json.load(open(os.path.join(raw_dir, "wfapi.json"),
                               encoding="utf-8"))
        report_path = os.path.join(raw_dir, "test-report.json")
        report = json.load(open(report_path, encoding="utf-8")) \
            if os.path.exists(report_path) else None

        exits = parse_exits(console)
        stages = parse_stages(wfapi)
        reactors = parse_reactors(console)
        report_tests = parse_test_report(report)
        console_tests = parse_console_tests(console)
        tests = console_tests if console_tests["reported"] else report_tests
        tests["jenkins_reported"] = report_tests["reported"]
        if report_tests["failed_cases"]:
            tests["failed_cases"] = report_tests["failed_cases"]
        annotate_failed_cases(tests, console_tests)

        stage_sum = sum(s["duration_ms"] for s in stages
                        if s.get("duration_ms") is not None)
        run_data.update({
            "result": build.get("result"),
            "jenkins_duration_ms": build.get("duration"),
            "stages": stages,
            "stage_sum_ms": stage_sum,
            "post_estimate_ms": (build.get("duration") or 0) - stage_sum,
            "maven_exit_codes": exits,
            "reactors": reactors,
            "tests": tests,
        })
        write_json(result_path, run_data)
        runs.append(run_data)
        print(f"reparsed {label}: {tests['reported']} reported, "
              f"{tests['failures']} failures, {tests['errors']} errors")
    return write_aggregate(runs, "PASS", None, known)


def main():
    os.makedirs(evidence_paths.generated_dir(EVID), exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    known = write_known_inventory()
    runs = []
    status = "PASS"
    error = None
    try:
        preflight()
        for index, state in RUNS:
            data = run_one(index, state)
            validate_run(data)
            runs.append(data)
    except Exception as exc:  # noqa: BLE001
        status = "BLOCKED"
        error = str(exc)
        print(f"STOPPED: {error}", file=sys.stderr)

    return write_aggregate(runs, status, error, known)


if __name__ == "__main__":
    if "--reparse" in sys.argv[1:]:
        sys.exit(reparse())
    sys.exit(main())
