# myastro

Personal astronomy data toolkit with a ledger: what you already have, how it was
fetched, and whether it is still on disk. Python API + CLI + TUI.

## What it does

- **Fetch** from 10 public surveys (TESS, Gaia, ZTF metadata/light curves/frames,
  Legacy Survey bricks, MPC, SIMBAD, VizieR, unWISE, ASAS-SN when upstream is up).
- **Ledger**: every dataset is recorded (source, params, files, sha256 baseline) in
  local SQLite — dedup, retry, audit and coverage all build on it.
- **Find your own data**: precise cone search, keyword search, coverage against
  catalogue indexes.
- **Audit**: hash baseline checks, orphan detection, `doctor` self-check, ledger
  backup/restore.
- **Extend**: third-party sources go through the plugin protocol ([plugin API](../zh/dev/plugin-api.md), Chinese).

## Install

```bash
pip install myastro
```

Requires Python ≥ 3.11 (macOS/Linux; Windows untested). Optional extras and the
`aria2` system dependency are covered in [Install](install.md).

## Next steps

- [Install](install.md) — extras, `aria2`, environment variables
- [Quickstart](quickstart.md) — first fetch, the TUI, searching your archive

## Source and issues

- Repository: <https://github.com/DanJiabi/myastro>
- Changelog: <https://github.com/DanJiabi/myastro/blob/main/CHANGELOG.md>
- License: MIT
