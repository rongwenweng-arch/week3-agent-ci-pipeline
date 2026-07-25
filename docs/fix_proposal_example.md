# Agent-Proposed Fix (dry run)

**Root cause:** Test collection failed with ModuleNotFoundError: No module named 'toml'. 'toml' is imported by the source under test but is not declared in requirements.txt, so a clean install (as CI does) never installs it.

**Change:** Append 'toml' to requirements.txt. No other file is touched.

Append 'toml' to requirements.txt. No other file is touched.

```diff
 pytest
+toml
```
