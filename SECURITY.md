# Security

## What myastro touches

- **Network**: only public survey endpoints (MAST, IRSA, VizieR, SIMBAD, NERSC,
  unwise.me) over HTTPS. No telemetry, no upload of your data or ledger.
- **Filesystem**: your data root and the SQLite ledger. Artifacts are written with
  `atomic_write` and every path is verified to stay **inside the data root**.
- **Credentials**: myastro never stores or reads credentials. If you configure an
  IRSA account for ZTF metadata, that lives in your own tooling (e.g. `~/.ztfquery`),
  not in this project.

## Reporting a vulnerability

Please report privately via GitHub's
[security advisory](https://github.com/DanJiabi/myastro/security/advisories/new)
rather than a public issue. Include steps to reproduce; expect an initial response
within two weeks.

## Scope notes

- Parameter handling is validated (no path traversal via name-like parameters, no
  silent no-op searches); bypasses of those checks are security-relevant.
- Anything that could cause writes outside `$MYASTRO_DATA`, or could make the ledger
  report data that is not on disk, counts as a vulnerability.
