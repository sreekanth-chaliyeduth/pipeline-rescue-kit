# F2: JDK 17 compatibility assessment

## Question

Can the same Train-Ticket build run on JDK 17 while targeting Java 8?

## Method

The full reactor was run with Maven 3.9.16 on Temurin 17.0.21.1, compiling to
Java 8. The command retained the existing failure-ignore setting so every
module could be reached.

## Observed interaction

- JaCoCo 0.8.2 attaches its agent to each forked test JVM.
- On JDK 17 the agent failed during JVM startup:
  `FATAL ERROR in native method: processing of -javaagent failed`.
- Surefire reported `Tests run: 0`.
- Maven reported `BUILD SUCCESS` because test failures were ignored.
- All 43 modules compiled and packaged, but no test outcome was produced.

This is a legacy JaCoCo and failure-policy interaction. It is not a general
Java 17 defect and does not show that the application cannot run on Java 17.

## Command with placeholders

```sh
JAVA_HOME=<jdk17> mvn -B -T 2 -fae -Dmaven.test.failure.ignore=true \
  -Dmaven.repo.local=<repo> -Dmaven.compiler.release=8 verify
```

## Decision

JDK 11 is the validated migration target for the current test stack. JDK 17
requires upgrading and revalidating the test tooling before it can be assessed.

## Evidence

Public in this bundle: `summary.json`, `excerpt.txt`.

Private source references, not public: the JDK 17 Maven log and
`spike/GATE2_VALIDATION.md`. The log is not included because it is raw execution
evidence.
