#!/usr/bin/env python3
"""Create disposable M6 PetClinic branches and record the prGate checksum."""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.join(ROOT, "evidence", "M6", "work", "petclinic")
SOURCE = os.path.join(ROOT, "evidence", "M0D", "work", "petclinic")
UPSTREAM = "https://github.com/spring-projects/spring-petclinic.git"
LIBRARY = os.path.join(ROOT, "jenkins-lib", "vars", "prGate.groovy")
PIN = "500158f732419217507c7656904b8e6aa1bcc0d6"
BASE = os.path.join("src", "main", "java", "org", "springframework", "samples", "petclinic")
TEST = os.path.join("src", "test", "java", "org", "springframework", "samples", "petclinic")


def run(cmd):
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {proc.stdout}{proc.stderr}")
    return proc.stdout.strip()


def run_raw(cmd):
    """Run and return stdout exactly, preserving the trailing newline."""
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {proc.stdout}{proc.stderr}")
    return proc.stdout


def git(*args):
    return run(["git", "-C", REPO, *args])


def branch(name):
    git("checkout", "-B", name, PIN)


def write(path, text):
    full = os.path.join(REPO, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def commit(message):
    git("add", "-A")
    git("commit", "-m", message)


def has_branch(name):
    return run(["git", "-C", REPO, "branch", "--list", name]) != ""


def coverage_class():
    lines = [
        "package org.springframework.samples.petclinic;",
        "",
        "public class M6CoverageFixture {",
        "",
        "\tpublic int checksum() {",
        "\t\tint total = 0;",
    ]
    for value in range(1, 51):
        lines.append(f"\t\ttotal += {value};")
    lines += ["\t\treturn total;", "\t}", "", "}", ""]
    return "\n".join(lines)


COVERAGE_TEST = """package org.springframework.samples.petclinic;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class M6CoverageFixtureTest {

\t@Test
\tvoid checksum() {
\t\tassertEquals(1275, new M6CoverageFixture().checksum());
\t}

}
"""

STATIC_CLASS = """package org.springframework.samples.petclinic;

public class M6StaticFixture {

\tpublic int classify(int value) {
\t\tif (value > 0) {
\t\t\tif (value < 10) {
\t\t\t\treturn 1;
\t\t\t}
\t\t}
\t\treturn 0;
\t}

}
"""

STATIC_FIXED_CLASS = """package org.springframework.samples.petclinic;

public class M6StaticFixture {

\tpublic int classify(int value) {
\t\tif (value > 0 && value < 10) {
\t\t\treturn 1;
\t\t}
\t\treturn 0;
\t}

}
"""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    os.makedirs(os.path.dirname(REPO), exist_ok=True)
    if not os.path.isdir(SOURCE):
        os.makedirs(os.path.dirname(SOURCE), exist_ok=True)
        run(["git", "clone", UPSTREAM, SOURCE])
        run(["git", "-C", SOURCE, "checkout", PIN])
    if not os.path.isdir(os.path.join(REPO, ".git")):
        run(["git", "clone", "--no-hardlinks", SOURCE, REPO])

    if not has_branch("m6-green"):
        branch("m6-green")

    if not has_branch("m6-coverage-red"):
        branch("m6-coverage-red")
        write(os.path.join(BASE, "M6CoverageFixture.java"), coverage_class())
        commit("M6 scenario: untested coverage fixture")

    if not has_branch("m6-static-red"):
        branch("m6-static-red")
        write(os.path.join(BASE, "M6StaticFixture.java"), STATIC_CLASS)
        commit("M6 scenario: new nested-if PMD issue")

    if not has_branch("m6-fixed"):
        branch("m6-fixed")
        write(os.path.join(BASE, "M6CoverageFixture.java"), coverage_class())
        write(os.path.join(TEST, "M6CoverageFixtureTest.java"), COVERAGE_TEST)
        write(os.path.join(BASE, "M6StaticFixture.java"), STATIC_FIXED_CLASS)
        commit("M6 fixed: cover the fixture and collapse the nested if")

    branches = {}
    for name in ("m6-green", "m6-coverage-red", "m6-static-red", "m6-fixed"):
        branches[name] = git("rev-parse", name)

    library_sha = sha256(LIBRARY)
    tags = run(["git", "-C", ROOT, "tag", "--sort=-v:refname",
                "--list", "lib-v*"]).splitlines()
    if not tags:
        raise RuntimeError("no library release tag found")
    latest_tag = tags[0]
    tag_content = run_raw(["git", "-C", ROOT, "show",
                           f"{latest_tag}:jenkins-lib/vars/prGate.groovy"])
    tag_sha = hashlib.sha256(tag_content.encode("utf-8")).hexdigest()
    obj = {
        "reference": PIN,
        "application": "spring-petclinic",
        "jdk": "17",
        "library_sha256": library_sha,
        "library_tag": latest_tag,
        "library_tag_sha256": tag_sha,
        "library_tag_matches": tag_sha == library_sha,
        "branches": branches,
        "files": {
            "coverage_red": os.path.join(BASE, "M6CoverageFixture.java"),
            "static_red": os.path.join(BASE, "M6StaticFixture.java"),
            "fixed_main": os.path.join(BASE, "M6CoverageFixture.java"),
            "fixed_test": os.path.join(TEST, "M6CoverageFixtureTest.java"),
        },
    }
    out = os.path.join(ROOT, "evidence", "M6", "work", "branches.generated.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")
    print(json.dumps(obj, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
