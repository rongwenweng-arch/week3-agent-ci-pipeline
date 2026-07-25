#!/usr/bin/env python3
"""
select_tests.py -- minimal test-impact analysis for the Agent-Optimized CI
Pipeline assignment.

Goal: given the files changed in this push/PR, print (to stdout) the
smallest set of pytest targets that could possibly be affected, so CI can
run `pytest $(python scripts/select_tests.py)` instead of the full suite.

Design principle: ASYMMETRIC SAFETY. A false positive (running an
unnecessary test) costs a few seconds of CI time. A false negative (SKIPPING
a test that should have run) can ship a broken build. So every rule below is
written to fail open -- any change we don't have a confident, narrow mapping
for falls back to "run everything." This is a deliberate design choice
documented in docs/guardrails.md, not an oversight.

Mapping rules (checked in order):
  1. A changed file under tests/            -> run that test file directly.
  2. A changed file src/<name>.py           -> run tests/test_<name>.py if it
                                                exists.
  3. requirements.txt, conftest.py, pytest.ini, setup.cfg/pyproject.toml,
     or ANY changed file we don't recognize -> run the full suite (safe
     default; a dependency or config change can affect every test).

Usage:
    # In CI (real usage): diff against the merge-base of the PR
    python scripts/select_tests.py --base origin/main --head HEAD

    # Local/manual (what this repo's README demos were generated with):
    python scripts/select_tests.py --files src/string_utils.py

Output: a single line of space-separated pytest targets on stdout (either
specific test file paths, or the literal string "tests/" meaning "run
everything"). Also writes a one-line JSON decision record to
select_tests_decision.json for auditability (which files triggered which
targets, and why) -- useful evidence for the assignment's "before/after"
requirement and for anyone reviewing why a test was or wasn't skipped.
"""
import argparse
import json
import os
import subprocess
import sys

TESTS_DIR = "tests"
SRC_DIR = "src"
FULL_SUITE = f"{TESTS_DIR}/"

# Config/infra files that can influence *any* test's behavior -> always
# trigger a full run rather than trying to model their blast radius.
ALWAYS_FULL_SUITE_TRIGGERS = {
    "requirements.txt",
    "conftest.py",
    "pytest.ini",
    "setup.cfg",
    "pyproject.toml",
}


def get_changed_files(base, head):
    """Real usage in CI: ask git what changed between base and head."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            text=True,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except subprocess.CalledProcessError as e:
        print(f"# git diff failed ({e}); falling back to full suite", file=sys.stderr)
        return None  # signal "we don't know" -> caller should run everything


def map_file_to_targets(changed_file):
    """Return (targets:list[str]|None, reason:str).
    targets is None when this file forces a full-suite run."""
    base = os.path.basename(changed_file)

    if changed_file.startswith(TESTS_DIR + "/") and base.startswith("test_"):
        return [changed_file], "test file changed directly"

    if base in ALWAYS_FULL_SUITE_TRIGGERS:
        return None, f"'{base}' can affect any test -> full suite"

    if changed_file.startswith(SRC_DIR + "/") and base.endswith(".py"):
        module_name = base[:-3]
        candidate = f"{TESTS_DIR}/test_{module_name}.py"
        if os.path.exists(candidate):
            return [candidate], f"maps to {candidate} by naming convention"
        return None, f"no tests/test_{module_name}.py found -> full suite (safety fallback)"

    return None, f"unrecognized file '{changed_file}' -> full suite (safety fallback)"


def select(changed_files):
    if changed_files is None or len(changed_files) == 0:
        return [FULL_SUITE], [{"file": None, "targets": [FULL_SUITE], "reason": "no diff information -> full suite"}]

    targets = set()
    decisions = []
    force_full = False

    for f in changed_files:
        mapped, reason = map_file_to_targets(f)
        decisions.append({"file": f, "targets": mapped, "reason": reason})
        if mapped is None:
            force_full = True
        else:
            targets.update(mapped)

    if force_full:
        return [FULL_SUITE], decisions
    return sorted(targets), decisions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("BASE_REF", "HEAD~1"))
    ap.add_argument("--head", default=os.environ.get("HEAD_REF", "HEAD"))
    ap.add_argument("--files", nargs="*", default=None,
                     help="Explicit changed-file list (bypasses git diff); "
                          "used for local demos and unit-testing this script.")
    args = ap.parse_args()

    changed = args.files if args.files is not None else get_changed_files(args.base, args.head)
    targets, decisions = select(changed)

    with open("select_tests_decision.json", "w") as f:
        json.dump({"changed_files": changed, "targets": targets, "decisions": decisions}, f, indent=2)

    for d in decisions:
        print(f"# {d['file']}: {d['reason']}", file=sys.stderr)
    print(f"# -> pytest targets: {targets}", file=sys.stderr)

    print(" ".join(targets))


if __name__ == "__main__":
    main()
