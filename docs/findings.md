# Technical findings and evidence index

These findings come from the compatibility investigation. They are experimental
results, not a production readiness claim. Raw logs remain private; the curated
files under `evidence/findings/` are sanitized.

| Finding | Subject | Key result | Detail |
|---|---|---|---|
| F1 | JDK 8 versus JDK 11 | 626 of 626 test identities matched, 0 outcome differences | `evidence/findings/F1-java-migration/` |
| F2 | JDK 17 assessment | The tested legacy JaCoCo and failure-ignore setup produced a successful build with 0 tests | `evidence/findings/F2-jdk17-assessment/` |
| F3 | GIB 4.8.1 selection | Leaf change selected 1 of 43 reactor entries; shared-module and root changes selected all 43 | `evidence/findings/F3-build-selection/` |
| F4 | BCE 1.2.3 safety | Default cache restored 43 reactor entries with 0 tests; strict reconciled run executed 626 tests and failed correctly | `evidence/findings/F4-build-cache/` |
| F5 | Maven Profiler 3.3 | Shaded artifact produced JSON for 43 projects; thin extension produced no report | `evidence/findings/F5-build-profiling/` |

## How to read a finding

Each directory contains:

- `summary.json`: machine-readable facts used by `site/data.json`.
- `excerpt.txt`: a short sanitized console excerpt.
- `README.md`: question, method, versions, result and limitations.

## Interpretation

- F1 is baseline parity, not application health. The same 221 tests failed or
  errored on both JDKs.
- F2 is about the tested tool configuration, not a general Java 17 defect.
- F3 is about selection scope, not measured build time. GIB was evaluated, not
  integrated into the v1.0 selector.
- F4 is about cache configuration and quality signals. BCE was evaluated and not
  selected for future core integration.
- F5 is a diagnostic result. Profiling does not imply that tests passed and does
  not identify a universal bottleneck.

## Reproduction limits

- One Intel Mac host, one Docker VM and one benchmark application.
- Train-Ticket has a predominantly star dependency graph and 221 existing failing
  or erroring tests.
- The Gate 3A Jenkins jobs and raw logs are retained as private experimental
  evidence. The sanitized Jenkinsfiles document path substitutions and were not
  rerun.
