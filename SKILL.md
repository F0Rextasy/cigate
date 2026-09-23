---
name: cigate
description: Gates GitHub Actions workflows for waste and drift -- unpinned actions tags, push/pull_request triggers without path filters (every docs-only commit runs the matrix), duplicate jobs that pay twice, pull_request without a concurrency group, and an optional history budget that fails when minutes burned on failed/cancelled runs exceed --max-waste-minutes (fed offline from a captured gh api actions/runs payload). Use before merging workflow changes, in CI on every PR, or when a repo's Actions bill or queue time creeps up. Exit 1 = over a failure-class rule or budget; exit 2 = no workflows / bad usage.
license: MIT
compatibility: Requires Python 3.8+ with PyYAML (pip install pyyaml). No network needed: history mode reads a local --runs-json capture of `gh api repos/OWNER/REPO/actions/runs`. Works in Claude Code, Codex, Cursor, and any Agent Skills compatible client.
metadata:
  author: F0Rextasy
  version: "1.0"
---

# cigate

CI is where minutes quietly burn: every push runs the full matrix
because nobody wrote `paths:`, two copy-pasted jobs do the same work,
superseded runs queue because there is no `concurrency` group, and last
month's failures ate the free quota. `cigate` reads your
`.github/workflows/*.yml` as data and puts a number on the waste.

## The one rule

You may not ship a workflow that burns minutes twice:

```bash
python scripts/cigate . --strict
```

- **exit 1** - a failure-class rule fired, or a budget was exceeded (or
  any warning with `--strict`).
- **exit 0** - workflows are lean.
- **exit 2** - usage: no workflow files, bad `--allow`, budget without
  `--runs-json`.

## Protocol

1. **Point at the repo root**: cigate reads
   `.github/workflows/*.{yml,yaml}` (a directory without workflows is a
   usage error - there is nothing to gate).
2. **Static pass** (always): four rules over parsed YAML.
3. **History pass** (optional): `--runs-json` = local capture of
   `gh api repos/O/R/actions/runs` (works offline, reproducible);
   `--max-waste-minutes N` turns the sum into a `waste-budget` failure.
   Window: `--since-days` (default 30).
4. **Read findings** as `file  FAIL  rule  message`, then fix or exempt:
   `--allow RULE=reason` (repeatable), counted in the summary and JSON.

## Rules

| Rule | Severity | Fires when |
| --- | --- | --- |
| `unpinned-action` | warn | `uses:` target is not a full 40-char commit SHA (once per distinct ref; `./` local and `docker://` skipped) |
| `missing-paths-filter` | warn | `push`/`pull_request` triggers lack `paths`/`paths-ignore` **and** the workflow is costly (>=2 jobs or a matrix) |
| `no-concurrency` | warn | `pull_request` trigger with no top-level `concurrency` |
| `duplicate-job` | fail | two jobs have byte-identical bodies under different names |
| `waste-budget` | fail | failed/cancelled/timed_out run minutes in the window exceed `--max-waste-minutes` |
| `malformed-workflow` | warn | YAML that cannot be parsed - un-audited, reported not hidden |

```console
$ python scripts/cigate examples/mini-repo --runs-json examples/runs.json --max-waste-minutes 5 --no-color
ci.yml  FAIL  duplicate-job        jobs 'build' and 'test' are identical -- every run pays twice
ci.yml  WARN  missing-paths-filter on: push, pull_request without paths/paths-ignore -- every push runs 2 job(s)
ci.yml  WARN  no-concurrency       pull_request without a concurrency group -- rapid pushes queue full runs back to back
ci.yml  WARN  unpinned-action      uses actions/checkout@v4 -- pin the 40-char commit SHA
-       FAIL  waste-budget         20 min in 1 failed/cancelled run(s) over 30d exceeds budget 5 min

cigate: 2 failure(s), 3 warning(s) across 1 workflow(s), 2 action pin(s) checked; history: 1 failed/cancelled run(s) = 20 min wasted (budget 5 min)
cigate: fix the workflow -- or exempt a rule with:  --allow RULE=<reason>
[exit 1]
```

## Reporting back

1. Counts: failures / warnings / workflows / action pins checked.
2. History suffix: failed runs, wasted minutes, budget.
3. Command and exit code.
