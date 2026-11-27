# F4: build-cache safety assessment

## Question

Can a build cache be used in a quality gate without hiding tests that were
failing when the cache was seeded?

## Method

BCE 1.2.3 on JDK 11 and Maven 3.9.16 was tested in three configurations:

1. A cache seeded while `maven.test.failure.ignore=true`.
2. A strict build against that cache with default BCE configuration.
3. A strict build with the documented Surefire `skipTests` and
   `testFailureIgnore` reconciliation, and a separate strict cache.

An uncached strict build provided the reference.

## Result

| Run | Cache state | Restored | Tests executed | Maven exit |
|---|---|---:|---:|---:|
| Strict, default policy | Fresh cache seeded with failure-ignore | 43 | 0 | 0 |
| Strict, uncached reference | No cache | 0 | 626 | 1 |
| Strict, reconciled, fresh gate cache | Strict-only cache, no prior entries | 0 | 626 | 1 |
| Strict, reconciled, one-test run | Copy of the earlier exploratory cache | 2 unaffected entries | affected tests executed | 1 |

The fresh strict gate run saved 11 of 43 reactor entries. The other modules
contain tests that already fail, so they cannot be stored as successful entries.
This is a strict-cache result for Train-Ticket, not comprehensive warm-cache
validation.

The one-test run used a copied exploratory cache and two unaffected entries
were restored. Changed entries missed by checksum and the seeded test failed.
That is not evidence that a fully warm strict cache is safe for every change.

## Commands with placeholders

```sh
# Seed the exploratory cache with ignored failures.
mvn -B -T 2 -fae -Dmaven.test.failure.ignore=true \
  -Dmaven.repo.local=<repo> -Dmaven.build.cache.location=<cache> verify

# Strict run against the same cache, with reconcile configuration.
mvn -B -T 2 -fae -Dmaven.repo.local=<repo> \
  -Dmaven.build.cache.location=<cache> verify
```

## Decision

BCE was evaluated and not selected for future core integration. The behaviour
is configuration-dependent, with a documented mitigation. It is not a security
vulnerability.

## Limitations

- The 11-entry result is specific to Train-Ticket and its 221 baseline failures.
- It does not establish a universal cacheability limit.
- Fresh strict execution and earlier reconciled-cache experiments are distinct.
- The reconciled cache must be kept separate from exploratory caches.

## Evidence

Public in this bundle: `summary.json`, `excerpt.txt`.

Private source references, not part of the publication bundle:

- `spike/GATE3A.md`, sections J2a to J2d
- Gate 3A builds `bce-hazard2-1`, `bce-gate-1` and `bce-one-cached-2`

Sanitized reproduction, not rerun:

- `harness/pipelines/v11-experimental/sanitized/bce-hazard2.Jenkinsfile`
- `harness/pipelines/v11-experimental/sanitized/bce-one-cached.Jenkinsfile`

## Decision

BCE was evaluated and not selected for future core integration. The behaviour
is configuration-dependent, with a documented mitigation. It is not a security
vulnerability.

## Limitations

- The 11-entry result is specific to Train-Ticket and its 221 baseline failures.
- It does not establish a universal cacheability limit.
- The reconciled cache must be kept separate from exploratory caches.

## Evidence

- `spike/GATE3A.md`, sections J2a to J2d
- `spike/logs/gate3a/bce-hazard2-1/`
- `spike/logs/gate3a/bce-gate-1/`
