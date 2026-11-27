# Closure review: claims, evidence, privacy and acceptance

## Claim-to-evidence map

| Public claim | Evidence | Status |
|---|---|---|
| JDK 11 matched all 626 JDK 8 test identities | `tools/prk-verify.py`, `spike/logs/gate3a/jdk-parity-verify.txt`, F1 | Verified by execution |
| 405 passed, 27 failed, 194 errored on both JDKs | Surefire XML from the two runs, F1 | Verified by execution |
| GIB selected 1 of 43 reactor entries for the leaf fixture | Gate 3A build 2, `gib-a-2`, F3 | Verified by execution |
| GIB selected 43 of 43 for shared and root changes | Gate 2A logs, F3 | Verified by execution |
| BCE default cache restored 43 reactor entries and ran 0 tests | Gate 3A `bce-hazard2-1`, F4 | Verified by execution |
| Strict reconciled BCE ran 626 tests and failed | Gate 3A `bce-gate-1`, F4 | Verified by execution |
| Profiler produced JSON for 43 projects | Gate 3A `profiler-1`, F5 | Verified by execution |
| The v1.0 selector remains the implemented selector | `tools/select-modules.sh`, v1.0 documentation | Verified by inspection |
| Verification handles unreadable XML, missing names and failure-to-skip | `tools/test_prk_verify.py`, 13 synthetic tests | Verified by execution |
| Reactor chart proportions derive from generated data | `site/app.js`, `site/data.json`, UI assertions | Verified by execution |
| No performance improvement is claimed | Historical benchmark sections and `docs/decisions.md` | Editorial and evidence check |

## Limitations

- One host, one application and a predominantly star dependency graph.
- The application suite is not green: 221 tests failed or errored at the pinned
  commit.
- GIB over-selects the full reactor for shared-module and root changes in the
  tested configuration.
- JDK 17 was not adopted because the tested test tooling did not execute tests.
- BCE strict caching stored 11 of 43 entries for this application.
- Profiler required the shaded artifact and `-Dmaven.ext.class.path`.
- No controlled performance comparison was run in this closure phase.

## Evidence reference policy

- Public curated files are under `evidence/findings/` and `verification`.
- Private historical source logs are named in finding READMEs but are not part
  of the publication bundle.
- Sanitized Jenkinsfiles replace absolute paths and were not rerun.
- Fresh strict-cache execution and the earlier copied reconciled-cache
  experiment are separate results. No comprehensive warm-cache claim is made.
- The publication allowlist is `docs/publication-allowlist.md`.

## Privacy review

- No credentials, tokens, private keys, personal email addresses or private
  network addresses are present in the curated findings.
- Raw logs and scratch checkouts remain gitignored and private.
- Excerpts are sanitized console fragments, not full build logs.
- No Jenkins screenshot was fabricated.
- The public repository and website were not changed in this closure phase.

## Final acceptance status

- Verification script: accepted for the closure scope; 13 synthetic tests pass.
- Report comparison cannot establish freshness, artifact provenance or whether
  reports came from restored caches.
- Curated evidence pack: complete for F1 to F5.
- Findings data integration: complete; `site/data.json` is generated from the
  five summaries.
- Website editorial rewrite: implemented on the closure branch for owner review.
- Site data and UI checks: pass.
- Fresh-clone limitation: the site data suite requires gitignored raw evidence;
  publicly reproducible checks are the verification script and generator output
  when the curated evidence is present.
- Closure is not complete until owner review and approval.

## Final correction validation

| Check | Result |
|---|---|
| `tools/test_prk_verify.py` | 13 tests pass |
| Historical JDK 8 versus JDK 11 comparison | PASS, 626 of 626, exit 0 |
| `site-data-test.py` | 776 checks pass |
| `site-ui-test.py` | 220 checks pass |
| `evidence-integrity-test.py` | PASS |
| Gitleaks on curated findings and review text | 0 findings |
| Fresh checkout: tests, verifier and generator | pass; byte-identical data |
| Fresh checkout: data suite | blocked by private raw M4 evidence |

The report comparison cannot establish freshness, artifact provenance or whether
reports came from restored caches. It verifies identity and outcome parity only.
