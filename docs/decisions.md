# Decision record

This public record summarises the technical decisions behind the recorded
results. Private planning, review coordination and historical working notes are
not part of the public export.

## D1: Withdraw the M3 same-workload speed-up headline

Date: 24 November 2026. Status: accepted.

The original M3 comparison ran a baseline and a rescued pipeline over the
Train-Ticket reactor: 43 reactor entries and 626 tests on a warm cache, three
runs per variant. The baseline installed all 43 entries and then ran a separate
test pass. The rescued `verify` stopped packaging a module when its tests failed,
so only 11 of 43 entries reached packaging. The two runs did not do equal work.

A packaging control restored the packaging work with
`mvn -B -T 2 -fae -Dmaven.test.failure.ignore=true verify`, three runs.

| Variant | Runs, Jenkins total | Median | Range |
|---|---|---:|---|
| Baseline | 577.1, 589.0, 736.2 s | 589.0 s | 577.1 to 736.2 s |
| Rescued, historical | 359.7, 311.2, 388.8 s | 359.7 s | 311.2 to 388.8 s |
| Packaging control | 421.6, 641.7, 514.6 s | 514.6 s | 421.6 to 641.7 s |

The control median is 12.6% below the baseline median, not the 38.9% originally
claimed, and the two ranges overlap between 577.1 s and 641.7 s. The 38.9%
same-workload claim is withdrawn. No same-workload speed-up is claimed.

The public material leads with the fail-closed selective build: 3 of 43 reactor
entries, 38.22 s median, 51 tests. That is a different workload from the
full-reactor comparison.

Evidence: `evidence/M3/results.json`, `evidence/m3-control/results.json`.

## D2: Immutable project-repository library releases

Date: 24 November 2026. Status: accepted.

Library releases are immutable annotated tags in the project repository:
`lib-v1.0.0`, `lib-v1.1.0` and `lib-v1.1.1`. Jenkins loads the library from the
project repository with `libraryPath: jenkins-lib` and
`includeInChangesets: false`. Preparation scripts only verify release tags;
they never create, move or delete them. Library changes require a new release
version, never a retag.

Each public tag contains the recorded library code. Verify with `git rev-parse lib-v1.0.0:jenkins-lib/vars` against `evidence/site/library-releases.json`. Commit IDs in that file refer to the original private history; the code fingerprint is the check.

Evidence: `evidence/task-1.3a/immutable-tag.json`,
`evidence/site/library-releases.json`.

## D3: Application SCM attribution and no-modified-lines handling

Date: 24 November 2026. Status: accepted.

Builds check out both the application repository and the pipeline library.
Warnings NG and the Coverage plugin need an explicit SCM selector when a
reference build is used. `prGate` exposes `coverageScm` and passes it to both
`recordCoverage` and `recordIssues`.

The modified-lines gate distinguishes three outcomes:

- A reference build exists, the code delta is clean and no executable Java line
  changed: PASS, reported as no modified lines.
- Modified executable lines exist but coverage data is unavailable: FAIL.
- A code delta error or a missing reference: FAIL.

Evidence: `evidence/review-fixes/jenkins-runs.json`,
`evidence/v4/task-1.2/selector-regression/selector-regression.json`.

## D4: Recorded screenshots in the site data

Date: 24 November 2026. Status: accepted.

Five screenshots are captured from the local Jenkins at recorded build numbers:
the multibranch branch list, project coverage on the untested-change build,
modified-lines coverage on the same build, the PMD package summary on the
PMD-only build, and the Train-Ticket selector decision.

Their metadata lives in `evidence/site/images.json`, a generator input. The
generator rejects a build number that does not match the recorded scenario, a
missing or 200 KB or larger asset, an unknown section, a missing variant and an
unloaded source.

The original Task 3.1 data hash is preserved for provenance:
`7ee38b4ecfccfe4ad116044204d2f5a7aa02cd5dcdb164a6df0c6c35790f1d05`.
Adding the screenshot records changed the generated data hash to
`cf5c4fd542499176958f293bff2852370e8ade4cef6a13a46486132cf1900678`.
No measurement changed.

Evidence: `evidence/site/images.json`, `site/data.json`.

## D5: Preserve the validated site checkpoint

Date: 25 November 2026. Status: recorded.

The validated site checkpoint was retained while editorial and reader
comprehension work continued separately. The recorded measurements, the visual
design and the `ts-common` finding were not changed. The 42 reactor entries,
42 module paths and 41 display labels are correct; the duplicate Maven display
label is not deduplicated and 42 is not changed to 43.

Evidence: `evidence/M4/scenarios.json`,
`evidence/M4/raw/scenarios/ts-common.log`.

## D6: Factual correction for the ts-common limitation

Date: 25 November 2026. Status: accepted.

The historical limitation said the aggregator root was not in the ts-common
reactor. That statement was wrong. The recorded 42-entry list starts with
`ts-service-cluster`. The historical limitation text and its source evidence are
preserved; the site shows the original text with a visible correction.

The independent upstream Train-Ticket run records 221 failed or errored tests at
the pinned commit, while the kit baseline builds record 220. The site shows both
values and records the one-test difference.

Evidence: `evidence/M4/scenarios.json`,
`evidence/M4/raw/scenarios/ts-common.log`,
`evidence/M3/test-inventory.json`.

## D7: Final Lighthouse acceptance criteria

Date: 25 November 2026. Status: accepted.

Final acceptance applies to every individual Lighthouse run.

Mobile:

- Performance at least 95.
- Accessibility 100.
- Total Blocking Time at most 200 ms.
- Largest Contentful Paint at most 2500 ms.
- Cumulative Layout Shift 0.000.

Desktop:

- Performance at least 99.
- Accessibility 100.
- Cumulative Layout Shift 0.000.

Desktop TBT and LCP are reported for completeness but are not additional
desktop gates. No source optimisation is performed to convert a result into a
pass.
