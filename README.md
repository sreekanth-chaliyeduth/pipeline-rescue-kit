# Pipeline Rescue Kit

A reusable Jenkins merge-gate library and build-acceleration kit, demonstrated
on two applications:

- FudanSELab Train-Ticket, Java 8, a 43-entry Maven reactor (42 modules plus the aggregator).
- Spring PetClinic, Java 17, one Maven module.

The kit replaces a slow, report-only Jenkins pipeline with one shared quality
gate library, a reproducible Jenkins-as-code stack and a fail-closed selective
build. It uses maintained Jenkins plugins and does not require a new platform,
database or dashboard.

Author: [Sreekanth C](https://www.linkedin.com/in/sreekanth-chaliyeduth/)

### What I built

- **prGate**: a Jenkins Shared Library step, written in Groovy, that turns test, coverage and code-quality reports into a clear pass or block decision for each pull request. `jenkins-lib/vars/prGate.groovy`
- **Module selector**: a shell script that reads which files a change touched and tells Maven which modules to build. Maven adds the modules that depend on them. When the script cannot be sure, it builds everything. `tools/select-modules.sh`
- **Reproducible Jenkins lab**: Jenkins in Docker, configured entirely as code, with a Python harness that runs and checks every scenario. This site is generated from the recorded results.

### Existing tools it uses

- Jenkins, with the JUnit, Coverage, Warnings NG and Git Forensics plugins
- Maven, JaCoCo for test coverage, PMD for code-quality warnings
- Docker and Docker Compose
- Two open-source test projects: Train-Ticket and Spring PetClinic

### How you would use it

- Add `@Library('prk@lib-v1.1.1') _` and a `prGate(…)` step to a Jenkinsfile (full example in [examples/Jenkinsfile.multibranch](examples/Jenkinsfile.multibranch)).
- Run `select-modules.sh` before Maven and pass its result to `mvn -pl … -am -amd`, as the Train-Ticket pipeline does.

Where it fits: if your team already uses SonarQube, its pull-request quality gate can enforce new-code coverage and code-quality requirements. Unit-test execution and failure handling remain the responsibility of the CI pipeline. Established Maven tools such as Gitflow Incremental Builder provide change-based module selection, while the Maven Build Cache Extension avoids repeating eligible build work. The selector here is a small, transparent demonstration of change-based build selection.

## The problem

The original Train-Ticket pipeline has six practical problems that matter to a
merge gate:

1. It executes the same Maven reactor more than once, so feedback is slow.
2. PMD and JaCoCo are report-only. A failing analysis does not block a merge.
3. The Docker block prints success messages while no image is built or pushed.
4. The upstream pipeline uses a `sudo docker login -p` credential pattern.
5. The original pipeline has no dependency cache.
6. There is no timeout, so a hung test can occupy an executor indefinitely.

The kit keeps the application source pinned and unchanged. It delivers:

- A Jenkins controller with zero executors and one inbound agent with the
  required JDK 8 and JDK 17 toolchains.
- A faithful baseline for comparison and a rescued one-pass build.
- A Git-diff module selector for incremental scope, with safe full-scope
  fallbacks.
- One reusable `prGate` step that publishes JUnit results, applies a
  line-coverage gate and applies a Warnings NG PMD gate on new issues only.
- A second consumer, PetClinic, that calls the same library without changing
  the library implementation.

## Architecture

The stack is defined in `harness/`:

- `Dockerfile.controller` pins Jenkins and installs the plugin set from
  `plugins.txt`.
- `Dockerfile.agent` provides JDK 8, JDK 17 and Maven 3.9.16.
- `casc/jenkins.yaml` defines the controller, the inbound agent, the six jobs,
  the shared library and the security policy.
- `docker-compose.yml` exposes only loopback ports and does not mount the Docker
  socket.
- `pipelines/` contains the baseline, rescued and `prGate` Jenkinsfiles.
- `scripts/` contains the verifier, measurement tools, site generator and
  regression suites.

The controller schedules work. Builds run on the agent with separate pinned
toolchains.

## Recorded results

These results come from recorded Jenkins runs. They are not a single
build-time claim and they are not interchangeable.

| Claim | Result | Scope |
|---|---:|---|
| Fail-closed selective build | 38.22 s median | 3 of 43 reactor entries, 51 tests |
| Full reactor, packaging control | 514.6 s median, range 421.6 to 641.7 s | 43 entries, 626 tests, warm cache |
| Train-Ticket gate reference | 25 tests, 78.09% line coverage | `ts-assurance-service` |
| PetClinic gate reference | 79 reported tests, 77 passed, 93.99% line coverage | PetClinic monolith, Java 17 |

The selective build is the first result because it is the one the kit claims
with confidence. It builds the changed module scope and skips the rest, so 3 of
43 reactor entries ran in 38.22 s with 51 tests. That is a different workload
from the full-reactor comparison, not a faster execution of the same 626 tests.

The full-reactor comparison uses the packaging control. Three control runs of
one `verify` that continues through packaging for every module produced a
median of 514.6 s, against a baseline median of 589.0 s. The ranges overlap
between 577.1 s and 641.7 s, and the baseline also installs about 2.9 GB of
artifacts that the control does not. The same-workload time saving could not be
isolated; no same-workload speed-up is claimed. The historical 38.9% figure is
withdrawn and survives only in the recorded evidence and `docs/decisions.md`.

The Train-Ticket gate reference is deliberately narrow so the gate is
measurable. The PetClinic second consumer calls the same library without a
library change.

The site links every figure to the recorded file it comes from.

## What is not claimed

- No same-workload speed-up. The packaging control shows overlapping ranges and
  a partially different workload.
- The full Train-Ticket reactor is not green. The recorded full-reactor runs
  contain 626 tests with 220 failed or errored. The green gate reference is
  `ts-assurance-service` only.
- The Train-Ticket gate uses project line coverage, not modified-lines
  coverage. A small uncovered change can be hidden by existing covered lines.
- Trivy, SCA, secret scanning and DAST are not implemented.
- PetClinic MySQL tests are skipped without Docker. The PostgreSQL class aborts
  before execution and is reported with zero tests. Neither is counted as a
  pass.
- Only one Jenkins stack runs at a time because the container names are fixed.
- The benchmark is a single Intel Mac host. It is not a multi-host or
  production-scale benchmark.

## Repository layout

```text
jenkins-lib/       shared prGate library
harness/           Jenkins images, JCasC, pipelines, verifier, measurements
site/              static evidence-driven website and assets
examples/          multibranch example
tools/             module selector
evidence/          curated evidence files used by the site and its tests
release/           manifest, evidence closure, exclusions and checksums
docs/              public decision record
```

## Evidence policy

Raw build logs are kept privately and are available on request. Every figure on the site links to the recorded file it comes from.

The public export contains a curated evidence closure, not the full historical
experiment archive. The closure is listed in `release/evidence-closure.txt`.
Files outside it remain private. The public evidence is sufficient to regenerate
`site/data.json` and to run the data, UI and integrity suites.

## Reproduce

Prerequisites:

- An amd64 Docker host. The recorded host is an Intel Mac with Docker Desktop.
- Python 3, Git, OpenSSL and network access to GitHub and Maven Central.
- About 8 GB of free disk for source checkouts, the Maven cache and Jenkins
  volumes. The warm Maven cache alone was about 3,096 MB.

From a clean checkout:

```sh
python3 harness/scripts/m5_prepare_sources.py
python3 harness/scripts/m6_prepare_sources.py
make up
make verify
```

`m5_prepare_sources.py` and `m6_prepare_sources.py` clone the pinned upstream
applications when the local checkouts are absent. They create the disposable
branches and the generated PetClinic repository used by the demonstration.

Each public tag contains the recorded library code. Verify with
`git rev-parse lib-v1.0.0:jenkins-lib/vars` against
`evidence/site/library-releases.json`. Commit IDs in that file refer to the
original private history; the code fingerprint is the check.

Source preparation verifies the existing tags and does not create, move or
delete them. A normal `git clone` retrieves the required tags. GitHub's
Download ZIP does not provide the Git tag history needed for reproduction.

Jenkins is at `http://127.0.0.1:8080/`. The generated admin password is in
`.secrets/admin-password`, which is ignored by Git.

The one-command demonstration is:

```sh
make demo
```

It prepares the pinned sources and the generated PetClinic repository, starts
the harness if needed, builds the clean main reference and runs the controlled
pull-request scenarios. Expected negative results are successful demonstration
outcomes. The first run takes roughly 10 to 15 minutes on the recorded host and
longer when images and the Maven cache are cold.

`make verify` writes its output under `evidence/task-1.3a/verify/` by default.
Set `PRK_VERIFY_EVID` to write it elsewhere. These verification outputs are
working results and are not part of the curated public evidence.

### Validation commands

```sh
python3 harness/scripts/site-data-test.py
python3 harness/scripts/site-ui-test.py
python3 harness/scripts/evidence-integrity-test.py
```

The UI suite needs Chrome and the local Chrome DevTools Protocol helper used by
`harness/scripts/cdp.py`. The evidence-integrity suite verifies the curated
evidence against `release/checksums.txt`.

## Recorded benchmark environment

- Intel Core i5-1038NG7, 4 physical cores and 8 logical cores.
- 16 GiB host RAM.
- macOS 26.6.2, Intel x86_64.
- Docker Desktop 4.49.0, Docker Engine 28.5.1.
- Docker VM: 8 CPUs and 7.656 GiB RAM.
- Jenkins controller: zero executors. Agent: two executors.

The timings are from this host. They are not a claim about other hardware.

## Licence and attribution

The kit's original code is licensed under the Apache License 2.0. See `LICENSE`.

Third-party attribution is in `NOTICE`. The export does not contain complete
third-party application source trees. It contains two exact Train-Ticket POM
copies used as selector evidence and generated demo-branch diffs that use the
PetClinic package namespace.

## More detail

- `docs/decisions.md`: public technical decision record.
- `site/`: the evidence-driven case study.
- `release/evidence-closure.txt`: the curated evidence list.
- `release/EXCLUDED.md`: what remains private and why.
