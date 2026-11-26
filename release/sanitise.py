#!/usr/bin/env python3
"""Repeatable verification for the curated public export.

The export was built from an explicit manifest and evidence closure, not by
copying and then sanitising the full private tree. This script is the repeatable
mechanism for that construction:

- every manifest entry has an approved action;
- no entry uses a redaction action;
- every exported file matches release/checksums.txt;
- the evidence tree contains exactly the files in release/evidence-closure.txt;
- with --source, copied and curated files are byte-identical to their source.

There are no redactions in this release. If a redaction is added later, it must
be recorded in the manifest and checksums before this script can pass.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_ACTIONS = {"copied", "modified", "regenerated-identical",
                   "curated-evidence", "generated"}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksums(path):
    entries = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            digest, rel = line.split("  ", 1)
            entries[rel] = digest
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="optional private source tree for byte comparison")
    args = ap.parse_args()

    manifest = json.load(open(os.path.join(ROOT, "release", "manifest.json"),
                              encoding="utf-8"))
    checksums = read_checksums(os.path.join(ROOT, "release", "checksums.txt"))
    errors = []
    redactions = 0

    for entry in manifest["files"]:
        path = entry["path"]
        action = entry["action"]
        if action not in ALLOWED_ACTIONS:
            errors.append(f"unapproved action {action}: {path}")
        if "redact" in action:
            redactions += 1
        full = os.path.join(ROOT, path)
        if not os.path.isfile(full):
            errors.append("missing exported file: " + path)
            continue
        if path in checksums and sha256(full) != checksums[path]:
            errors.append("checksum mismatch: " + path)
        if args.source and action in {"copied", "curated-evidence"}:
            source = os.path.join(args.source, path)
            if not os.path.isfile(source):
                errors.append("missing source file: " + path)
            elif sha256(full) != sha256(source):
                errors.append("source differs: " + path)

    closure = []
    for line in open(os.path.join(ROOT, "release", "evidence-closure.txt"),
                     encoding="utf-8"):
        if line.startswith("evidence/"):
            closure.append(line.split("\t", 1)[0])
    evidence = []
    for base, dirs, files in os.walk(os.path.join(ROOT, "evidence")):
        dirs.sort()
        for name in sorted(files):
            evidence.append(os.path.relpath(os.path.join(base, name), ROOT))
    if sorted(closure) != sorted(evidence):
        errors.append("evidence tree differs from release/evidence-closure.txt")

    if os.path.isdir(os.path.join(ROOT, ".git")):
        releases = json.load(open(os.path.join(ROOT, "evidence", "site",
                                               "library-releases.json"),
                                  encoding="utf-8"))
        for release in releases["releases"]:
            proc = subprocess.run(
                ["git", "-C", ROOT, "rev-parse",
                 f"{release['tag']}:jenkins-lib/vars"],
                text=True, capture_output=True)
            if proc.returncode != 0:
                errors.append("missing library tag: " + release["tag"])
            elif proc.stdout.strip() != release["vars_tree"]:
                errors.append("library fingerprint mismatch: " + release["tag"])

    if errors:
        for error in errors:
            print("FAIL " + error, file=sys.stderr)
        return 1
    print(f"PASS manifest entries: {len(manifest['files'])}")
    print(f"PASS redactions: {redactions}")
    print(f"PASS curated evidence files: {len(evidence)}")
    print("PASS checksums and evidence closure agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
