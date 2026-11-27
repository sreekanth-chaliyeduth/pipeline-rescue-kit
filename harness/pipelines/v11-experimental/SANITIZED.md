# Gate 3A experimental Jenkinsfiles

The files in this directory are historical experimental definitions from Gate
3A. They are not product pipelines and are not loaded by the existing PRK jobs.

`/spike` and `/logs` were absolute paths in the executed definitions. The
sanitized copies in `sanitized/` substitute `${SPIKE_ROOT}` and
`${EVIDENCE_ROOT}`. Apart from those path placeholders and the header comment,
the scripts are the same as the executed definitions. The sanitized copies were
not rerun. The executed build numbers, console output and logs remain under
`spike/logs/gate3a/`.

The fallback fixture contains the deliberately unavailable extension version
`9.9.9`. That value is part of the experiment, not a product default.

One historical file differs from its executed build: `gib-fixture-a.Jenkinsfile`
retains the pre-execution `/spike/work/...` paths. The executed build used
`/spike/...` after the mount path was corrected. The sanitized copy uses only
the path placeholders; the executed command and its evidence are in
`spike/logs/gate3a/gib-a-2`. No historical definition was rewritten.
