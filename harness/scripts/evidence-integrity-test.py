#!/usr/bin/env python3
"""Validate the curated public evidence against the release checksums.

This is the public-export integrity suite. It does not read the private
historical evidence archive. It checks:

- every path in release/checksums.txt exists and has the recorded SHA-256;
- every file under evidence/ is listed in the checksum file;
- every checksum path is listed in release/manifest.json;
- a tampered file is detected in a temporary fixture.
"""
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKSUMS = os.path.join(ROOT, "release", "checksums.txt")
MANIFEST = os.path.join(ROOT, "release", "manifest.json")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksums(path):
    entries = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise ValueError(f"bad checksum line {lineno}: {line!r}")
            entries.append((parts[0], parts[1]))
    return entries


def verify(root=ROOT):
    errors = []
    checksums = read_checksums(os.path.join(root, "release", "checksums.txt"))
    listed = set()
    for digest, rel in checksums:
        listed.add(rel)
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            errors.append("missing file: " + rel)
            continue
        actual = sha256(full)
        if actual != digest:
            errors.append("checksum mismatch: " + rel)
    evidence = {
        os.path.relpath(path, root)
        for path in glob.glob(os.path.join(root, "evidence", "**", "*"), recursive=True)
        if os.path.isfile(path)
    }
    for rel in sorted(evidence - listed):
        errors.append("evidence file not in checksums: " + rel)
    manifest = json.load(open(os.path.join(root, "release", "manifest.json"), encoding="utf-8"))
    manifest_paths = {entry["path"] for entry in manifest["files"]}
    for rel in sorted(listed - manifest_paths):
        errors.append("checksum path not in manifest: " + rel)
    for rel in sorted(manifest_paths - listed):
        if rel != "release/checksums.txt":
            errors.append("manifest path not in checksums: " + rel)
    return errors


def main():
    errors = verify(ROOT)
    if errors:
        for error in errors:
            print("FAIL " + error)
        return 1
    print("PASS checksums match every exported file")
    print("PASS every evidence file is in the checksum manifest")
    print("PASS every checksum path is in the release manifest")

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "release"))
        shutil.copy2(CHECKSUMS, os.path.join(tmp, "release", "checksums.txt"))
        shutil.copy2(MANIFEST, os.path.join(tmp, "release", "manifest.json"))
        sample = "README.md"
        shutil.copy2(os.path.join(ROOT, sample), os.path.join(tmp, sample))
        with open(os.path.join(tmp, sample), "a", encoding="utf-8") as fh:
            fh.write("\ntampered\n")
        tamper_errors = verify(tmp)
        if not any("checksum mismatch: " + sample == error for error in tamper_errors):
            print("FAIL tamper detection did not report " + sample)
            return 1
        print("PASS tamper detection rejects a modified file")
    print("all public evidence integrity checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
