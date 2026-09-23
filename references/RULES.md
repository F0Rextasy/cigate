# Workflow catalogue

Input: a repository root containing `.github/workflows/*.{yml,yaml}`.
Missing directory -> usage error (exit 2); directory present but empty of
workflows -> usage error too (nothing to gate is not a clean verdict).

Parser: PyYAML `safe_load`. Known quirk handled: YAML 1.1 reads the key
`on` as boolean `true`, so triggers are read from `on` **or** `True`;
shorthand (`on: [push]`), scalar (`on: push`) and mapping forms all
normalize to a trigger list plus a mapping of per-trigger options.

## Rules

| Rule | Severity | Condition |
| --- | --- | --- |
| `unpinned-action` | warn | a `uses:` ref whose target after `@` is not `[0-9a-f]{40}`; deduped per workflow; local `./path` and `docker://image` skipped (no commit exists to pin) |
| `missing-paths-filter` | warn | `push` and/or `pull_request` trigger without `paths`/`paths-ignore` **and** the workflow is costly: `len(jobs) >= 2` or any job has `strategy.matrix` |
| `no-concurrency` | warn | `pull_request` among triggers and no top-level `concurrency` key |
| `duplicate-job` | fail | two job names whose bodies are identical after `json.dumps(sort_keys=True)` - keys and order normalized, names excluded |
| `waste-budget` | fail | history mode sum exceeds `--max-waste-minutes` |
| `malformed-workflow` | warn | YAML error / non-mapping document - reported, never skipped silently |

## History mode (offline by design)

`--runs-json FILE` accepts a captured
`gh api repos/OWNER/REPO/actions/runs --paginate` payload (array of run
objects; `run_started_at`/`created_at` + `updated_at` + `conclusion`
used). No network call is ever made by the tool - a gate that flakes when
GitHub hiccups is not a gate.

Minutes math: runs whose `conclusion` is `failure`, `cancelled`, or
`timed_out`; window = now - `--since-days` (default 30) against
`run_started_at`; duration = `updated_at - run_started_at`, floored to
minutes, clamped at 0; runs missing a parseable timestamp are skipped.
`--max-waste-minutes N` without `--runs-json` is a usage error.

## Exemptions

`--allow RULE=reason` (repeatable): drops the whole rule, requires a
non-empty reason, and is echoed as `N exempt by --allow` in the text
summary and `counts.exempt` in JSON. Unknown rule or empty reason ->
usage error (exit 2).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | no failing rule; no warning under `--strict` |
| 1 | a fail rule fired, budget exceeded, or any warning with `--strict` |
| 2 | usage: missing root, no workflow files, bad `--allow`, budget without `--runs-json`, unreadable runs JSON |

## Invariants

- Static findings are a pure function of the workflow bytes; history
  findings a pure function of (runs JSON, window, budget).
- Findings name the workflow file relative to
  `.github/workflows/` (forward slashes on every OS), so CI output and
  local output are byte-identical.
- Row order is deterministic: per-file alphabetical by rule, history row
  (`-`) last.
- The gate scans itself in this repository's own CI with `--strict`:
  unpinned actions or a missing concurrency group fail the build that
  would ship them.
