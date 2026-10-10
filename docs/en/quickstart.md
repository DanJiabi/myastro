# Quick start

Five minutes from an empty machine to "this sky is already mine".

## 1. Install and self-check

```bash
pip install myastro
myastro init && myastro doctor
```

## 2. Fetch something

```python
import myastro as ma

r = ma.fetch("tess", target="WASP-12", sector=20)
print(r.paths[0])          # parquet with time/flux/flux_err/quality
```

Run it twice: the second call makes **zero** network requests (cache key =
normalized source + parameters) and still returns the original metadata.

## 3. Ask what you already have

```python
# precise cone search — coordinates are resolved at ingest time
for hit in ma.search(near=(97.6367, 29.6723), radius_deg=0.5):
    print(f"{hit['source']:10s} sep={hit['sep_deg']:.4f}°  {hit['path']}")

# text / time filters combine freely
ma.search(source="gaia", since="2026-01-01")
```

Search parameters are validated: a negative radius, a declination outside
`[-90, 90]`, `limit < 1` or a malformed date raise an error instead of silently
returning nothing.

## 4. Measure coverage against a full catalogue

```bash
myastro index update legacy-bricks     # 366k bricks, ~104 MB, once
myastro coverage legacy-bricks
```

```python
ma.coverage("legacy-bricks")   # {'local': n, 'total': 366912, 'ratio': ...}
```

## 5. Verify what is on disk

```bash
myastro audit        # first run builds the sha256 baseline
myastro audit        # later runs report missing / size mismatch / corrupt
```

## 6. Browse it all in the TUI

```bash
myastro top
```

| Key | Action |
|---|---|
| `0` / `1` / `2` | data sources / jobs / storage |
| `enter` | drill into a row (storage → assets), or open details |
| `F1` / `F2` | new download / prefill the form from the selected job |
| `F12` | batch order (sources with an index field) |
| `s` | toggle sort, `f` cycle job filter, `x` cancel, `F5` retry, `F4` quit |

## 7. Keep the ledger safe

```bash
myastro backup --out ~/myastro-backup     # online SQLite backup + manifest
myastro restore ~/myastro-backup/<stamp> --force
```

Data files can be re-downloaded; the ledger (what you fetched, with which
parameters, plus the sha baselines) cannot. Back it up.

## Where next

- [capabilities.md](../capabilities.md) — what exists, at which maturity (中文)
- [processing.md](../processing.md) — pipeline behaviour and failure semantics (中文)
- Notebooks under `notebooks/` show end-to-end analyses (outputs cleared).
