# F5: build profiling assessment

## Question

Can Maven Profiler provide per-module, per-mojo evidence for the full
Train-Ticket reactor without adding an observability platform?

## Method

Maven Profiler 3.3 was tested on JDK 11 and Maven 3.9.16.

- The thin core extension was declared in `.mvn/extensions.xml`.
- The shaded artifact was supplied through
  `-Dmaven.ext.class.path=<shaded.jar>`.

## Result

The thin extension loaded but produced no report. Debug output showed a
classloader conflict: the profiler tried to access Maven core's Guava
`Stopwatch` from a different class realm.

The shaded artifact, with relocated dependencies, produced valid JSON:

- 43 projects
- 650,762 ms recorded
- compile, test, packaging, resources and JaCoCo mojo records
- parallel `-T 2` completed

Checksum:
`d235bc3f1d75d3eefde5627f33e7255c3d2f4476bad7f3c60fed6056a54f6f87`.

## Decision

Use the shaded artifact with checksum verification. Do not use the thin
extension in this environment. Profiling is a diagnostic aid, not a quality
gate.

## Limitations

- A successful profiled build does not mean the application tests passed.
- No universal performance bottleneck is claimed.
- The artifact was not vendored into the repository.

## Evidence

Public in this bundle: `summary.json`, `excerpt.txt`.

Private source references, not public: Gate 3A build `profiler-1` and the
private Gate 2A and 3A reports.

Sanitized reproduction, not rerun:

- `harness/pipelines/v11-experimental/sanitized/profiler.Jenkinsfile`

Command with placeholders:

```sh
mvn -Dmaven.ext.class.path=<shaded-jar> -Dprofile -DprofileFormat=JSON verify
```
