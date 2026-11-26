#!/usr/bin/env python3
"""Route generated outputs away from tracked historical evidence.

Historical milestone folders under evidence/M*/ are read-only inputs. Current
outputs are written under the ignored evidence/M*/work/generated/ directory.
Raw logs and existing work paths are left unchanged.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HISTORICAL = re.compile(r"^(?:.*/)?evidence/(M[0-9][^/]*)/(.+)$")
IGNORED_PREFIXES = ("raw/", "work/", "verify/")


def _relative(path):
    if os.path.isabs(path):
        try:
            return os.path.relpath(path, ROOT)
        except ValueError:
            return path
    return path


def generated_dir(history_dir):
    """Return the ignored generated directory for a milestone evidence dir."""
    return os.path.join(history_dir, "work", "generated")


def generated_path(path):
    """Return an ignored generated path when path points at historical evidence."""
    rel = _relative(path)
    match = HISTORICAL.match(rel)
    if not match:
        return path
    milestone, rest = match.group(1), match.group(2)
    if rest.startswith(IGNORED_PREFIXES):
        return path
    return os.path.join(ROOT, "evidence", milestone, "work", "generated", rest)


def evidence_read(path):
    """Prefer a generated current file, falling back to historical evidence."""
    generated = generated_path(path)
    if generated != path and os.path.exists(generated):
        return generated
    return path
