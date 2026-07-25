# Guardrails

Two agents run in this pipeline. Each has a hard scope boundary and neither can merge anything.

## 1. `scripts/select_tests.py` (test-impact analysis — not really an "agent," but has a blast radius)

**What it can affect:** which tests run this build. Nothing else.

**Failure mode we're guarding against:** skipping a test that should have run (a false negative), which could let a real regression merge unnoticed. This is worse than the alternative failure mode (running extra tests, which only costs CI minutes) — so every rule is written to fail toward "run more," never "run less."

**Guardrail:** any changed file the mapping rules don't recognize with high confidence — `requirements.txt`, `conftest.py`, `pytest.ini`, `setup.cfg`, `pyproject.toml`, or literally anything else not matched by the `src/<name>.py → tests/test_<name>.py` convention — forces a full-suite run. Verified in `README.md` (Case C, Case E): a `requirements.txt` change and an unrecognized `README.md` change both correctly fall back to `tests/` (everything), not a narrower set.

**What it cannot do:** it cannot exclude a test based on anything except the changed-files list; it has no access to historical flake data, coverage maps, or "trust me" overrides. If a future contributor wants a smarter mapping (e.g. real import-graph analysis), that's a separate, reviewable change to this file — not something the tool can decide for itself at runtime.

## 2. `scripts/remediation_agent.py` (auto-remediation agent)

**Scope, explicitly:** one failure class — `ModuleNotFoundError` for a third-party package missing from `requirements.txt`. Nothing else.

**Blast radius:** the only file it can ever write is `requirements.txt`, and the only edit it can make is *appending* one line. It cannot reorder or delete existing entries, and it cannot touch `src/`, `tests/`, workflow files, or anything else. This is enforced in code (`propose_fix()` only ever returns a `fixed_file_path` of `requirements.txt`), not just asked for in a prompt.

**Refusal behavior (verified, not assumed):** run against a build log for the calculator logic bug (an `AssertionError`, not a `ModuleNotFoundError`), the agent printed `REFUSING TO ACT: build log does not match this agent's scope` and exited with code `2` — it proposed nothing rather than guessing. Run against a log where the missing package is already present in `requirements.txt`, it also refuses (`already_satisfied()` check), on the theory that a second, unrelated cause must be responsible and this agent isn't equipped to diagnose it.

**Human-in-the-loop, not human-notified-after-the-fact:** the agent's only paths are (a) write `fix_proposal.md` locally / as a workflow artifact for a human to read (dry-run / no GitHub credentials), or (b) open a PR that lands in the same `agent-proposed` GitHub Environment as the Week 3 lab, which requires a **Required reviewer** approval before the job — and therefore before any merge — can proceed. The agent's GitHub token is scoped to open PRs only; it is never given merge rights. Nothing in this repo auto-merges on a timeout; an unattended approval gate should time out to **abort**, never to **approve**.

**LLM usage is optional, not load-bearing, for this failure class.** When `ANTHROPIC_API_KEY` isn't set, the fix is produced by a small deterministic lookup table (import name → PyPI package name) — not an LLM guess. When the key *is* set, Claude only drafts the PR's prose description and sanity-checks the proposed one-line diff; it cannot change what gets written to `requirements.txt`. See `README.md`'s reflection section for why this failure class specifically doesn't need an LLM in the loop to be correct.

## Shared guarantees across both agents

- Neither agent can push directly to a protected branch or call a merge API. GitHub branch protection on `main` (require PR + review) is assumed to be turned on independent of anything these scripts do — the scripts' own restraint is a second layer, not the only layer.
- Every agent action is logged to a JSON artifact (`select_tests_decision.json`, `remediation_result.json`) so a reviewer can reconstruct *why* a decision was made after the fact, not just *what* the decision was.
- Refusing to act is a valid, expected, and tested outcome for both scripts — not an edge case that was left unhandled.
