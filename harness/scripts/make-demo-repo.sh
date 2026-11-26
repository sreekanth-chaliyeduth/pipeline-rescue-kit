#!/usr/bin/env bash
# Build the local PetClinic demo bare repository used by the multibranch PR
# demonstration.
#
# Generated data only. The bare repository and the working clone live under
# evidence/pr-flow/work, which is ignored by Git and is never committed.
#
# The four branches are deterministic: fixed content, fixed author and fixed
# commit dates, so a clean rebuild produces the same SHAs and a second run
# changes nothing.
#
# Every branch carries examples/Jenkinsfile.multibranch from the project, and
# main keeps the pinned upstream commit as its direct ancestor.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
PIN=500158f732419217507c7656904b8e6aa1bcc0d6
WORK_ROOT="$ROOT/evidence/pr-flow/work"
SOURCE="$ROOT/evidence/M0D/work/petclinic"
WORK="$WORK_ROOT/petclinic-demo-src"
BARE="$WORK_ROOT/petclinic-demo.git"
JENKINSFILE_SRC="$ROOT/examples/Jenkinsfile.multibranch"
JENKINSFILE_PATH=examples/Jenkinsfile.multibranch
BASE=src/main/java/org/springframework/samples/petclinic
TEST=src/test/java/org/springframework/samples/petclinic
BRANCHES=(main feature/small-untested-change feature/pmd-violation feature/fixed
	feature/docs-only)
STAMP="2026-01-01T00:00:00 +0000"

export GIT_AUTHOR_DATE="$STAMP"
export GIT_COMMITTER_DATE="$STAMP"
export GIT_AUTHOR_NAME="PRK Demo"
export GIT_AUTHOR_EMAIL="demo@example.invalid"
export GIT_COMMITTER_NAME="PRK Demo"
export GIT_COMMITTER_EMAIL="demo@example.invalid"

log() {
	printf '%s\n' "$*"
}

git_work() {
	git -C "$WORK" "$@"
}

write_file() {
	local path="$1"
	mkdir -p "$(dirname "$WORK/$path")"
	cat > "$WORK/$path"
}

copy_file() {
	local src="$1" path="$2"
	mkdir -p "$(dirname "$WORK/$path")"
	cp "$src" "$WORK/$path"
}

write_untested_change() {
	write_file "$BASE/CoverageGap.java" <<'JAVA'
package org.springframework.samples.petclinic;

public class CoverageGap {

	public int adjustedFee(int base) {
		int fee = base * 2;
		int discount = 5;
		int total = fee - discount;
		int rounded = Math.max(total, 0);
		return rounded;
	}

}
JAVA
}

write_pmd_violation() {
	write_file "$BASE/StaticCheck.java" <<'JAVA'
package org.springframework.samples.petclinic;

public class StaticCheck {

	public int classify(int value) {
		if (value > 0) {
			if (value < 10) {
				return 1;
			}
		}
		return 0;
	}

}
JAVA
	# Cover every line of the violation so the modified-lines gate passes and
	# only the deliberate PMD finding blocks this branch.
	write_file "$TEST/StaticCheckTest.java" <<'JAVA'
package org.springframework.samples.petclinic;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class StaticCheckTest {

	@Test
	void classify() {
		StaticCheck check = new StaticCheck();
		assertEquals(1, check.classify(5));
		assertEquals(0, check.classify(10));
		assertEquals(0, check.classify(-1));
	}

}
JAVA
}

write_fixed_change() {
	write_file "$BASE/CoverageGap.java" <<'JAVA'
package org.springframework.samples.petclinic;

public class CoverageGap {

	public int adjustedFee(int base) {
		int fee = base * 2;
		int discount = 5;
		int total = fee - discount;
		int rounded = Math.max(total, 0);
		return rounded;
	}

}
JAVA
	write_file "$TEST/CoverageGapTest.java" <<'JAVA'
package org.springframework.samples.petclinic;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CoverageGapTest {

	@Test
	void adjustedFeeRoundsNegativeResultsToZero() {
		CoverageGap gap = new CoverageGap();
		assertEquals(15, gap.adjustedFee(10));
		assertEquals(0, gap.adjustedFee(1));
	}

}
JAVA
	write_file "$BASE/StaticCheck.java" <<'JAVA'
package org.springframework.samples.petclinic;

public class StaticCheck {

	public int classify(int value) {
		if (value > 0 && value < 10) {
			return 1;
		}
		return 0;
	}

}
JAVA
	write_file "$TEST/StaticCheckTest.java" <<'JAVA'
package org.springframework.samples.petclinic;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class StaticCheckTest {

	@Test
	void classify() {
		StaticCheck check = new StaticCheck();
		assertEquals(1, check.classify(5));
		assertEquals(0, check.classify(10));
		assertEquals(0, check.classify(-1));
	}

}
JAVA
}

write_docs_only_change() {
	write_file docs/pr-demo-note.md <<'MD'
# PR demo note

This branch changes documentation only. It adds no executable Java lines, so
the modified-lines coverage gate must report no modified lines instead of a
coverage percentage.
MD
}

has_branch() {
	git_work show-ref --verify --quiet "refs/heads/$1"
}

commit() {
	git_work add -A
	git_work commit --quiet -m "$1"
}

# A branch is current when it is exactly main plus one commit, carries the
# Jenkinsfile, and its scenario file is present.
feature_current() {
	local name="$1" file="$2"
	has_branch "$name" || return 1
	git_work cat-file -e "refs/heads/$name:$JENKINSFILE_PATH" 2>/dev/null || return 1
	git_work cat-file -e "refs/heads/$name:$file" 2>/dev/null || return 1
	[ "$(git_work rev-parse "$name^")" = "$(git_work rev-parse main)" ] || return 1
	[ "$(git_work rev-list --count "main..$name")" = "1" ] || return 1
}

layout_current() {
	has_branch main || return 1
	git_work cat-file -e "refs/heads/main:$JENKINSFILE_PATH" 2>/dev/null || return 1
	[ "$(git_work rev-parse main^)" = "$PIN" ] || return 1
	[ "$(git_work rev-list --count "$PIN..main")" = "1" ] || return 1
	[ "$(git_work rev-parse "main:$JENKINSFILE_PATH")" = \
		"$(git_work hash-object "$JENKINSFILE_SRC")" ] || return 1
	feature_current feature/small-untested-change "$BASE/CoverageGap.java" || return 1
	feature_current feature/pmd-violation "$BASE/StaticCheck.java" || return 1
	git_work cat-file -e "refs/heads/feature/pmd-violation:$TEST/StaticCheckTest.java" 2>/dev/null || return 1
	feature_current feature/fixed "$TEST/StaticCheckTest.java" || return 1
	feature_current feature/docs-only docs/pr-demo-note.md || return 1
}

build_repository() {
	log "rebuilding generated repository from $SOURCE"
	rm -rf "$WORK" "$BARE"
	mkdir -p "$WORK_ROOT"
	git clone --quiet --no-hardlinks "$SOURCE" "$WORK"

	log "creating main at the pinned revision plus the multibranch Jenkinsfile"
	git_work checkout --quiet -B main "$PIN"
	copy_file "$JENKINSFILE_SRC" "$JENKINSFILE_PATH"
	commit "demo: add the multibranch Jenkinsfile"

	log "creating feature/small-untested-change"
	git_work checkout --quiet -B feature/small-untested-change main
	write_untested_change
	commit "demo: add a small untested fee adjustment"

	log "creating feature/pmd-violation"
	git_work checkout --quiet -B feature/pmd-violation main
	write_pmd_violation
	commit "demo: add a nested if that PMD reports"

	log "creating feature/fixed"
	git_work checkout --quiet -B feature/fixed main
	write_fixed_change
	commit "demo: cover the new code and collapse the nested if"

	log "creating feature/docs-only"
	git_work checkout --quiet -B feature/docs-only main
	write_docs_only_change
	commit "demo: add a documentation-only note"
}

# Reuse the documented PetClinic source preparation when the pinned checkout is
# absent. The M0D checkout is the source of truth; nothing upstream is modified.
if [ ! -f "$JENKINSFILE_SRC" ]; then
	log "error: $JENKINSFILE_SRC is missing" >&2
	exit 1
fi
if [ ! -d "$SOURCE/.git" ]; then
	log "preparing pinned PetClinic source with m6_prepare_sources.py"
	python3 "$ROOT/harness/scripts/m6_prepare_sources.py" >/dev/null
fi
if [ ! -d "$SOURCE/.git" ]; then
	log "error: $SOURCE is missing after preparation" >&2
	exit 1
fi

mkdir -p "$WORK_ROOT"
if [ ! -d "$WORK/.git" ]; then
	log "cloning pinned PetClinic source into $WORK"
	git clone --quiet --no-hardlinks "$SOURCE" "$WORK"
fi
if ! git_work cat-file -e "$PIN^{commit}" 2>/dev/null; then
	log "error: pinned commit $PIN is missing from $WORK" >&2
	log "rerun the documented PetClinic source preparation" >&2
	exit 1
fi

if ! layout_current; then
	build_repository
else
	log "generated branches already current, leaving them unchanged"
fi

if [ ! -d "$BARE" ]; then
	log "initialising bare repository at $BARE"
	git init --quiet --bare --initial-branch=main "$BARE"
fi

# Pull the branches into the bare repository. This is a local fetch, not a push
# and not a force update: an unexpected divergence fails loudly instead of
# rewriting history.
for name in "${BRANCHES[@]}"; do
	git --git-dir="$BARE" fetch --quiet --no-tags "$WORK" \
		"refs/heads/$name:refs/heads/$name"
done
git --git-dir="$BARE" symbolic-ref HEAD refs/heads/main

git_work checkout --quiet main

python3 - "$BARE" "$PIN" "$WORK_ROOT/branches.generated.json" <<'PY'
import json
import subprocess
import sys

bare, pin, out = sys.argv[1], sys.argv[2], sys.argv[3]
purpose = {
    "main": "clean pinned PetClinic baseline plus the multibranch Jenkinsfile",
    "feature/small-untested-change": (
        "five newly introduced production lines with no test, used to show that "
        "project line coverage hides new uncovered lines"
    ),
    "feature/pmd-violation": (
        "minimal nested-if PMD violation for the static-analysis gate"
    ),
    "feature/fixed": (
        "corrected change that covers the new lines and removes the PMD "
        "violation, intended to pass the gates"
    ),
    "feature/docs-only": (
        "documentation-only change with no modified executable Java lines, "
        "used to prove the explicit no-modified-lines result"
    ),
}


def git(*args):
    return subprocess.run(["git", f"--git-dir={bare}", *args], text=True,
                          capture_output=True, check=True).stdout.strip()


branches = {}
for name in purpose:
    sha = git("rev-parse", f"refs/heads/{name}")
    files = [f for f in git("diff", "--name-only", f"main..{name}").splitlines() if f]
    branches[name] = {
        "sha": sha,
        "purpose": purpose[name],
        "changed_files": files,
        "diffstat": git("diff", "--stat", f"main..{name}"),
    }

record = {
    "application": "spring-petclinic",
    "pinned_revision": pin,
    "bare_repository": bare,
    "main_sha": branches["main"]["sha"],
    "jenkinsfile": "examples/Jenkinsfile.multibranch",
    "branches": branches,
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(record, fh, indent=2)
    fh.write("\n")
print(json.dumps(record, indent=2))
PY

log "branch refs in $BARE"
git --git-dir="$BARE" for-each-ref --format='%(refname:short) %(objectname)' refs/heads
