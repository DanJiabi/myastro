# myastro

[![CI](https://github.com/DanJiabi/myastro/actions/workflows/ci.yml/badge.svg)](https://github.com/DanJiabi/myastro/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/myastro.svg)](https://pypi.org/project/myastro/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**A personal astronomy data toolkit with a memory.** Fetch from public surveys and
keep a local ledger of *what you already have* — so you stop re-downloading the same sky.

`myastro` answers questions plain query tools don't:

- "Have I already downloaded this patch of sky?" → precise cone search over your ledger
- "How much of the brick/field index is local?" → coverage against a full catalogue
- "Which files rotted on disk?" → sha256 baseline audit
- "Is it still fetchable?" → deduplicated fetches plus source probes

Three entry points, one contract:

| Entry point | Use |
|---|---|
| Library | `import myastro as ma` — the only public import (`ma.__all__`) |
| CLI | `myastro fetch / search / coverage / audit / doctor / backup …` |
| TUI | `myastro top` — jobs / storage / sources, no config file needed |

> Status: **0.3.0 — alpha**. The facade is the public API; `myastro.io.*` is internal
> and may change. Breaking changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Install

```bash
pip install myastro                      # from PyPI
pip install -c constraints.txt myastro   # with known-good dependency versions
pip install "myastro[processing]"        # + photometry/imaging deps (planned P2/P3)
myastro doctor                           # self-check: deps, paths, ledger, filesystem
```

Python ≥ 3.11. macOS and Linux are supported; Windows is untested (scheduling is
macOS/Linux only). Optional extras: `[processing]`, `[asassn]`, `[ztfquery]`.

**Optional system dependency — `aria2`** (bulk downloads only: Legacy bricks, ZTF
frames, YAML manifests; the other eight sources are pure Python):

```bash
brew install aria2          # macOS
sudo apt install aria2      # Debian/Ubuntu   (dnf / pacman on Fedora / Arch)
```

You do not have to start the daemon: on first use myastro launches `aria2c --enable-rpc`
itself. It authenticates with `MYASTRO_ARIA2_SECRET` (default `myastro-legacy`, port
`MYASTRO_ARIA2_PORT`, default 6800) — set the variable if you run your own daemon with a
different secret. `myastro doctor` reports all of this.

## Quick start

```python
import myastro as ma

# 1) fetch — deduplicated: the same params never hit the network twice
r = ma.fetch("tess", target="WASP-12", sector=20)
print(r.paths[0])

# 2) what do I already have near this position?
for hit in ma.search(near=(97.6367, 29.6723), radius_deg=0.5):
    print(f"{hit['source']:10s} sep={hit['sep_deg']:.4f}°  {hit['path']}")

# 3) coverage against a full catalogue index
print(ma.coverage("legacy-bricks"))      # {'local': 7, 'total': 366912, ...}

# 4) integrity: build a sha256 baseline, then detect silent corruption
print(ma.audit())
```

Data root defaults to `~/myastro-data`; the ledger defaults to
`~/.local/state/myastro/astro.db`. Both are overridable:

```bash
export MYASTRO_DATA=/path/to/your/data               # may live on a NAS
export MYASTRO_DB=~/.local/state/myastro/astro.db    # must be a LOCAL disk (SQLite WAL)
```

Keeping the ledger local while data lives on a NAS is the intended layout —
`myastro doctor` fails when the ledger sits on NFS/CIFS.

## CLI

```bash
myastro init                               # create data root + ledger (idempotent)
myastro doctor                             # environment self-check (exit 1 if broken)
myastro backup --out ~/myastro-backup      # online SQLite backup + manifest
myastro restore ~/myastro-backup/<stamp> --force   # refuses to overwrite unless --force
myastro fetch tess --target "WASP-12" --sector 20  # args generated from descriptors
myastro jobs / wait / retry / delete / retry-batch
myastro search --near 196.18 33.35 --radius 0.2
myastro coverage legacy-bricks
myastro audit                              # sha256 baseline / corruption report
myastro index list | index update <name>   # local indexes (Legacy bricks, ZTF fields)
myastro health | schedule install health   # source probes, launchd (macOS)
myastro top                                # TUI
```

Exit codes are a contract, so scripts can branch:
`0` ok · `1` partial failure / doctor found problems · `2` bad parameter ·
`3` not found · `4` network · `5` state not allowed · `130` interrupted.

## What's inside

- **Ledger** — every fetch is a job; datasets, files, parameters, provenance and
  coordinates are recorded. Data files are the truth, the ledger is the index.
- **Deduplication** — cache key is a normalized `(source, params)` hash: the same
  request never hits the network twice; cache hits return the original metadata.
- **10 sources** — TESS light curves, Gaia DR3 cones, ZTF frames / metadata / light
  curves, MPC ephemerides, SIMBAD, VizieR, Legacy Surveys tractor bricks, unWISE
  cutouts, plus YAML manifests for bulk URL lists.
- **Precise cone search** — coordinates are resolved at ingest time (params → meta →
  index lookup → filename fallback), stored in the ledger, then queried with a
  bounding box plus haversine refinement and sorted by separation.
- **Local indexes** — 366k Legacy bricks and 1776 ZTF fields, cached in memory and
  searched with binary search (sub-millisecond per keystroke in the TUI).
- **Verifiability** — a capability matrix (`docs/capabilities.md`), a generated test
  map (`docs/test-map.md`) and design guards: tests fail when docs or registries drift.

## Documentation

| Document | Language | Audience |
|---|---|---|
| [Install](docs/en/install.md) · [Quick start](docs/en/quickstart.md) | EN | users |
| [安装](docs/zh/install.md) · [快速上手](docs/zh/quickstart.md) | 中文 | 用户 |
| [capabilities.md](docs/capabilities.md) | 中文 | roadmap: what exists, at which maturity |
| [processing.md](docs/processing.md) | 中文 | pipeline behaviour and failure semantics |
| [design-io.md](docs/design-io.md) · [design-top.md](docs/design-top.md) | 中文 | layer design and decisions |
| [testing.md](docs/testing.md) · [test-map.md](docs/test-map.md) | 中文 | test layers, guards, generated map |
| [release.md](docs/release.md) | 中文 | release process and public-mirror model |

Developer docs are maintained in Chinese; user-facing docs are bilingual.

## Development

```bash
git clone https://github.com/DanJiabi/myastro && cd myastro
pip install -e ".[dev]"                 # or: pip install -e . pytest ruff pyflakes ztfquery
git config core.hooksPath githooks      # versioned pre-push gate (full suite + pyflakes)
pytest -q                               # 372 tests, offline (network is stubbed)
pytest -m "unit or guards" -q           # fast lane (~3 s)
myastro test-map && myastro doc-sync    # regenerate docs (guards fail when stale)
```

> `requirements-lock.txt` is the maintainer's conda environment record (it contains
> conda `file://` sources, so it is not a pip lock file). For reproducible pip installs
> use `constraints.txt`.

The pre-push hook resolves a usable interpreter itself (`MYASTRO_ENV_BIN` →
`.myastro-env` → active venv → `.venv` → PATH, each pre-flighted with
`pytest --collect-only`) and never pipes command output, so a red suite cannot slip through.

## Data, privacy, credentials

- Everything stays on your machine: no telemetry, no account, no upload.
- Downloads use public survey endpoints (MAST, IRSA, VizieR, SIMBAD, NERSC, unwise.me).
  ZTF metadata via IRSA may benefit from a free account configured in your own tooling —
  **myastro never stores credentials**.
- Survey data belongs to the surveys; this tool only fetches it. Cite the surveys you use.

## License

MIT — see [LICENSE](LICENSE).

<sub>中文说明见 [README.zh-CN.md](README.zh-CN.md)。</sub>
