#!/usr/bin/env python3
"""Run the five M4 selector scenarios and record actual Maven reactor selections."""
import json
import os
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m2_measure as m2  # noqa: E402
import evidence_paths  # noqa: E402

EVID = os.path.join(ROOT, "evidence", "M4")
RAW = os.path.join(EVID, "raw", "scenarios")
REPO = os.path.join(ROOT, "evidence", "M4", "work", "train-ticket")
PIN = "313886e99befb94be6cd45f085c98e0019f59829"
BRANCHES = {
    "one-service": "m4-service",
    "ts-common": "m4-common",
    "root-pom": "m4-root",
    "non-maven-directory": "m4-nonmaven",
    "documentation-only": "m4-docs",
}


def run(cmd, timeout=300):
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True,
                          timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def selector(head):
    rc, out = run([
        os.path.join(ROOT, "tools", "select-modules.sh"),
        "--repo", REPO,
        "--reference", PIN,
        "--head", head,
    ])
    if rc != 0:
        raise RuntimeError(f"selector failed for {head}: {out}")
    values = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        parts = shlex.split(line)
        if parts and "=" in parts[0]:
            key, value = parts[0].split("=", 1)
            values[key] = value
    return values


def branch_sha(branch):
    rc, out = run(["git", "-C", REPO, "rev-parse", branch])
    if rc != 0:
        raise RuntimeError(out)
    return out.strip()


def maven_validate(name, sha, mode, pl):
    raw_path = os.path.join(RAW, name + ".log")
    os.makedirs(RAW, exist_ok=True)
    if mode == "none":
        with open(raw_path, "w", encoding="utf-8") as fh:
            fh.write("PRK_SKIP_MAVEN: no Maven modules selected\n")
        return {
            "exit_code": None,
            "command": None,
            "reactor_count": 0,
            "status_counts": {},
            "modules": [],
            "raw_log": os.path.relpath(raw_path, ROOT),
            "skipped": True,
        }

    if mode == "full":
        maven = ("JAVA_HOME=/opt/java/jdk8 /opt/maven/bin/mvn "
                 "-B -Dmaven.repo.local=/m2/repository validate")
        command = "mvn validate (full reactor)"
    else:
        maven = ("JAVA_HOME=/opt/java/jdk8 /opt/maven/bin/mvn "
                 f"-B -Dmaven.repo.local=/m2/repository -pl '{pl}' -am -amd validate")
        command = f"mvn -pl {pl} -am -amd validate"

    script = (
        "set -eu; "
        "rm -rf /tmp/m4-scenario; "
        "git -c safe.directory=/src/train-ticket-m4 clone --no-checkout "
        "file:///src/train-ticket-m4 /tmp/m4-scenario >/dev/null 2>&1; "
        f"git -C /tmp/m4-scenario -c advice.detachedHead=false checkout {sha} >/dev/null 2>&1; "
        f"cd /tmp/m4-scenario; {maven}"
    )
    rc, out = run(["docker", "exec", "prk-m1-agent", "sh", "-c", script],
                  timeout=600)
    with open(raw_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    blocks = m2.parse_reactor_blocks(out)
    modules = blocks[-1] if blocks else []
    counts = {}
    for module in modules:
        counts[module["result"]] = counts.get(module["result"], 0) + 1
    return {
        "exit_code": rc,
        "command": command,
        "reactor_count": len(modules),
        "status_counts": counts,
        "modules": [m["display_name"] for m in modules],
        "raw_log": os.path.relpath(raw_path, ROOT),
        "skipped": False,
    }


def main():
    scenarios = []
    for name, branch in BRANCHES.items():
        sha = branch_sha(branch)
        sel = selector(sha)
        print(f"=== {name} ({branch} {sha}) ===")
        print(f"mode={sel.get('PRK_MODE')} pl={sel.get('PRK_PL')} "
              f"reason={sel.get('PRK_REASON')}")
        validation = maven_validate(
            name, sha, sel.get("PRK_MODE", ""), sel.get("PRK_PL", ""))
        print(f"validate: exit={validation['exit_code']} "
              f"reactor={validation['reactor_count']} "
              f"statuses={validation['status_counts']}")
        scenarios.append({
            "name": name,
            "branch": branch,
            "head": sha,
            "changed": sel.get("PRK_CHANGED"),
            "selector": sel,
            "maven_validate": validation,
        })

    obj = {
        "milestone": "M4",
        "reference": PIN,
        "scenarios": scenarios,
        "summary": {
            "one_service": "selects the service; Maven -am pulls required upstream",
            "ts_common": "selects ts-common; Maven -amd pulls dependents",
            "root_pom": "fail-safe full reactor",
            "non_maven_directory": "no Maven modules; skip",
            "documentation_only": "no Maven modules; skip",
        },
    }
    out = evidence_paths.generated_path(os.path.join(EVID, "scenarios.json"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")
    print("scenarios: " + os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
