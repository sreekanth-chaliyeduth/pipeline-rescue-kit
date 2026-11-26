#!/usr/bin/env python3
"""One-command Pipeline Rescue Kit demo.

Prepares the pinned sources and the generated PetClinic repository, ensures the
Jenkins harness is running, builds the multibranch clean reference first and
then the controlled PR scenarios. Prints a table of expected versus observed
results and exits non-zero when any scenario disagrees.

Expected negative results (the failing feature branches) are successful
demonstration outcomes. A timeout, a missing reference, a missing report or an
unexpected pass makes the command fail.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = os.environ.get("JENKINS_PORT", "8080")
os.environ.setdefault("JENKINS_URL", f"http://127.0.0.1:{PORT}")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jenkins_api as api  # noqa: E402

MULTIBRANCH = "/job/petclinic-pr"
BRANCHES = ("main", "feature/small-untested-change", "feature/pmd-violation",
            "feature/fixed", "feature/docs-only")
BUILD_TIMEOUT = 1200


def say(message):
    print(message, flush=True)


def run(cmd):
    say(f"+ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc.returncode


def prepare():
    say("== preparing pinned sources and the demo repository ==")
    run([sys.executable, "harness/scripts/m5_prepare_sources.py"])
    run([sys.executable, "harness/scripts/m6_prepare_sources.py"])
    run(["bash", "harness/scripts/make-demo-repo.sh"])


def ensure_jenkins():
    say("== ensuring the Jenkins harness ==")
    try:
        api.wait_controller(10)
    except Exception:
        say("Jenkins is not reachable; starting the harness with make up")
        run(["make", "up"])
        api.wait_controller(300)
    api.wait_agent_online("linux-agent", 300)
    say(f"Jenkins ready at {api.BASE}")


def check_jobs():
    jobs = sorted(job["name"] for job in
                  api.get_json("/api/json?tree=jobs[name]").get("jobs", []))
    required = ["petclinic", "petclinic-baseline", "petclinic-pr",
                "train-ticket", "train-ticket-baseline", "train-ticket-prgate",
                "train-ticket-prgate-baseline"]
    missing = [job for job in required if job not in jobs]
    if missing:
        raise RuntimeError(f"missing Jenkins jobs: {', '.join(missing)}")
    say("jobs: " + ", ".join(jobs))


def job_path(branch):
    if branch == "main":
        return f"{MULTIBRANCH}/job/main"
    return f"{MULTIBRANCH}/job/{urllib.parse.quote(branch, safe='')}"


def scan():
    say("== indexing petclinic-pr ==")
    api.post(f"{MULTIBRANCH}/build")
    deadline = time.monotonic() + 300
    names = set()
    while time.monotonic() < deadline:
        children = api.get_json(
            f"{MULTIBRANCH}/api/json?tree=jobs[name]").get("jobs", [])
        names = {urllib.parse.unquote(job["name"]) for job in children}
        if set(BRANCHES) <= names:
            say("branches: " + ", ".join(sorted(names)))
            return
        time.sleep(3)
    raise RuntimeError(f"branches not discovered within 300s: {sorted(names)}")


def wait_idle():
    """Wait for automatic discovery builds and the queue to drain."""
    say("== waiting for automatic discovery builds ==")
    stable = 0
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        queue = api.get_json("/queue/api/json?tree=items[id]").get("items", [])
        busy = False
        for branch in BRANCHES:
            data = api.get_json(
                f"{job_path(branch)}/api/json?tree=lastBuild[building]")
            if (data.get("lastBuild") or {}).get("building"):
                busy = True
                break
        if not queue and not busy:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
        time.sleep(5)
    raise RuntimeError("automatic builds did not settle within 1800s")


def next_build(path):
    return api.get_json(f"{path}/api/json?tree=nextBuildNumber")["nextBuildNumber"]


def wait_build(path, number):
    deadline = time.monotonic() + BUILD_TIMEOUT
    while time.monotonic() < deadline:
        status, body, _ = api.request(f"{path}/{number}/api/json"
                                      "?tree=number,building,result")
        if status == 200:
            data = json.loads(body.decode("utf-8"))
            if not data.get("building"):
                return data.get("result")
        elif status != 404:
            raise RuntimeError(f"{path} #{number} returned {status}")
        time.sleep(5)
    raise RuntimeError(f"{path} #{number} did not finish within {BUILD_TIMEOUT}s")


def build(path):
    number = next_build(path)
    api.post(f"{path}/build")
    result = wait_build(path, number)
    return number, result


def artifact(path, number, name):
    status, body, _ = api.request(f"{path}/{number}/artifact/{name}")
    if status != 200:
        raise RuntimeError(f"missing {name} for {path} #{number}: {status}")
    return body.decode("utf-8", errors="replace")


def console(path, number):
    status, body, _ = api.request(f"{path}/{number}/consoleText")
    if status != 200:
        raise RuntimeError(f"missing console for {path} #{number}: {status}")
    return body.decode("utf-8", errors="replace")


STATE_RE = re.compile(r":\s*([A-Z][A-Z ]+?)\s*\(([^)]*)\)")
STATIC_RE = re.compile(r":\s*([A-Z][A-Z ]+?)\s*\((\d+) total, (\d+) new\)")


def parse_summary(text):
    data = {"project": None, "modified": None, "static": None,
            "decision": None, "ref_build": None, "ref_job": None}
    for line in text.splitlines():
        if line.startswith("- Coverage ") and "project" in line:
            match = STATE_RE.search(line)
            if match:
                data["project"] = (match.group(1), match.group(2))
        elif line.startswith("- Coverage ") and "modified lines" in line:
            match = STATE_RE.search(line)
            if match:
                data["modified"] = (match.group(1), match.group(2))
        elif line.startswith("- Static analysis"):
            match = STATIC_RE.search(line)
            if match:
                data["static"] = (match.group(1), int(match.group(2)),
                                  int(match.group(3)))
        elif line.startswith("- Decision:"):
            data["decision"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Static reference build:"):
            data["ref_build"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Static reference job:"):
            data["ref_job"] = line.split(":", 1)[1].strip()
    return data


def blocked_reason(text):
    for line in text.splitlines():
        if "prGate blocked:" in line:
            return line.split("prGate blocked:", 1)[1].strip()
    return ""


def library_line(text):
    for line in text.splitlines():
        if line.startswith("Loading library "):
            return line.strip()
    return ""


def evaluate(name, result, summary, console_text, main_number):
    data = parse_summary(summary)
    reason = blocked_reason(console_text)
    checks = []
    if name == "main":
        checks.append(("result SUCCESS", result == "SUCCESS"))
        checks.append(("decision PASS", data["decision"] == "PASS"))
        checks.append(("project published", (data["project"] or ("", ""))[0] == "PUBLISHED"))
        checks.append(("no modified gate", data["modified"] is None))
        gate = "none"
    elif name == "small":
        checks.append(("result FAILURE", result == "FAILURE"))
        checks.append(("project PASS", (data["project"] or ("", ""))[0] == "PASS"))
        checks.append(("modified FAIL", (data["modified"] or ("", ""))[0] == "FAIL"))
        checks.append(("blocked by modified lines",
                       "modified lines" in reason and "pmd" not in reason))
        gate = "modified lines"
    elif name == "pmd":
        static = data["static"] or ("", 0, 0)
        checks.append(("result FAILURE", result == "FAILURE"))
        checks.append(("project PASS", (data["project"] or ("", ""))[0] == "PASS"))
        checks.append(("modified PASS", (data["modified"] or ("", ""))[0] == "PASS"))
        checks.append(("pmd FAIL", static[0] == "FAIL"))
        checks.append(("exactly one new issue", static[2] == 1))
        checks.append(("blocked by pmd only",
                       "pmd" in reason and "modified lines" not in reason))
        gate = "PMD (1 new)"
    elif name == "fixed":
        checks.append(("result SUCCESS", result == "SUCCESS"))
        checks.append(("decision PASS", data["decision"] == "PASS"))
        checks.append(("project PASS", (data["project"] or ("", ""))[0] == "PASS"))
        checks.append(("modified PASS", (data["modified"] or ("", ""))[0] == "PASS"))
        gate = "none"
    else:  # docs
        checks.append(("result SUCCESS", result == "SUCCESS"))
        checks.append(("decision PASS", data["decision"] == "PASS"))
        checks.append(("project PASS", (data["project"] or ("", ""))[0] == "PASS"))
        checks.append(("no modified lines",
                       "no modified lines" in (data["modified"] or ("", ""))[1]))
        gate = "none (no modified lines)"
    if name != "main":
        checks.append(("reference job", data["ref_job"] == "petclinic-pr/main"))
        checks.append(("reference build", data["ref_build"] == f"#{main_number}"))
    failed = [label for label, ok in checks if not ok]
    return {"data": data, "reason": reason, "gate": gate,
            "failed": failed, "ok": not failed}


def main():
    start = time.time()
    try:
        prepare()
        ensure_jenkins()
        check_jobs()
        scan()
        wait_idle()

        say("== building the clean reference petclinic-pr/main ==")
        main_number, main_result = build(job_path("main"))
        if main_result != "SUCCESS":
            raise RuntimeError(f"petclinic-pr/main #{main_number} was {main_result}, "
                               "no feature build is attempted")
        say(f"main reference: petclinic-pr/main #{main_number} SUCCESS")

        scenarios = [
            ("small (run 1)", "small", "feature/small-untested-change"),
            ("small (run 2)", "small", "feature/small-untested-change"),
            ("pmd (run 1)", "pmd", "feature/pmd-violation"),
            ("pmd (run 2)", "pmd", "feature/pmd-violation"),
            ("fixed", "fixed", "feature/fixed"),
            ("docs-only", "docs", "feature/docs-only"),
        ]
        rows = []
        for label, kind, branch in scenarios:
            path = job_path(branch)
            say(f"== building {branch} ({label}) ==")
            number, result = build(path)
            summary = artifact(path, number, "prgate-summary.md")
            text = console(path, number)
            verdict = evaluate(kind, result, summary, text, main_number)
            library = library_line(text)
            rows.append({"label": label, "branch": branch, "number": number,
                         "result": result, "kind": kind, "verdict": verdict,
                         "library": library})

        say("")
        say("== demo results ==")
        header = (f"{'Scenario':<16} {'Branch':<30} {'Build':<7} {'Result':<9} "
                  f"{'Expected':<22} {'Gate':<24} {'Main ref':<9} {'Agree'}")
        say(header)
        say("-" * len(header))
        all_ok = True
        expected = {
            "small": "FAIL modified lines", "pmd": "FAIL PMD only",
            "fixed": "PASS", "docs": "PASS no modified lines",
        }
        for row in rows:
            verdict = row["verdict"]
            all_ok = all_ok and verdict["ok"]
            say(f"{row['label']:<16} {row['branch']:<30} #{row['number']:<6} "
                f"{row['result']:<9} {expected[row['kind']]:<22} "
                f"{verdict['gate']:<24} #{main_number:<8} "
                f"{'YES' if verdict['ok'] else 'NO'}")
        say("")
        say("main: petclinic-pr/main #%d SUCCESS (clean reference)" % main_number)
        for row in rows:
            data = row["verdict"]["data"]
            project = data["project"] or ("?", "?")
            modified = data["modified"]
            static = data["static"] or ("?", 0, 0)
            say(f"{row['label']}: {row['library'] or 'library line missing'}")
            say(f"  project={project[0]} {project[1]}, "
                f"modified={modified[0] + ' ' + modified[1] if modified else 'disabled'}, "
                f"pmd={static[0]} {static[1]} total/{static[2]} new, "
                f"decision={data['decision']}, reference={data['ref_build']}")
            if row["verdict"]["failed"]:
                say("  FAILED CHECKS: " + "; ".join(row["verdict"]["failed"]))
            if row["verdict"]["reason"]:
                say(f"  block: {row['verdict']['reason']}")
        say("")
        say(f"wall clock: {int(time.time() - start)} s")
        if all_ok:
            say("DEMO PASS: every scenario matched its expected decision")
            return 0
        say("DEMO FAIL: at least one scenario did not match")
        return 1
    except Exception as exc:  # noqa: BLE001
        say(f"DEMO FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
