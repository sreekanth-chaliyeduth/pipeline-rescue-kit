# prGate shared library v1.0.0

`prGate` is a Jenkins global shared-library step that publishes JUnit results,
applies a project line-coverage gate and applies one static-analysis gate on
new issues. It writes a plain-language `prgate-summary.md` and archives it.

The step is application-neutral. The caller supplies report paths, module
names, labels and thresholds.

Use it with:

```groovy
@Library('prk@v1.0.0') _
```

## Contract source

This document is derived from `vars/prGate.groovy` at the `v1.0.0` snapshot. If
the implementation and this contract disagree, the implementation is the
source of truth and the version needs a new release.

## Parameters and defaults

| Parameter | Type | Default | Behavior |
|---|---|---|---|
| `testResults` | String | `**/target/surefire-reports/*.xml` | JUnit XML glob passed to the Jenkins JUnit step. Tests are always evaluated, even when `enforce` is false. |
| `coverageReport` | String | `**/target/jacoco-ut/jacoco.xml` | JaCoCo XML glob passed to the Jenkins Coverage step. |
| `coverageParser` | String | `JACOCO` | Coverage parser name passed to `recordCoverage`. |
| `coverageThreshold` | double | `0.0` | Project line-coverage threshold in percent. Values greater than 0 apply a `LINE`/`PROJECT` gate when `enforce` is true. A value of 0 publishes coverage without a coverage gate. |
| `staticAnalysisTool` | String | `pmd` | Static-analysis parser. Supported values are `pmd`, `checkstyle` and `spotbugs`. |
| `staticAnalysisReport` | String | `**/target/pmd.xml` | Static-analysis report path or glob. The shell fallback accepts only letters, digits, `.`, `_`, `*`, `/` and `-`. |
| `staticNewIssueThreshold` | int | `1` | Warnings NG NEW gate threshold. The gate fails when the number of new issues is greater than or equal to the threshold. `1` means any new issue blocks. Values below 1 are invalid when `enforce` is true. |
| `enforce` | boolean | `true` | Applies the coverage and static gates and fails the build on a blocking result. `false` observes and publishes without coverage or static gating. |
| `summaryFile` | String | `prgate-summary.md` | Workspace-relative summary file, archived by the step. |
| `mavenExit` | Integer or null | `null` | Optional Maven exit code. A non-null, non-zero value is recorded as a failure. |
| `scopeLabel` | String | `unspecified` | Label shown in the summary. |
| `revision` | String | `unknown` | Revision label shown in the summary. |
| `referenceCommit` | String or null | `null` | Clean reference commit label shown in the summary. It does not select the Warnings NG reference build. |
| `referenceJob` | String or null | `null` | When set, calls `discoverReferenceBuild(referenceJob: ..., requiredResult: 'SUCCESS')`. The selected reference build must belong to that job or the static gate fails. When not set, the standard `discoverReferenceBuild()` path is used. |

## Expected report inputs

- JUnit XML from Surefire or an equivalent producer.
- JaCoCo XML containing line counters. The default parser is `JACOCO`.
- PMD XML by default. Checkstyle or SpotBugs XML when selected through
  `staticAnalysisTool`.
- All paths are workspace-relative. The static pattern is validated before the
  shell glob fallback.

The Jenkins JaCoCo plugin is not required by `prGate`. The Coverage plugin
reads the JaCoCo XML directly.

## Outputs

- JUnit results attached to the build.
- Coverage action with ID `coverage`, visible at `coverage/`.
- Static-analysis action with ID `pmd`, `checkstyle` or `spotbugs`, visible at
  the matching URL.
- `prgate-summary.md` written to the workspace and archived. It records scope,
  revision, build URL, enforcement mode, Maven exit, test counts, coverage
  result and value, static-analysis result and counts, reference build and job,
  notes and the final decision.
- Build result `FAILURE` when `enforce` is true and any gate fails. The step
  calls `error(...)` after writing and archiving the summary.

JUnit can mark a build `UNSTABLE` for test failures. `prGate` treats any test
failure as a blocking failure when `enforce` is true and then raises the result
to `FAILURE`.

## Failure behavior

### Unit tests

- A test failure blocks.
- Zero reported tests blocks. An empty test inventory is never treated as a
  pass.
- Skipped tests are reported but do not by themselves fail the gate.

### Coverage

- With `enforce: true` and `coverageThreshold > 0`, project line coverage below
  the threshold blocks.
- A missing coverage report, or no line value, blocks when tests passed or were
  not the reason for stopping. If the test gate already failed and Maven
  stopped before JaCoCo wrote the report, coverage is `NOT EVALUATED`.
- With `enforce: false` or `coverageThreshold: 0`, coverage is published and
  not gated.

### Static analysis

- With `enforce: true`, the NEW gate fails when new issues reach
  `staticNewIssueThreshold`.
- Inherited issues remain visible and do not block.
- A missing static report blocks unless the test gate already failed and Maven
  stopped before the report was written; in that case it is `NOT EVALUATED`.
- When `referenceJob` is set, the selected reference must be a successful build
  of that job. A missing baseline or a fallback build from the wrong job is a
  static failure.
- `staticNewIssueThreshold: 0` is invalid when `enforce: true`; the step throws
  a configuration error.

### Maven exit

A non-null, non-zero `mavenExit` adds a failure. Set it when the caller wants
Maven exit status reflected in the gate summary even after a failed build step.

## `ENFORCE=false` observation behavior

`enforce: false` is an observation mode:

- JUnit results are still published and test failures still appear in the
  summary and gate decision.
- Coverage and static analysis are published without quality gates.
- The decision is `OBSERVE` when failures are recorded, otherwise `PASS`.
- `prGate` does not call `error(...)` in observation mode. JUnit may still mark
  the build `UNSTABLE`, and Maven may already have failed.
- Observation mode does not seed or overwrite a dedicated baseline job. Use a
  separate baseline job pinned to the clean revision for the Warnings NG
  reference.

## Required Jenkins plugins and pinned versions

`prGate` calls steps from these plugins:

| Plugin | Pinned version |
|---|---|
| `workflow-aggregator` | `608.v67378e9d3db_1` |
| `junit` | `1458.1460.vd53b_087eeb_2c` |
| `coverage` | `4.3620.v407ef5b_88f0d` |
| `warnings-ng` | `13.10365.v85cd7a_c8110b_` |

`warnings-ng` needs `forensics-api`, which the harness receives as a dependency
and which is active at `4.1977.v0f55b_7ee93a_4`.

The harness also pins `git-forensics` `4.2557.v2c7f200dfc72`, `jacoco` `3.3.7`
and `pipeline-stage-view` `2.41`. `prGate` calls neither the JaCoCo plugin nor
the stage-view plugin. `git-forensics` supplies blame data, which `prGate`
disables with `skipBlames: true`.

## Trusted global library requirement

`prGate` must be configured as a global shared library. It runs trusted code
and uses APIs outside the normal job sandbox, including
`currentBuild.rawBuild` and plugin classes. Only Jenkins administrators should
be able to change the library or the jobs that load it. Do not load it from an
untrusted branch.

## Complete caller example

The baseline job must exist and must be pinned to the clean revision if
`referenceJob` is used. Omit `referenceJob` to use the standard same-job
reference discovery.

```groovy
@Library('prk@v1.0.0') _

pipeline {
    agent { label 'linux && java17' }

    stages {
        stage('Build and test') {
            steps {
                script {
                    env.MAVEN_EXIT = sh(
                        returnStatus: true,
                        script: '''
                            mvn -B clean verify \
                                org.apache.maven.plugins:maven-pmd-plugin:3.28.0:pmd
                        '''
                    )
                }
            }
        }

        stage('prGate') {
            steps {
                prGate(
                    testResults: 'target/surefire-reports/*.xml',
                    coverageReport: 'target/site/jacoco/jacoco.xml',
                    coverageParser: 'JACOCO',
                    coverageThreshold: 80.0,
                    staticAnalysisTool: 'pmd',
                    staticAnalysisReport: 'target/pmd.xml',
                    staticNewIssueThreshold: 1,
                    enforce: true,
                    mavenExit: env.MAVEN_EXIT as int,
                    scopeLabel: 'example-service',
                    revision: 'local-example',
                    summaryFile: 'prgate-summary.md'
                )
            }
        }
    }
}
```

## Release identity and versioning

The generated local library snapshot is tagged `v1.0.0`. The tag is immutable.

| Item | Value |
|---|---|
| Tag | `v1.0.0` |
| Commit | `802d69bda71b8abe687ed06056940a30a107a7ce` |
| Tree | `07df720bf8d9811513087fc15c10ddea644f5ca7` |
| Snapshot content | `vars/prGate.groovy` only |

The snapshot contains `vars/` only. This README is product documentation in the
main repository and is not part of the tagged snapshot. The tree hash covers
`vars/prGate.groovy` alone.

The commit SHA identifies the generated local snapshot used by the validated
builds. A fresh clone creates a new snapshot commit with the same tree hash.

The preparation workflow compares the exact intended release tree with the tag
tree. Unchanged content reuses the existing tag and creates no commit. Changed
content fails with `library changed; bump the version` and leaves the tag in
place. Moving or deleting an existing version tag is not supported. The tag is
local to the generated snapshot repository and is not a tag in the main project
repository.
