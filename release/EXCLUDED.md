# Excluded material

The public export is built from an explicit inclusion manifest. This file records
what remains private and why. It does not list every raw log, transcript or
environment dump.

## Private evidence outside the closure

All evidence files outside `release/evidence-closure.txt` remain private. This
class includes:

- Raw build logs and Maven reactor logs not named in the closure.
- Verification transcripts, fresh-clone transcripts and environment dumps.
- Diagnostic outputs, per-task working folders and temporary experiment
  artifacts.
- Historical development review records and intermediate measurement files.
- Nested application source trees and bare Git repositories.

Reason: the public site and its tests need a small, reproducible evidence
closure. The wider archive contains private working material that is not needed
to support a public claim.

## Private planning and coordination files

- `AGENTS.md`
- `docs/plan.md`
- `docs/public-release.md`
- `docs/website-plan-v4.md`
- `.secrets/`

Reason: private planning, employer and role context, release coordination,
credentials and private agent instructions. They are not public-release material.

## Demo script

- `docs/demo-script.md`

Reason: the prose review found that it instructs a presenter to open private
evidence files that are not in the curated export and refers to internal
milestone records. It does not pass the public prose review.

## Development review tooling

- `harness/scripts/site-refinement-capture.py`

Reason: it captures private editorial-review screenshots outside the curated
evidence closure. It is not needed to build, run or validate the public site.

## Historical website screenshots

Screenshots outside `site/assets/` and the curated evidence are private. The
public site uses only the assets listed in `evidence/site/images.json`.

## Private operational documents

The takedown procedure and the P5.7 owner checklist are private operational
runbooks. They name deployment order, DNS rollback and personal-site safeguards
that must not be published. They are kept in the private repository only.

## Private Git data

The private repository history, tags, author identities, remotes and any nested
Git objects are excluded. The public export has its own separate history.

## Sensitive values

No credential, personal home path, private address, personal email address or
employer name is reproduced in this file. The closure audit found zero personal
findings in the files selected for publication.
