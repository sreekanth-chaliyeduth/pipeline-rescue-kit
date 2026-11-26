#!/usr/bin/env python3
"""Regression checks for immutable library tag verification.

Builds disposable repositories. It never touches the real project tags.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m5_prepare_sources as m5  # noqa: E402


def run(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args], text=True,
                          capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)
    return proc.stdout.strip()


def write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def commit(repo, message):
    run(repo, "add", "-A")
    run(repo, "commit", "-m", message)
    return run(repo, "rev-parse", "HEAD")


def main():
    with tempfile.TemporaryDirectory() as repo:
        subprocess.run(["git", "init", "-b", "main", repo], check=True,
                       capture_output=True)
        run(repo, "config", "user.name", "test")
        run(repo, "config", "user.email", "test@example.invalid")

        trees = {}
        commits = {}
        for version in ("1.0.0", "1.1.0", "1.1.1"):
            write(repo, "jenkins-lib/vars/prGate.groovy",
                  f"// prGate {version}\n")
            commits[version] = commit(repo, "library " + version)
            trees[version] = run(repo, "rev-parse",
                                 f"{commits[version]}:jenkins-lib/vars")
            run(repo, "tag", "-a", "lib-v" + version, "-m", "library " + version,
                commits[version])

        original = {tag: run(repo, "rev-parse", tag)
                    for tag in ("lib-v1.0.0", "lib-v1.1.0", "lib-v1.1.1")}
        m5.ROOT = repo
        m5.RELEASE_TREES = {f"lib-v{v}": trees[v]
                            for v in ("1.0.0", "1.1.0", "1.1.1")}
        releases = m5.verify_release_tags()
        assert set(releases) == set(m5.RELEASE_TREES), releases
        assert {tag: run(repo, "rev-parse", tag) for tag in original} == original, \
            "verification moved a tag"
        print("PASS correct tags pass and tag refs are unchanged")

        run(repo, "tag", "-d", "lib-v1.0.0")
        try:
            m5.verify_release_tags()
        except RuntimeError as exc:
            assert "missing" in str(exc), exc
            print("PASS missing tag is rejected")
        else:
            raise AssertionError("missing tag was accepted")

        run(repo, "tag", "-a", "lib-v1.0.0", "-m", "restored",
            commits["1.0.0"])
        write(repo, "jenkins-lib/vars/prGate.groovy", "// changed\n")
        commit(repo, "wrong tree")
        run(repo, "tag", "-f", "lib-v1.0.0", "HEAD")
        try:
            m5.verify_release_tags()
        except RuntimeError as exc:
            assert "mismatch" in str(exc), exc
            print("PASS incorrect fingerprint is rejected")
        else:
            raise AssertionError("incorrect fingerprint was accepted")

    print("all library tag checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
