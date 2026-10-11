# Install

## Requirements

- Python **3.11+**
- macOS or Linux (Windows is untested; scheduling is macOS/Linux only)
- The ledger must live on a **local disk** (SQLite WAL does not work on NFS/CIFS).
  Data files may live on a NAS.

## Install the package

```bash
pip install myastro
```

Reproducible install (known-good versions used during development):

```bash
pip install -c constraints.txt myastro
```

Optional extras:

| Extra | Adds | Needed for |
|---|---|---|
| `processing` | photutils, astroalign, ccdproc, scipy, matplotlib, skyfield | the notebooks, planned photometry/imaging |
| `asassn` | pyasassn | the dormant ASAS-SN source |
| `ztfquery` | ztfquery | building the ZTF field index locally |

```bash
pip install "myastro[processing]"
```

## Configure paths

The defaults are:

| What | Default | Override |
|---|---|---|
| Data root (FITS/parquet) | `~/myastro-data` | `MYASTRO_DATA` |
| Ledger (SQLite) | `~/.local/state/myastro/astro.db` | `MYASTRO_DB` |

```bash
export MYASTRO_DATA=/path/to/your/data      # e.g. a NAS mount
export MYASTRO_DB=~/.local/state/myastro/astro.db
```

Add those lines to your shell profile if you keep data outside the default.

## First run

```bash
myastro init      # create the data root and the ledger (idempotent)
myastro doctor    # self-check; exits 1 when something is actually broken
```

`doctor` verifies dependencies (including `transitleastsquares >= 2.0`), that the
data root and ledger directory are writable, the ledger schema version, the
**filesystem of the ledger** (NFS/CIFS → failure), a sample of recorded files,
which indexes are built, and platform capabilities.

## Upgrade / uninstall

```bash
pip install -U myastro     # upgrade; the ledger migrates itself on next open
pip uninstall myastro      # code only — your data root and ledger are untouched
```

Before upgrading a large ledger, take a backup:

```bash
myastro backup --out ~/myastro-backup
```

## Optional: aria2 (bulk downloads)

Only three things need it — Legacy Survey bricks, ZTF science frames, and YAML
manifests. TESS, Gaia, ZTF metadata/light curves, MPC, SIMBAD, VizieR and unWISE are
pure Python and work without it.

```bash
brew install aria2          # macOS
sudo apt install aria2      # Debian/Ubuntu
```

You normally do **not** start the daemon yourself: myastro spawns
`aria2c --enable-rpc` on first use (detached) and keeps using it. Configuration:

| Variable | Default | Meaning |
|---|---|---|
| `MYASTRO_ARIA2_SECRET` | `myastro-legacy` | RPC token; must match your daemon's `--rpc-secret` |
| `MYASTRO_ARIA2_PORT` | `6800` | RPC port |

If you prefer running the daemon yourself, `myastro doctor` prints the exact command
(including the secret it expects) in its aria2 line.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `aria2` reported as missing but you only fetch TESS/Gaia/etc. | Harmless — those sources do not use it. Install it when you need Legacy/ZTF frames. |
| `doctor` reports "账本文件系统: nfs" | The ledger is on a network filesystem. Move `MYASTRO_DB` to a local disk. |
| `doctor` reports a missing optional dependency | Install the matching extra, e.g. `pip install "myastro[ztfquery]"`. |
| Fetch fails with a network error after retries | The survey endpoint is down or unreachable — check `myastro health`. |
| A `UserWarning` about lightkurve's `tpfmodel`/`oktopus` | Upstream notice about an optional lightkurve submodule myastro never uses. Ignore it (myastro suppresses it on its own import paths). |
| `myastro test-map` / `doc-sync` exit with code 2 | They only work inside a source checkout, not from an installed wheel. |
