# Contributing

Thanks for considering a contribution. This project is small and opinionated:
read the two rules below before sending a PR, they explain most review comments.

## Setup

```bash
git clone https://github.com/DanJiabi/myastro && cd myastro
pip install -e ".[test]"                # pytest, pytest-asyncio, ruff, pyflakes
git config core.hooksPath githooks      # versioned pre-push gate
pytest -q                               # 372 tests, offline, ~35 s
pytest -m "unit or guards" -q           # fast lane, ~3 s
```

The pre-push hook resolves its own interpreter (`MYASTRO_ENV_BIN` → `.myastro-env`
→ active venv → `.venv` → PATH, each pre-flighted) and never pipes output.

## Rule 1 — tests are organised by design, and they must be able to fail

Layers (`tests/<layer>/`) mirror the architecture:

| Layer | May touch | Must not touch |
|---|---|---|
| `unit` | pure logic | db, network, TUI |
| `kernel` | real SQLite in tmp | real network (stub the `_download_*`) |
| `sources` | source modules | real network |
| `facade` | `import myastro as ma` only | kernel internals |
| `ui` | headless Textual | real network / real downloads |
| `cli` | `cli.main([...])` + capsys | real network, repo docs |
| `guards` | static invariants | — |

- Every test carries exactly one `@pytest.mark.cap("<capability id>")`; ids live in
  `src/myastro/io/testmap.py` and are explained in `docs/capabilities.md`.
- **A regression test must be able to go red.** Break the fix on purpose, watch the
  test fail, then restore it. Tests that cannot fail are treated as bugs.
- No pipes in CI or hooks (`pytest | tail` hides the exit code — we have been bitten).

## Rule 2 — docs and registries are generated or guarded

- `myastro test-map` regenerates `docs/test-map.md`; `myastro doc-sync` regenerates the
  source matrix in `docs/design-io.md`. Guards fail when they are stale.
- Adding a source means: `SOURCES` + a task in `TASKS` (or `URL_SOURCES`) + descriptor;
  drift between registries is guarded in `tests/guards/`.
- User-facing docs are bilingual: `docs/en/<name>.md` and `docs/zh/<name>.md` must both
  exist with the same heading structure. Developer docs are Chinese.
- Never document a path or symbol that does not exist — a guard checks `file::symbol`
  references in `docs/`.

## Commits and PRs

- Conventional-commit style subjects (`fix(search): …`, `feat(ops): …`, `docs: …`),
  body explains **why** and cites evidence (measurements, failing tests).
- Keep commits self-contained: each one should pass the full gate.
- PRs: describe the problem, the approach, and how you verified it (commands + output).
  If you touched a pipeline stage, update `docs/processing.md`.

## Reporting bugs

Use the issue template and include `myastro doctor` output (it redacts nothing
sensitive — no paths are personal unless you keep data in odd places).
