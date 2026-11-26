#!/usr/bin/env python3
"""Create disposable M5 Train-Ticket branches for the prGate demonstrations."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.join(ROOT, "evidence", "M5", "work", "train-ticket")
SOURCE = os.path.join(ROOT, "evidence", "M2", "work", "train-ticket")
UPSTREAM = "https://github.com/FudanSELab/train-ticket.git"
PIN = "313886e99befb94be6cd45f085c98e0019f59829"
ASSURANCE = "ts-assurance-service"
MAIN = os.path.join(ASSURANCE, "src/main/java/assurance")
TEST = os.path.join(ASSURANCE, "src/test/java/assurance")

# Immutable library release tags live in the project repository. Each tag must
# resolve to the recorded tree for jenkins-lib/vars. A tag whose content does
# not match, or an unrecorded lib-* tag, refuses preparation.
RELEASE_TREES = {
    "lib-v1.0.0": "fd6be673861bc2dc7a72bc417802024d4cc6c54e",
    "lib-v1.1.0": "39403d5c9a1551dbdf203599fab84be8d8ede44f",
    "lib-v1.1.1": "3e4930c580eb742b90a4785139e2ed2e92d41e1c",
}


def run(cmd):
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {proc.stdout}{proc.stderr}")
    return proc.stdout.strip()


def git(*args):
    return run(["git", "-C", REPO, *args])


def branch(name):
    git("checkout", "-B", name, PIN)


def verify_release_tags():
    """Verify the immutable project release tags and their recorded content.

    Preparation never creates or moves a library tag. It only checks that every
    lib-* tag present in the project is recorded and that each recorded tag
    resolves to the expected jenkins-lib/vars tree.
    """
    tags = set(run(["git", "-C", ROOT, "tag", "--list", "lib-v*"]).splitlines())
    unrecorded = sorted(tags - set(RELEASE_TREES))
    if unrecorded:
        raise RuntimeError(
            "unrecorded library release tag(s): " + ", ".join(unrecorded))
    releases = {}
    for tag, expected in sorted(RELEASE_TREES.items()):
        if tag not in tags:
            raise RuntimeError(f"library release tag missing: {tag}")
        actual = run(["git", "-C", ROOT, "rev-parse", f"{tag}:jenkins-lib/vars"])
        if actual != expected:
            raise RuntimeError(
                f"library release content mismatch for {tag}\n"
                f"  recorded: {expected}\n"
                f"  actual:   {actual}")
        releases[tag] = run(["git", "-C", ROOT, "rev-parse", f"{tag}^{{commit}}"])
    return releases


def write(path, text):
    full = os.path.join(REPO, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def commit(message):
    git("add", "-A")
    git("commit", "-m", message)


def coverage_class():
    lines = ["package assurance;", "", "public class M5CoverageFixture {", "", "    public int checksum() {", "        int total = 0;"]
    for value in range(1, 51):
        lines.append(f"        total += {value};")
    lines += ["        return total;", "    }", "}", ""]
    return "\n".join(lines)


COVERAGE_TEST = """package assurance;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class M5CoverageFixtureTest {
    @Test
    void checksum() {
        assertEquals(1275, new M5CoverageFixture().checksum());
    }
}
"""

STATIC_CLASS = """package assurance;

public class M5StaticFixture {
    private int unusedValue = 42;

    public String label() {
        return "m5-static";
    }
}
"""

FAILING_TEST = """package assurance;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.fail;

class M5FailingGateTest {
    @Test
    void controlledFailure() {
        fail("M5 controlled test failure");
    }
}
"""


def main():
    os.makedirs(os.path.dirname(REPO), exist_ok=True)
    if not os.path.isdir(SOURCE):
        os.makedirs(os.path.dirname(SOURCE), exist_ok=True)
        run(["git", "clone", UPSTREAM, SOURCE])
        run(["git", "-C", SOURCE, "checkout", PIN])
    if not os.path.isdir(os.path.join(REPO, ".git")):
        run(["git", "clone", "--no-hardlinks", SOURCE, REPO])

    # Leave an existing M5 clone's branches untouched so recorded SHAs remain stable.
    if run(["git", "-C", REPO, "branch", "--list", "m5-green"]) == "":
        branch("m5-base")
        branch("m5-green")

        branch("m5-coverage-red")
        write(os.path.join(MAIN, "M5CoverageFixture.java"), coverage_class())
        commit("M5 scenario: untested coverage fixture")

        branch("m5-static-red")
        write(os.path.join(MAIN, "M5StaticFixture.java"), STATIC_CLASS)
        commit("M5 scenario: new static-analysis issue")

        branch("m5-test-red")
        write(os.path.join(TEST, "M5FailingGateTest.java"), FAILING_TEST)
        commit("M5 scenario: controlled test failure")

        branch("m5-fixed")
        write(os.path.join(MAIN, "M5CoverageFixture.java"), coverage_class())
        write(os.path.join(TEST, "M5CoverageFixtureTest.java"), COVERAGE_TEST)
        commit("M5 fixed: cover the new fixture")

    branches = {}
    for name in ("m5-base", "m5-green", "m5-coverage-red", "m5-static-red",
                 "m5-test-red", "m5-fixed"):
        branches[name] = git("rev-parse", name)
    try:
        releases = verify_release_tags()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    obj = {
        "reference": PIN,
        "scope": ASSURANCE,
        "library_releases": releases,
        "branches": branches,
        "files": {
            "coverage_red": os.path.join(MAIN, "M5CoverageFixture.java"),
            "static_red": os.path.join(MAIN, "M5StaticFixture.java"),
            "test_red": os.path.join(TEST, "M5FailingGateTest.java"),
            "fixed_main": os.path.join(MAIN, "M5CoverageFixture.java"),
            "fixed_test": os.path.join(TEST, "M5CoverageFixtureTest.java"),
        },
    }
    out = os.path.join(ROOT, "evidence", "M5", "work", "branches.generated.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")
    print(json.dumps(branches, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
