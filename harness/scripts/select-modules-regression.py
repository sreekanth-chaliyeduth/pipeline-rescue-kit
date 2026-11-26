#!/usr/bin/env python3
"""Selector-only module regression checks, including fail-closed cases.

Creates disposable branches in the ignored Train-Ticket worktree. Does not run
Maven and does not modify historical evidence. Results go to a temporary
directory by default; set PRK_REGRESSION_EVID to keep them elsewhere.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.join(ROOT, "evidence", "M4", "work", "train-ticket")
SOURCE = os.path.join(ROOT, "evidence", "M2", "work", "train-ticket")
UPSTREAM = "https://github.com/FudanSELab/train-ticket.git"
PIN = "313886e99befb94be6cd45f085c98e0019f59829"
EVID = os.environ.get("PRK_REGRESSION_EVID") or tempfile.mkdtemp(
    prefix="prk-m4-selector-regression-")
SELECTOR = os.path.join(ROOT, "tools", "select-modules.sh")

SCENARIOS = [
    # name, path, kind, expected mode, expected module
    ("known-module", "ts-order-service/review-fix.txt", "write", "modules", "ts-order-service"),
    ("docs", "docs/review-fix.md", "write", "none", None),
    ("old-docs", "old-docs/review-fix.md", "write", "none", None),
    ("image", "image/review-fix.txt", "write", "none", None),
    ("deployment", "deployment/review-fix.yml", "write", "none", None),
    ("readme", "README.md", "append", "none", None),
    ("license", "LICENSE", "append", "none", None),
    ("root-pom", "pom.xml", "append", "full", None),
    ("unknown-root", "config/review-fix.yml", "write", "full", None),
    ("shared-resource", "src/main/resources/shared-review.yml", "write", "full", None),
    ("unknown-module-pom", "custom-service/pom.xml", "write", "full", None),
    ("gradle", "build.gradle", "write", "full", None),
    ("makefile", "Makefile", "append", "full", None),
    ("jenkinsfile", "Jenkinsfile", "write", "full", None),
    ("github-workflow", ".github/workflows/review-fix.yml", "write", "full", None),
    ("non-maven-avatar", "ts-avatar-service/review-fix.txt", "write", "none", None),
    ("non-maven-news", "ts-news-service/review-fix.txt", "write", "none", None),
    ("non-maven-ticket-office", "ts-ticket-office-service/review-fix.txt", "write", "none", None),
    ("non-maven-ui-dashboard", "ts-ui-dashboard/review-fix.txt", "write", "none", None),
    ("non-maven-voucher", "ts-voucher-service/review-fix.txt", "write", "none", None),
    ("module-markdown", "ts-order-service/src/main/resources/x.md", "write", "modules", "ts-order-service"),
    ("module-docs-markdown", "ts-order-service/docs/x.md", "write", "modules", "ts-order-service"),
]


def run(cmd, cwd=ROOT, timeout=120):
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True,
                          timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def git(*args):
    rc, out = run(["git", "-C", REPO, *args])
    if rc != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out}")
    return out.strip()


def ensure_repo():
    if os.path.isdir(os.path.join(REPO, ".git")):
        return
    if not os.path.isdir(SOURCE):
        os.makedirs(os.path.dirname(SOURCE), exist_ok=True)
        rc, out = run(["git", "clone", UPSTREAM, SOURCE])
        if rc != 0:
            raise RuntimeError(out)
        rc, out = run(["git", "-C", SOURCE, "checkout", PIN])
        if rc != 0:
            raise RuntimeError(out)
    os.makedirs(os.path.dirname(REPO), exist_ok=True)
    rc, out = run(["git", "clone", "--no-hardlinks", SOURCE, REPO])
    if rc != 0:
        raise RuntimeError(out)


def create_branch(name, path, kind):
    git("checkout", "-B", name, PIN)
    full = os.path.join(REPO, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if kind == "append":
        with open(full, "a", encoding="utf-8") as fh:
            fh.write("\n<!-- M4 review selector regression -->\n" if path.endswith(".xml")
                     else "\n# M4 review selector regression\n" if path == "Makefile"
                     else "\nM4 review selector regression.\n")
    else:
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("M4 review selector regression.\n")
    git("add", "-A")
    git("commit", "-m", f"M4 review regression: {name}")


def selector(head):
    rc, out = run([SELECTOR, "--repo", REPO, "--reference", PIN, "--head", head])
    if rc != 0:
        raise RuntimeError(f"selector failed for {head}: {out}")
    values = {}
    for line in out.splitlines():
        parts = shlex.split(line)
        if parts and "=" in parts[0]:
            key, value = parts[0].split("=", 1)
            values[key] = value
    return values


def main():
    ensure_repo()
    results = []
    failures = 0
    for name, path, kind, expected_mode, expected_module in SCENARIOS:
        branch = f"m4-review-{name}"
        create_branch(branch, path, kind)
        head = git("rev-parse", branch)
        sel = selector(head)
        mode = sel.get("PRK_MODE")
        pl = sel.get("PRK_PL", "")
        ok = mode == expected_mode and (expected_module is None or pl == expected_module)
        if not ok:
            failures += 1
        result = {
            "name": name,
            "path": path,
            "expected_mode": expected_mode,
            "expected_module": expected_module,
            "actual_mode": mode,
            "actual_module": pl,
            "reason": sel.get("PRK_REASON"),
            "pass": ok,
        }
        results.append(result)
        print(("PASS " if ok else "FAIL ") + name +
              f": mode={mode} pl={pl} reason={sel.get('PRK_REASON')}")

    os.makedirs(EVID, exist_ok=True)
    payload = {
        "reference": PIN,
        "scenarios": results,
        "passed": len(results) - failures,
        "failed": failures,
        "selector": "tools/select-modules.sh",
    }
    with open(os.path.join(EVID, "selector-regression.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(EVID, "selector-regression.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"Module selector regression\nreference: {PIN}\n")
        for r in results:
            fh.write(("PASS " if r["pass"] else "FAIL ") + r["name"] +
                     f": mode={r['actual_mode']} pl={r['actual_module']} "
                     f"reason={r['reason']}\n")
        fh.write(f"passed: {payload['passed']}\nfailed: {failures}\n")
    print(f"passed {payload['passed']}, failed {failures}")
    print(f"results: {os.path.join(EVID, 'selector-regression.json')}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
