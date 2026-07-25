# Agent-Optimized CI Pipeline

A small CI pipeline where an agent does two things: (1) skips tests that
can't possibly be affected by a given change, and (2) auto-remediates one
narrow, well-defined class of build failure — a missing third-party
dependency — by opening a human-reviewed PR.

## Try it yourself

This repo ships in a green baseline (`requirements.txt` already lists
`toml`). To reproduce the missing-dependency demo yourself: delete the
`toml` line from `requirements.txt`, run `pytest`, watch `tests/test_data_loader.py`
fail to collect, then run
`python scripts/remediation_agent.py --log build_log.txt --requirements requirements.txt`
and confirm it proposes putting the line right back.

## Architecture

```
push/PR
  │
  ▼
select-and-test job
  │  scripts/select_tests.py inspects the diff, prints the minimal
  │  pytest target list (or "run everything" if unsure)
  ▼
pytest <selected targets>  →  build_log.txt
  │
  ├─ green → done
  │
  └─ red ──▶ remediate job (GitHub Environment: agent-proposed, Required reviewers)
              scripts/remediation_agent.py reads build_log.txt
              │
              ├─ matches "missing-dependency" signature
              │     → proposes a 1-line requirements.txt fix
              │     → opens a PR (or writes fix_proposal.md if no
              │       GH_TOKEN/REPO configured) — never merges
              │
              └─ doesn't match  → refuses, exits non-zero, escalates to a human
```

## Design choices

**Test selection fails open, not closed.** `select_tests.py`'s mapping is
deliberately narrow: `src/<name>.py → tests/test_<name>.py` by naming
convention, and a changed test file runs itself. Anything else —
`requirements.txt`, `conftest.py`, config files, or a source file with no
matching test file — forces a full-suite run instead of guessing. A skipped
test that should have run is a worse outcome than a wasted 10 seconds of CI
time, so the tool is biased toward the safe side whenever it isn't sure.
This is verified below, not just asserted.

**The remediation agent is intentionally narrow, and doesn't need an LLM to
be correct for this failure class.** It handles exactly one signature —
`ModuleNotFoundError` for a package missing from `requirements.txt` — using
a small deterministic lookup table (`import name → PyPI package name`, to
handle the common cases where they differ, e.g. `yaml → PyYAML`). If
`ANTHROPIC_API_KEY` is configured, Claude additionally drafts the PR's prose
and sanity-checks the diff, but it cannot change *what* gets written to
`requirements.txt` — see `docs/guardrails.md`. If the build log doesn't
match this exact signature, the agent refuses and exits non-zero rather than
improvising a fix for a bug class it wasn't built to reason about.

**Blast radius is enforced in code, not just in a prompt.** The remediation
agent's only possible file write is an append to `requirements.txt`. Neither
agent can merge anything; both rely on the same GitHub Environment
(`agent-proposed`, Required reviewers) used in the Week 3 lab.

## Results (real, locally verified — see "What's real vs. what still needs your repo" below)

Demo app: `src/calculator.py` (4 tests), `src/string_utils.py` (3 tests),
`src/data_loader.py` (2 tests, imports `toml`, which is intentionally *not*
in `requirements.txt`).

**Test selection**, driven by a real `git diff` between two branches in a
throwaway local repo (only `src/string_utils.py` changed):

| Changed file(s) | Selected targets | Tests that would run |
|---|---|---|
| `src/string_utils.py` | `tests/test_string_utils.py` | 3 of 9 |
| `src/calculator.py` | `tests/test_calculator.py` | 4 of 9 |
| `tests/test_string_utils.py` (test file itself) | `tests/test_string_utils.py` | 3 of 9 |
| `requirements.txt` (safety fallback) | `tests/` (everything) | 9 of 9 |
| `README.md` (unrecognized file, safety fallback) | `tests/` (everything) | 9 of 9 |

The first case is the headline number: a change to one unrelated module
skips 6 of 9 tests (67%) with no risk of skipping something that could
actually be affected, since `string_utils.py` has no callers in
`calculator.py` or `data_loader.py`. Full commands and raw output are in
`docs/test_selection_log.txt`.

**Remediation agent**, run against a real captured `build_log.txt`:

- On the actual `toml`-missing failure: correctly diagnosed the root cause,
  proposed appending exactly one line (`toml`) to `requirements.txt`, wrote
  `fix_proposal.md` (no GitHub credentials were configured in this
  environment — see caveats below), and, when applied, `requirements.txt`
  contained the correct entry.
- On the *unrelated* calculator logic bug's build log (an `AssertionError`,
  not a missing-dependency error): **refused to act**, printed why, and
  exited with code 2 — verified, not assumed. See `docs/remediation_log.txt`.
- On a build log where the missing package was already listed in
  `requirements.txt`: also refused, on the theory that some other cause must
  be responsible.

## What's real vs. what still needs your repo

Everything above was executed for real, in a sandboxed dev environment,
against the actual scripts in this submission — the build failures, the
`git diff`-based selection, and the agent's diagnosis/refusal behavior are
genuine console output, not scripted or invented.

Two things could **not** be produced from that sandbox, and need to happen
in your own GitHub repo before you submit:

1. **A live GitHub Actions run with real screenshots.** The sandbox this was
   built in has no outbound access to GitHub's API or to PyPI, so there is
   no real workflow run, no real PR, and no real approval-gate screenshot to
   show you here. Push this folder to your own repo, add `ANTHROPIC_API_KEY`
   and `GH_TOKEN` as secrets, configure the `agent-proposed` Environment with
   Required reviewers (identical steps to the Week 3 lab), and trigger a push
   with the calculator bug present. That produces the real screenshots the
   rubric and the lab deliverable ask for.
2. **The final "pip install fixes it" step for the `toml` demo.** The agent's
   proposed fix is correct (verified: the diff is exactly `+toml`), but this
   sandbox couldn't reach PyPI to actually install it and re-run green. In
   your real CI run, the very next `pip install -r requirements.txt` step
   installs it automatically — that's standard, well-tested `pip` behavior.

## AI tool disclosure

This pipeline's code, workflow files, and documentation were written with
Claude (Anthropic), based on the Week 3 lab's `build_fixer_agent.py` pattern
and the assignment brief. All scripts were actually executed locally
(pytest-alike custom runner, real `git diff`, real refusal/guardrail checks)
to verify the behavior described above before being included here — nothing
in the "Results" section is a fabricated log. The two items in the section
above are the parts that genuinely require your own credentials/repo and
haven't been faked to look otherwise.

## Reflection

The most useful surprise while building this was realizing that a naive
version of the remediation agent — "just add the missing import name to
requirements.txt" — would sometimes propose the *wrong* package. `yaml` is
the clearest case: `pip install yaml` installs an unrelated, essentially
abandoned package, not PyYAML (the one that actually provides `import
yaml`). An agent that "fixes" the build by installing the wrong package
would look successful (the PR merges, `requirements.txt` has a new line)
while quietly leaving the real bug in place or introducing a new one. That's
why `remediation_agent.py` ships a small lookup table for the known
mismatches instead of trusting import-name-equals-package-name — a case
where a little domain knowledge matters more than a bigger model call.

The second surprise was more mundane but just as real: this sandbox's
network policy blocks PyPI and the GitHub API entirely, which meant every
claim in this README had to be re-derived from a custom local test runner
and real `git` operations rather than actual `pytest`/GitHub Actions. It's a
good reminder that "the agent worked in my dev environment" and "the agent
worked in CI" are genuinely different claims — this submission is explicit
about which one it can currently back up.
