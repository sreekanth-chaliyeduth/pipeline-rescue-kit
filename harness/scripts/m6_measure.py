#!/usr/bin/env python3
"""Run the M6 PetClinic prGate scenarios and capture raw evidence."""
import argparse
import json
import os
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jenkins_api  # noqa: E402

JOB = "petclinic"
BRANCHES = os.path.join(ROOT, "evidence", "M6", "work", "branches.generated.json")
RAW = os.path.join(ROOT, "evidence", "M6", "raw")
DEFAULT_PARAMS = {
    "SOURCE_REPO": "/src/petclinic-m6",
    "COVERAGE_THRESHOLD": "90",
    "STATIC_NEW_ISSUE_THRESHOLD": "1",
}

SCENARIOS = {
    "seed": ("m6-green", False,
             "Publish-only PetClinic build that seeds the static-analysis reference."),
    "green": ("m6-green", True,
              "Enforced passing reference on the pinned PetClinic monolith."),
    "coverage-red": ("m6-coverage-red", True,
                     "Untested fixture drops project line coverage below 90%."),
    "static-red": ("m6-static-red", True,
                   "New nested-if fixture adds one PMD finding."),
    "fixed": ("m6-fixed", True,
              "Fixture covered and PMD issue absent; all gates pass."),
}
ORDER = ["seed", "green", "coverage-red", "static-red", "fixed"]


def load_branches():
    with open(BRANCHES, encoding="utf-8") as fh:
        return json.load(fh)


def trigger(name, params, timeout=1500):
    before = (jenkins_api.get_json(
        f"/job/{JOB}/api/json?tree=lastBuild[number]").get("lastBuild") or {}).get("number", 0)
    fields = dict(DEFAULT_PARAMS)
    fields.update(params)
    jenkins_api.post_form(f"/job/{JOB}/buildWithParameters",
                          {k: str(v).lower() if isinstance(v, bool) else str(v)
                           for k, v in fields.items()})

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = jenkins_api.get_json(
            f"/job/{JOB}/api/json?tree=lastBuild[number,building,result]")
        last = data.get("lastBuild") or {}
        number = last.get("number", 0)
        if number > before and not last.get("building", False):
            build = jenkins_api.get_json(
                f"/job/{JOB}/{number}/api/json"
                "?tree=number,result,building,duration,builtOn")
            status, console, _ = jenkins_api.request(
                f"/job/{JOB}/{number}/consoleText", timeout=60)
            if status != 200:
                raise RuntimeError(f"console log returned {status}")
            return number, build, console.decode("utf-8", errors="replace")
        time.sleep(3)
    raise RuntimeError(f"{name}: build did not finish within {timeout}s")


def artifact(number, path):
    quoted = urllib.parse.quote(path, safe="")
    status, body, _ = jenkins_api.request(
        f"/job/{JOB}/{number}/artifact/{quoted}", timeout=30)
    if status != 200:
        return None
    return body.decode("utf-8", errors="replace")


def run(name):
    branch, enforce, note = SCENARIOS[name]
    data = load_branches()
    sha = data["branches"][branch]
    params = {
        "ENFORCE": "true" if enforce else "false",
        "SOURCE_COMMIT": sha,
    }
    print(f"== {name}: {branch} {sha} enforce={enforce}")
    number, build, console = trigger(name, params)

    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(RAW, f"{name}-console.txt"), "w", encoding="utf-8") as fh:
        fh.write(console)
    summary = artifact(number, "prgate-summary.md")
    if summary is not None:
        with open(os.path.join(RAW, f"{name}-summary.md"), "w", encoding="utf-8") as fh:
            fh.write(summary)
    gap = artifact(number, "petclinic-test-gap.md")
    if gap is not None:
        with open(os.path.join(RAW, f"{name}-db-gap.md"), "w", encoding="utf-8") as fh:
            fh.write(gap)

    key_lines = [line for line in console.splitlines()
                 if any(token in line for token in (
                     "PRK_", "prGate", "Decision:", "Unit tests:", "Coverage (",
                     "Static analysis (", "Static reference build:", "Maven exit:",
                     "ERROR:", "BUILD SUCCESS", "BUILD FAILURE", "Tests run:",
                     "Loading library", "Coverage: ", "PMD issues",
                     "MySqlIntegrationTests", "PostgresIntegrationTests"))]
    record = {
        "scenario": name,
        "branch": branch,
        "commit": sha,
        "enforce": enforce,
        "note": note,
        "build": number,
        "result": build.get("result"),
        "duration_ms": build.get("duration"),
        "url": f"/job/{JOB}/{number}/",
        "summary": summary,
        "db_gap": gap,
        "key_lines": key_lines[-100:],
    }
    print(json.dumps({k: record[k] for k in
                      ("scenario", "build", "result", "duration_ms")}, indent=2))
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", nargs="?",
                        choices=sorted(SCENARIOS) + ["all"], default="all")
    args = parser.parse_args()
    names = ORDER if args.scenario == "all" else [args.scenario]
    records = [run(name) for name in names]
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, f"runs-{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)
        fh.write("\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
