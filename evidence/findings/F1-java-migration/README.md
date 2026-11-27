# F1: Java migration verification

## Question

Does Maven running on JDK 11 reproduce the JDK 8 TestNG and JUnit outcomes for
the same Train-Ticket commit, test by test?

## Method

The original Surefire XML reports from the JDK 8 and JDK 11 full-reactor runs
were retained in the private scratch workspaces. `tools/prk-verify.py` compared
them by `(module, test class, test case)` identity and outcome.

- Source commit: `313886e99befb94be6cd45f085c98e0019f59829`
- Maven: 3.9.16 on both sides
- JDK 8: Temurin `1.8.0_512`
- JDK 11: Temurin `11.0.32.1`
- Test identities: 626 on each side
- Outcome differences: 0

## Result

| Status | JDK 8 | JDK 11 |
|---|---:|---:|
| Passed | 405 | 405 |
| Failed | 27 | 27 |
| Errored | 194 | 194 |
| Skipped | 0 | 0 |

Verdict: PASS, exact identity and outcome parity. This is baseline parity, not
application health. The 221 failing or erroring tests remain failures and
errors.

## Limitations

- One application and one host.
- The application is an unmaintained research benchmark with a predominantly
  star dependency graph.
- This does not certify JDK 11 for other projects.

## Evidence

Public in this bundle:

- `summary.json`, `excerpt.txt`
- `verification.txt` and `verification.json`

Private source references, not part of the publication bundle:

- Historical Surefire reports in the private scratch checkouts.
- `spike/logs/gate3a/` and `spike/GATE2_VALIDATION.md`.

Command with placeholders:

```sh
python3 tools/prk-verify.py <jdk8-reports> <jdk11-reports>
```
