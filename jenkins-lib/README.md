# prGate shared library v1.1.1

`prGate` is a Jenkins global shared-library step that publishes JUnit results,
applies a project line-coverage gate, optionally applies a modified-lines
line-coverage gate and applies one static-analysis gate on new issues. It writes
a plain-language `prgate-summary.md` and archives it.

The step is application-neutral. The caller supplies report paths, module
names, labels and thresholds.

Use it with:

```groovy
@Library('prk@lib-v1.1.1') _
```

## Contract source

This document is derived from `vars/prGate.groovy` at the `lib-v1.1.1` release. If
the implementation and this contract disagree, the implementation is the
source of truth and the version needs a new release.

## Parameters and defaults

| Parameter | Type | Default | Behavior |
|---|---|---|---|
| `testResults` | String | `**/target/surefire-reports/*.xml` | JUnit XML glob passed to the Jenkins JUnit step. Tests are always evaluated, even when `enforce` is false. |
| `coverageReport` | String | `**/target/jacoco-ut/jacoco.xml` | JaCoCo XML glob passed to the Jenkins Coverage step. |
| `coverageParser` | String | `JACOCO` | Coverage parser name passed to `recordCoverage`. |
| `coverageThreshold` | double | `0.0` | Project line-coverage threshold in percent. Values greater than 0 apply a `LINE`/`PROJECT` gate when `enforce` is true. A value of 0 publishes coverage without a coverage gate. |
| `modifiedLinesThreshold` | double | `0.0` | OFF. Values greater than 0 apply a `LINE`/`MODIFIED_LINES` gate against the reference build selected by `referenceJob` when `enforce` is true. The project gate and the modified-lines gate are evaluated independently. A missing reference build, missing coverage data or a missing code delta is never a pass. |
| `coverageScm` | String or null | `null` | Optional substring of the repository key used to compute the modified-lines code delta and to select the application SCM for Warnings NG issue attribution. Set it when the build checks out more than one SCM, for example a pipeline library plus the application repository. |
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
  revision, build URL, enforcement mode, Maven exit, test counts, project
  coverage result and value, modified-lines coverage result and value when the
  gate is enabled, static-analysis result and counts, reference build and job,
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
- With `enforce: true` and `modifiedLinesThreshold > 0`, line coverage of the
  lines modified relative to the `referenceJob` reference build below the
  modified-lines threshold blocks. The project gate keeps running
  independently, and both values appear in the summary.
- A modified-lines gate with no reference build, no modified-lines value or no
  code delta is `FAIL` (or `NOT EVALUATED` when tests already failed). It is
  never reported as a pass and never guessed from project coverage.
- A change with no modified executable Java lines passes the modified-lines gate
  and the summary says `no modified lines`. This requires a reference build and
  a code delta computed without errors, so missing data is still a failure.
- When the build checks out more than one SCM (a pipeline library counts), set
  `coverageScm` to a substring of the application repository key so the code
  delta and the Warnings NG issue attribution use the application revision, not
  the library revision.
- A missing coverage report, or no line value, blocks when tests passed or were
  not the reason for stopping. If the test gate already failed and Maven
  stopped before JaCoCo wrote the report, coverage is `NOT EVALUATED`.
- With `enforce: false` or both thresholds `0`, coverage is published and not
  gated.

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
@Library('prk@lib-v1.0.0') _

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
                    modifiedLinesThreshold: 80.0,
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

Library releases are immutable annotated Git tags in the project repository.
Jenkins loads the library from this repository with `libraryPath: jenkins-lib`
and `includeInChangesets: false`, so the library is not attributed to the
application changes.

Each public tag contains the recorded library code. Verify with
`git rev-parse lib-v1.0.0:jenkins-lib/vars` against
`evidence/site/library-releases.json`. Commit IDs in that file refer to the
original private history; the code fingerprint is the check. The historical
commit IDs in the table below are provenance references, not public history.

| Release | Tag | Historical tag object | Historical library commit | Historical `jenkins-lib/vars` tree |
|---|---|---|---|---|
| 1.0.0 | `lib-v1.0.0` | private archive | `845a9063ecb4a2e4528ecc270f1738ebdf9264e0` | `fd6be673861bc2dc7a72bc417802024d4cc6c54e` |
| 1.1.0 | `lib-v1.1.0` | private archive | `0e4a7db838cc74ce9964add183a092a031056096` | `39403d5c9a1551dbdf203599fab84be8d8ede44f` |
| 1.1.1 | `lib-v1.1.1` | private archive | `a6e033c12651e5a09e13ec75e6f4eee006cc0e2d` | `3e4930c580eb742b90a4785139e2ed2e92d41e1c` |

The tree column is the Git tree of the `jenkins-lib/vars` subtree. The older
generated snapshot repository held only `vars/`, so its recorded root tree
(`07df720...` for 1.0.0, `03c6d296...` for 1.1.0) is the tree that contained
`vars/`, not the `vars/` subtree itself.

The preparation workflow never creates, moves or deletes a release tag. It only
verifies that every `lib-*` tag is recorded and that its `jenkins-lib/vars` tree
matches the recorded hash; a mismatch or an unrecorded tag refuses preparation.
Library changes require a new release version. Moving or recreating an existing
release tag is not supported.
