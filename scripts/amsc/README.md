# AmSC Data Catalog

## populate_amsc.py

This registers the same data.lsdb.io catalogs as [`from_catalogs_json.py`](../from_catalogs_json.py) in the
HATS/LSDB public catalog of an AmSC data catalog, through the AmSC API. It writes no resource files. Everything
goes under a `uw` `scientificWork` for the data.lsdb.io source. Each data.lsdb.io folder (e.g. `Gaia`) becomes
an `artifactCollection` under it, each catalog an `artifactCollection` named after its `catalog.json` id, and
each of its HATS tables (primary catalog, margins and indexes) an `artifact`.

It uses `amsc-client`, which isn't on PyPI, so it's not a dependency in `pyproject.toml`. Its own
[requirements file](requirements.txt) lists it with the GitLab registries that host it and its AmSC
dependencies. From the root of this repository:

```
pip install -r scripts/amsc/requirements.txt
```

Then, with the local AmSC data catalog running:

```
export AMSC_TOKEN=$(<amsc-data-catalog-local>/scripts/get-token.sh)
python scripts/amsc/populate_amsc.py --dry_run   # print what would be registered
python scripts/amsc/populate_amsc.py             # register new catalogs
python scripts/amsc/populate_amsc.py --update    # also update the ones already registered
```

It reads data.lsdb.io from the same place as `from_catalogs_json.py` (or `--data_dir`), and registers into
the local AmSC API and `hats-public-repository.hats-public-catalog` by default (or `--api` and `--catalog`). To register some catalogs only, pass their ids with `--only`, comma-separated.
