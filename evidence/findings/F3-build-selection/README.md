# F3: established build-selection alternative

## Question

Would an established change-based selector select a safe module set for a
Train-Ticket leaf change without relying on unverified cached artifacts?

## Tool

Gitflow Incremental Builder 4.8.1 on JDK 11 and Maven 3.9.16. GIB was evaluated
as an alternative. It was not integrated into the v1.0 selector.

## Method and result

An isolated Maven repository was prepared from the exact `gib-base` commit on
top of Train-Ticket `313886e`. The leaf fixture changed one
`ts-order-service` controller file. The optimized build ran offline with GIB
and `gib.referenceBranch=refs/heads/gib-base`.

| Fixture | Selected | Tests | Outcome |
|---|---:|---:|---|
| Leaf service change | 1 of 43 | 51 | 3 failures, 22 errors, matching the reference |
| Shared `ts-common` change | 43 of 43 | full reactor | conservative over-selection |
| Root POM change | 43 of 43 | full reactor | expected |

The 51 leaf test identities matched the S0 subset exactly. Shared-module and
root changes selected the full reactor in the tested configuration, which is
safe but not minimal.

## Provenance

The original shared-cache run could not be attributed to the base commit. A
corrective isolated repository was built from the base commit, and the offline
run used only that repository. The shared cache was not used for reactor
artifacts in the corrective run.

## Limitations

- Selection scope is not a measured build-time improvement.
- The reason GIB marks the root aggregator as changed for a shared-module
  fixture remains incompletely explained; the result is conservative, not a
  demonstrated omission.
- One application with a predominantly star dependency graph.

## Evidence

Public in this bundle: `summary.json`, `excerpt.txt`.

Private source references, not part of the publication bundle:

- `spike/GATE2_VALIDATION.md`, section E2
- `spike/GATE3A.md`, section J1
- Gate 3A build `gib-a-2` console and Maven logs

Sanitized reproduction, not rerun:

- `harness/pipelines/v11-experimental/sanitized/gib-fixture-a.Jenkinsfile`

Command with placeholders:

```sh
mvn -B -o -T 2 -fae -Dmaven.test.failure.ignore=true \
  -Dmaven.repo.local=<isolated-repo> \
  -Dgib.referenceBranch=refs/heads/<base-branch> \
  -Dgib.logImpactedTo=<impacted-file> verify
```
