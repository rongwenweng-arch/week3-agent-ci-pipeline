#!/usr/bin/env python3
"""
remediation_agent.py -- auto-remediates ONE narrow, well-defined failure
class for the Agent-Optimized CI Pipeline assignment:

    ClassOfFailure: "ModuleNotFoundError caused by a third-party package
    missing from requirements.txt."

Scope, on purpose (read docs/guardrails.md for the full blast-radius writeup):
  - This agent NEVER touches src/ or tests/. Its only possible edit is
    requirements.txt.
  - If the build log doesn't match this exact failure signature, the agent
    refuses and exits non-zero rather than guessing. It does not attempt to
    fix logic bugs, formatting, or anything else -- that is a different
    agent's job (see the Week 3 lab's build_fixer_agent.py for "fix a source
    bug" style remediation).
  - It never merges anything. It either (a) prints a dry-run diff + PR body
    for a human to read, or (b) opens a PR (if GH_TOKEN/REPO are configured)
    that still requires human review/merge -- identical guarantee to the lab.

Runs in two modes depending on environment:
  - No ANTHROPIC_API_KEY: deterministic, rule-based fix (import name -> pip
    package name lookup table below). This is intentionally NOT an LLM call
    for this narrow class -- it's fast, free, and 100% reproducible, which is
    arguably *better* engineering than routing every fix through an LLM. The
    README's "reflection" section discusses this trade-off explicitly.
  - ANTHROPIC_API_KEY set: additionally asks Claude to sanity-check the
    proposed fix and draft the PR description in prose, with a tightly scoped
    system prompt that forbids touching anything but requirements.txt.
  - GH_TOKEN + REPO set: opens a real PR. Otherwise: --dry-run behavior
    (prints the diff and PR body, writes fix_proposal.md) is automatic.
"""
import argparse
import json
import os
import re
import sys

# Import name -> real PyPI package name, for the common cases where they
# differ. Unknown imports fall back to "same name" (correct most of the time).
IMPORT_TO_PACKAGE = {
    "yaml": "PyYAML",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "PIL": "Pillow",
    "toml": "toml",
}

# Never propose "installing" these -- they're stdlib, so a ModuleNotFoundError
# on one of these means something else is broken (bad venv, typo), not a
# missing-dependency situation this agent is scoped to handle.
STDLIB_DENYLIST = {
    "os", "sys", "re", "json", "math", "typing", "unittest", "subprocess",
    "itertools", "functools", "collections", "pathlib", "datetime", "time",
}

FAILURE_PATTERN = re.compile(r"ModuleNotFoundError: No module named '([\w\.]+)'")

SYSTEM_PROMPT = """You are a narrowly-scoped remediation agent. You handle
EXACTLY one failure class: a Python ModuleNotFoundError caused by a
third-party package missing from requirements.txt. You are given the failing
build log and the current requirements.txt.

You must NOT:
- propose changes to any file other than requirements.txt
- invent a fix for any other kind of failure (logic bugs, syntax errors,
  formatting, flaky tests, etc.) -- if the log doesn't clearly show this
  exact failure class, say so and propose nothing
- remove or reorder existing requirements.txt entries; only append the
  missing package

Return only a short human-readable confirmation of the root cause and the
one line you are adding to requirements.txt."""


def find_missing_module(build_log: str):
    match = FAILURE_PATTERN.search(build_log)
    if not match:
        return None
    module = match.group(1).split(".")[0]
    if module in STDLIB_DENYLIST:
        return None
    return module


def already_satisfied(requirements_text: str, package: str) -> bool:
    pkg_lower = package.lower()
    for line in requirements_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[=<>~\[]", line)[0].strip().lower()
        if name == pkg_lower:
            return True
    return False


def propose_fix(build_log_path: str, requirements_path: str):
    with open(build_log_path) as f:
        build_log = f.read()

    module = find_missing_module(build_log)
    if module is None:
        print(
            "REFUSING TO ACT: build log does not match this agent's scope "
            "(missing-third-party-dependency ModuleNotFoundError). "
            "No changes proposed. Escalate to a human or a different agent.",
            file=sys.stderr,
        )
        return None

    package = IMPORT_TO_PACKAGE.get(module, module)

    with open(requirements_path) as f:
        requirements_text = f.read()

    if already_satisfied(requirements_text, package):
        print(
            f"REFUSING TO ACT: '{package}' is already in {requirements_path}; "
            f"the ModuleNotFoundError must have a different cause (bad venv, "
            f"typo in the import, wrong Python version). Out of scope.",
            file=sys.stderr,
        )
        return None

    new_requirements_text = requirements_text.rstrip("\n") + f"\n{package}\n"

    return {
        "root_cause": (
            f"Test collection failed with ModuleNotFoundError: No module "
            f"named '{module}'. '{package}' is imported by the source under "
            f"test but is not declared in {requirements_path}, so a clean "
            f"install (as CI does) never installs it."
        ),
        "fix_description": (
            f"Append '{package}' to {requirements_path}. No other file is "
            f"touched."
        ),
        "module": module,
        "package": package,
        "fixed_file_path": requirements_path,
        "fixed_file_content": new_requirements_text,
        "diff_preview": _diff_preview(requirements_text, new_requirements_text),
    }


def _diff_preview(old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    lines = [f" {l}" for l in old_lines]
    for l in new_lines[len(old_lines):]:
        lines.append(f"+{l}")
    return "\n".join(lines)


def maybe_ask_claude(fix: dict, requirements_path: str):
    """Optional: if an API key is configured, ask Claude to sanity-check and
    draft prose for the PR. Not required for this failure class to be fixed
    correctly -- see the README's reflection on why a deterministic fix is
    used here instead of routing everything through an LLM call."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("(No ANTHROPIC_API_KEY set -- using deterministic fix only, no LLM call made.)", file=sys.stderr)
        return fix["fix_description"]

    try:
        import anthropic
    except ImportError:
        print("(anthropic package not installed -- skipping LLM sanity-check.)", file=sys.stderr)
        return fix["fix_description"]

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=os.environ.get("MODEL", "claude-opus-4-8"),
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Root cause: {fix['root_cause']}\n"
                f"Proposed single-line change to {requirements_path}: "
                f"add '{fix['package']}'.\n"
                f"Write a 2-3 sentence PR description confirming this is "
                f"correct and safe."
            ),
        }],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return text.strip() or fix["fix_description"]


def open_pull_request(fix: dict, description: str):
    from github import Github

    gh = Github(os.environ["GH_TOKEN"])
    repo = gh.get_repo(os.environ["REPO"])
    base = os.environ.get("BASE_BRANCH", "main")
    branch_name = f"bot/fix-missing-dep-{fix['module']}"

    ref = repo.get_git_ref(f"heads/{base}")
    repo.create_git_ref(f"refs/heads/{branch_name}", ref.object.sha)

    contents = repo.get_contents(fix["fixed_file_path"], ref=base)
    repo.update_file(
        fix["fixed_file_path"],
        f"[bot] fix: add missing dependency '{fix['package']}'",
        fix["fixed_file_content"],
        contents.sha,
        branch=branch_name,
    )

    pr = repo.create_pull(
        title=f"[Bot Fix] Add missing dependency: {fix['package']}",
        body=(
            f"## Agent-Proposed Fix (missing-dependency class only)\n\n"
            f"**Root cause:** {fix['root_cause']}\n\n"
            f"**Change:** {fix['fix_description']}\n\n"
            f"{description}\n\n"
            f"---\n"
            f"*Scope guarantee: this agent can only ever modify "
            f"`requirements.txt`. It cannot merge this PR.*\n\n"
            f"**Checklist before approving:**\n"
            f"- [ ] The missing package name is correct (not a typo / not "
            f"confused with a similarly-named package)\n"
            f"- [ ] No version pin is silently overridden\n"
            f"- [ ] Only `requirements.txt` changed\n"
        ),
        head=branch_name,
        base=base,
    )
    return pr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="build_log.txt")
    ap.add_argument("--requirements", default="requirements.txt")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true",
                     help="Write the fix to disk locally (used by the demo "
                          "to prove the fix actually turns the build green; "
                          "a real CI run would do this via the opened PR "
                          "being merged, not by writing straight to disk).")
    args = ap.parse_args()

    fix = propose_fix(args.log, args.requirements)
    if fix is None:
        sys.exit(2)

    print(f"Root cause: {fix['root_cause']}")
    print(f"Fix: {fix['fix_description']}")
    print("\n--- diff preview: requirements.txt ---")
    print(fix["diff_preview"])
    print("--- end diff ---\n")

    description = maybe_ask_claude(fix, args.requirements)

    can_open_pr = bool(os.environ.get("GH_TOKEN")) and bool(os.environ.get("REPO"))
    if can_open_pr and not args.dry_run:
        pr = open_pull_request(fix, description)
        print(f"Opened PR #{pr.number}: {pr.html_url}")
    else:
        with open("fix_proposal.md", "w") as f:
            f.write(f"# Agent-Proposed Fix (dry run)\n\n")
            f.write(f"**Root cause:** {fix['root_cause']}\n\n")
            f.write(f"**Change:** {fix['fix_description']}\n\n")
            f.write(f"{description}\n\n")
            f.write("```diff\n" + fix["diff_preview"] + "\n```\n")
        print("(No GH_TOKEN/REPO configured or --dry-run passed: wrote fix_proposal.md instead of opening a PR.)")

    if args.apply:
        with open(args.requirements, "w") as f:
            f.write(fix["fixed_file_content"])
        print(f"[--apply] wrote fix to {args.requirements}")

    with open("remediation_result.json", "w") as f:
        json.dump({k: v for k, v in fix.items() if k != "diff_preview"}, f, indent=2)


if __name__ == "__main__":
    main()
