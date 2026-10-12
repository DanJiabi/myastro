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
  `src/myastro/io/testmap.py` and are explained in `docs/zh/dev/capabilities.md`.
- **A regression test must be able to go red.** Break the fix on purpose, watch the
  test fail, then restore it. Tests that cannot fail are treated as bugs.
- No pipes in CI or hooks (`pytest | tail` hides the exit code — we have been bitten).

## Rule 2 — docs and registries are generated or guarded

- `myastro contract-snapshot` regenerates `docs/contract-snapshot.json` (facade API, CLI
  commands and options, exit codes, ledger schema, registries). A guard fails on any
  drift and points at the exact leaf path; **every contract change must be regenerated
  and recorded in `docs/zh/dev/contract-changelog.md`**.
- `myastro test-map` regenerates `docs/zh/dev/test-map.md`; `myastro doc-sync` regenerates the
  source matrix in `docs/zh/dev/design-io.md`. Guards fail when they are stale.
- Adding a source means: `SOURCES` + a task in `TASKS` (or `URL_SOURCES`) + descriptor;
  drift between registries is guarded in `tests/guards/`.
- User-facing docs are bilingual: `docs/en/<name>.md` and `docs/zh/<name>.md` must both
  exist with the same heading structure. Developer docs are Chinese.
- Never document a path or symbol that does not exist — a guard checks `file::symbol`
  references in `docs/`.

## Rule 3 — pick the change class before you edit

Structural churn is the main source of regressions in this repo (measured: 67 of 163
commits touched the structural core, and on the busiest repair day 6 of 7 structural
commits were fixes). So decide the class **first** — full policy and rationale live in
`docs/zh/dev/change-policy.md` (Chinese; this is the short version):

| Class | What | Budget | Process |
|---|---|---|---|
| **L1 local** | no observable contract change: a new source, a single-file fix, docs, tests | ≤3 files, ≤150 lines | just do it, run the gates |
| **L2 contract** | facade `__all__`/signatures, descriptors, CLI commands/exit codes, ledger schema, registries, error taxonomy | ≤6 files, **one contract point** | design note first (blast radius + compatibility) → approval → implement; append a row to `docs/zh/dev/contract-changelog.md` |
| **L3 structural** | layering, job lifecycle, locking/atomicity, TUI render core, file layout | 1 subsystem + 1 invariant | design first (invariants + failure-mode tests) → approval → **three commits**: guard/tests → implementation → migration; at most **one L3 per release**, then a freeze release |

Hard rules that came out of real incidents:

1. **One intent per commit.** Never mix a mechanical rewrite with a semantic change.
2. **Bulk/mechanical rewrites** need an AST-level equivalence proof and point-by-point
   review (see how `tests/kernel/test_db.py` proves structural equivalence).
3. **Cross-cutting semantics** (locks, transactions, concurrency, lifecycle) need a
   regression test that goes red without the fix (mutation-verified), at least two
   interleaving scenarios, and an explicit statement of the residual boundary.
4. **Changes to the user's environment** (default paths, external binaries, secrets)
   need a "what you must do" line at the top of the CHANGELOG entry.

When in doubt, treat it as L2.

## Rule 4 — third-party sources go through the plugin protocol

`docs/zh/dev/plugin-api.md` defines plugin protocol v1: a plugin registers a **named task**
(`myastro.register_task`) plus a `SourceDescriptor` (`myastro.register_source`). Registration
validates eagerly and refuses to shadow built-ins. Two things matter for contributions here:

- Guards and the contract snapshot bind **built-ins only** (`BUILTIN_SOURCES` / `BUILTIN_TASKS`);
  installing a plugin must never turn `pytest` or `contract-snapshot --check` red.
- New built-in sources must satisfy the same validation as plugins (they are the reference
  implementation of the protocol) — `tests/kernel/test_plugin_contract.py` asserts that.

## Commits and PRs

- Conventional-commit style subjects (`fix(search): …`, `feat(ops): …`, `docs: …`),
  body explains **why** and cites evidence (measurements, failing tests).
- Keep commits self-contained: each one should pass the full gate.
- PRs: describe the problem, the approach, and how you verified it (commands + output).
  If you touched a pipeline stage, update `docs/zh/dev/processing.md`.

## Reporting bugs

Use the issue template and include `myastro doctor` output (it redacts nothing
sensitive — no paths are personal unless you keep data in odd places).
