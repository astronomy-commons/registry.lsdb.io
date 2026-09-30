"""
Generate the registry's VOResource XML files from the catalogs in data.lsdb.io.

See scripts/README.md for how resources are named, refreshed and deleted.
Install its dependencies with `pip install -e '.[dev]'` from the root of the repository.
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from common import LOCATIONS, ROOT_DIR, Catalog, ResourceError, run


def read_catalogs(data_dir, report):
    """Return the catalogs in data_dir to register, adding the ones that are skipped to the report."""
    catalogs = []
    for path in sorted(data_dir.rglob("catalog.json")):
        label = str(path.parent.relative_to(data_dir))
        info = json.loads(path.read_text(encoding="utf-8"))
        urls = info.get("urls", {})
        url = urls.get("collection") or urls.get("catalog")

        if info.get("skip_connectivity_check"):
            report.append([label, "", info["skip_connectivity_check"]])
        elif not url:
            report.append([label, "", "no catalog URL"])
        elif url.endswith(".parquet"):
            report.append([label, "", "single parquet file"])
        elif urlparse(url).hostname not in LOCATIONS:
            report.append([label, "", "not a LINCC Frameworks-controlled catalog"])
        else:
            catalogs.append(Catalog(label, info, url, *LOCATIONS[urlparse(url).hostname]))
    return catalogs


def main():
    """Parse the command-line arguments and generate the resources."""
    parser = argparse.ArgumentParser("vo-resource-gen")
    parser.add_argument(
        "--data_dir",
        type=Path,
        default=ROOT_DIR.parent / "data.lsdb.io" / "data",
        help="The data directory of data.lsdb.io, with a catalog.json per catalog.",
    )
    parser.add_argument(
        "--out_dir",
        type=Path,
        default=ROOT_DIR / "resources" / "data.lsdb.io",
        help="The directory to output records to.",
    )
    parser.add_argument(
        "--short_name_max", type=int, default=16, help="Maximum length of the VOResource short name."
    )
    parser.add_argument("--refresh_resources", action="store_true", help="Re-render existing resources too.")
    parser.add_argument(
        "--rerender_list", default="", help="Comma-separated labels of existing resources to re-render."
    )
    args = parser.parse_args()

    try:
        report = []
        catalogs = read_catalogs(args.data_dir, report)
        run(
            catalogs,
            args.out_dir,
            report=report,
            short_name_max=args.short_name_max,
            refresh_resources=args.refresh_resources,
            rerender_list=args.rerender_list.split(",") if args.rerender_list else [],
        )
    except ResourceError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
