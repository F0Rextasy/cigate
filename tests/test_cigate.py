"""Contract tests for cigate. Run: python -m unittest discover -s tests -v

Workflows are written to temp repos and audited by the real CLI; history
mode runs off a captured gh-api payload (no network), because a gate that
needs the network is a gate that flakes.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "cigate")
SHA = "b1a2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"

CLEAN = """\
name: test
on:
  push:
    paths: ["src/**"]
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@%s
      - run: pytest -q
""" % SHA


def run_cli(*args):
    proc = subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=ROOT)
    return proc.returncode, proc.stdout, proc.stderr


def repo_with(tmp, workflow_body, name="ci.yml"):
    directory = os.path.join(tmp, ".github", "workflows")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(workflow_body)
    return tmp


class CigateContract(unittest.TestCase):
    def test_clean_workflow_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, CLEAN)
            code, out, _ = run_cli(tmp, "--format", "json")
            self.assertEqual(code, 0, out)
            data = json.loads(out)
            self.assertTrue(data["ok"])
            self.assertEqual(data["counts"],
                             {"fail": 0, "warn": 0, "exempt": 0,
                              "workflows": 1, "uses": 1})

    def test_unpinned_action_warns_and_strict_blocks(self):
        body = CLEAN.replace(SHA, "v4")
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, body)
            code, out, _ = run_cli(tmp, "--no-color")
            self.assertEqual(code, 0, out)
            self.assertIn("unpinned-action", out)
            self.assertEqual(out.count("unpinned-action"), 1)
            code, _, _ = run_cli(tmp, "--strict", "--no-color")
            self.assertEqual(code, 1)

    def test_matrix_workflow_without_paths_warns(self):
        body = """\
name: test
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@%s
      - run: pytest -q
""" % SHA
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, body)
            code, out, _ = run_cli(tmp, "--format", "json")
            self.assertEqual(code, 0, out)
            finding = json.loads(out)["findings"][0]
            self.assertEqual(finding["rule"], "missing-paths-filter")
            self.assertIn("push", finding["message"])

    def test_duplicate_jobs_fail(self):
        body = """\
name: test
on:
  push:
    paths: ["src/**"]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@%s
      - run: pytest -q
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@%s
      - run: pytest -q
""" % (SHA, SHA)
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, body)
            code, out, _ = run_cli(tmp, "--format", "json")
            self.assertEqual(code, 1, out)
            finding = json.loads(out)["findings"][0]
            self.assertEqual(finding["rule"], "duplicate-job")
            self.assertIn("'build'", finding["message"])
            self.assertIn("'test'", finding["message"])

    def test_pull_request_without_concurrency_warns(self):
        body = """\
name: test
on:
  pull_request:
    paths: ["src/**"]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@%s
      - run: pytest -q
""" % SHA
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, body)
            code, out, _ = run_cli(tmp, "--format", "json")
            self.assertEqual(code, 0, out)
            rules = [f["rule"] for f in json.loads(out)["findings"]]
            self.assertEqual(rules, ["no-concurrency"])
            # same workflow with a concurrency group -> no finding
            with_conc = body + "concurrency:\n  group: pr\n"
            repo_with(tmp, with_conc, name="ok.yml")
            os.remove(os.path.join(tmp, ".github", "workflows", "ci.yml"))
            code, out, _ = run_cli(tmp, "--format", "json")
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out)["findings"], [])

    def test_waste_budget_over_and_under(self):
        runs = [{"conclusion": "failure",
                 "run_started_at": "2026-09-20T10:00:00Z",
                 "updated_at": "2026-09-20T10:20:00Z"},
                {"conclusion": "success",
                 "run_started_at": "2026-09-21T09:00:00Z",
                 "updated_at": "2026-09-21T09:05:00Z"}]
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, CLEAN)
            runs_file = os.path.join(tmp, "runs.json")
            with open(runs_file, "w", encoding="utf-8") as handle:
                json.dump(runs, handle)
            code, out, _ = run_cli(tmp, "--runs-json", runs_file,
                                   "--max-waste-minutes", "10",
                                   "--format", "json")
            self.assertEqual(code, 1, out)
            data = json.loads(out)
            finding = data["findings"][0]
            self.assertEqual(finding["rule"], "waste-budget")
            self.assertIn("20 min", finding["message"])
            self.assertEqual(data["waste"],
                             {"failed_runs": 1, "minutes": 20,
                              "window_days": 30, "budget": 10})
            code, out, _ = run_cli(tmp, "--runs-json", runs_file,
                                   "--max-waste-minutes", "60",
                                   "--no-color")
            self.assertEqual(code, 0, out)
            self.assertIn("20 min wasted", out)

    def test_missing_inputs_are_usage_errors(self):
        code, _, err = run_cli(os.path.join("nope", "dir"))
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err)
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".github", "workflows"))
            code, _, err = run_cli(tmp)
            self.assertEqual(code, 2)
            self.assertIn("no workflow files", err)
            repo_with(tmp, CLEAN)
            code, _, err = run_cli(tmp, "--max-waste-minutes", "5")
            self.assertEqual(code, 2)
            self.assertIn("--runs-json", err)

    def test_malformed_yaml_warns_and_strict_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, "on: [push]\njobs: [ : : broken\n")
            code, out, _ = run_cli(tmp, "--no-color")
            self.assertEqual(code, 0, out)
            self.assertIn("malformed-workflow", out)
            code, _, _ = run_cli(tmp, "--strict", "--no-color")
            self.assertEqual(code, 1)

    def test_allow_exempts_with_a_reason(self):
        body = CLEAN.replace(SHA, "v4")
        with tempfile.TemporaryDirectory() as tmp:
            repo_with(tmp, body)
            code, out, _ = run_cli(
                tmp, "--allow", "unpinned-action=vendor policy", "--no-color")
            self.assertEqual(code, 0, out)
            self.assertIn("exempt", out)
            self.assertIn("ok --", out)


if __name__ == "__main__":
    unittest.main()
