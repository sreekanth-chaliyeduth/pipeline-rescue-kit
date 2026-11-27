# Publication allowlist

This is the explicit list of files intended for eventual public publication.
Do not use `git add .`. Stage only paths from this list after owner approval.

## Frontend

- `site/index.html`
- `site/styles.css`
- `site/app.js`
- `site/data.json`
- `site/assets/` (all ten WebP files)

## Verification

- `tools/prk-verify.py`
- `tools/test_prk_verify.py`

## Curated findings

- `evidence/findings/F1-java-migration/` (summary, excerpt, README, verification output)
- `evidence/findings/F2-jdk17-assessment/` (summary, excerpt, README)
- `evidence/findings/F3-build-selection/` (summary, excerpt, README)
- `evidence/findings/F4-build-cache/` (summary, excerpt, README)
- `evidence/findings/F5-build-profiling/` (summary, excerpt, README)

## Public documentation

- `docs/findings.md`
- `docs/closure-review.md`
- `docs/publication-allowlist.md`

## Data generation and validation

- `harness/scripts/build_site_data.py`
- `harness/scripts/site-data-test.py`
- `harness/scripts/site-ui-test.py`
- `harness/scripts/evidence-integrity-test.py`
- `harness/scripts/verify.py`
- `harness/scripts/jenkins_api.py`
- `harness/scripts/cdp.py`

## Sanitized experimental reproduction

- `harness/pipelines/v11-experimental/SANITIZED.md`
- `harness/pipelines/v11-experimental/sanitized/` (all eight files)
- `harness/pipelines/v11-experimental/agent/Dockerfile`

## Excluded from publication

- Unsanitized experimental Jenkinsfiles directly under
  `harness/pipelines/v11-experimental/`.
- `spike/` reports, logs and preview screenshots.
- `spike/work/`, Maven caches, target directories and scratch checkouts.
- Raw historical evidence under `evidence/` outside `evidence/findings/`.
- `docs/private/`, credentials, `.secrets/` and machine-specific configuration.
- Any file not listed above.

## Evidence reference policy

- Site and findings links to `evidence/findings/...`, `tools/prk-verify.py` and
  `harness/...` are intended to resolve in the public repository after
  publication.
- Private source logs named in findings are explicitly labelled as private and
  are not included.
- Sanitized Jenkinsfiles replace absolute experiment paths with placeholders and
  were not rerun.
