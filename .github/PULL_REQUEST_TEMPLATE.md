## Problem

<!-- What is broken or missing? Link the issue if there is one. -->

## Approach

<!-- Why this way? What alternatives did you reject? -->

## Verification

<!-- Commands you ran and what they printed. For a regression fix: which test goes red
     without the fix? Which mutation did you try? -->

- [ ] `pytest -q` passes (full suite)
- [ ] `ruff check src tests` and `pyflakes src tests` are clean
- [ ] `myastro test-map --check` and `myastro doc-sync` are up to date
- [ ] New/changed behaviour is documented (`docs/zh/dev/processing.md` for pipeline stages)
- [ ] Regression tests verified to fail without the fix
