"""
Load the catalog of every active resource with hats, and report whether it is reachable and
how long it takes to load.
"""

import sys
import time
from pathlib import Path
from xml.etree import ElementTree

import hats
import tabulate
from hats.catalog.catalog_collection import CatalogCollection
from tqdm import tqdm

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"


def resource_groups(resources_dir):
    """Yield every directory of resources, e.g. "data.lsdb.io", that holds an XML file."""
    for path in sorted(resources_dir.iterdir()):
        if path.is_dir() and any(path.rglob("*.xml")):
            yield path


def read_active_resources(resource_dir):
    """Yield the name and access URL of every active resource in resource_dir."""
    for path in sorted(resource_dir.rglob("*.xml")):
        root = ElementTree.parse(path).getroot()
        if root.get("status") == "active":
            yield path.stem, (root.findtext(".//accessURL") or "").strip()


def read_catalog(url):
    """Read a HATS catalog, resolving a collection to its main catalog."""
    catalog = hats.read_hats(url)
    return catalog.main_catalog if isinstance(catalog, CatalogCollection) else catalog


def check_resources(resource_dir):
    """
    Load the catalog of every active resource in resource_dir, print a row per resource with
    its load time, and return the ones that could not be loaded.
    """
    report, failures = [], []
    for name, url in tqdm(list(read_active_resources(resource_dir)), desc="Checking catalogs"):
        start = time.perf_counter()
        try:
            properties = read_catalog(url).catalog_info.extra_dict()
        except Exception as e:
            report.append([name, "", "", "", "FAILED"])
            failures.append([name, url, e])
            continue

        load_time = time.perf_counter() - start
        report.append(
            [
                name,
                f"{load_time:.1f}",
                properties.get("hats_builder", "UNKNOWN"),
                properties.get("hats_creation_date", "UNKNOWN"),
                "OK",
            ]
        )

    report.sort(key=lambda row: (row[-1] != "OK", row[0]))
    headers = [
        "resource",
        "load time (s)",
        "builder",
        "catalog creation date",
        "status",
    ]
    print(tabulate.tabulate(report, headers=headers))
    print(f"\n{len(failures)} FAILED, {len(report) - len(failures)} OK")
    return failures


def run():
    """Check every group of resources, and fail if any catalog could not be loaded."""
    failures = []
    for group in resource_groups(RESOURCES_DIR):
        print(f"\n=================  {group.name}  =================\n")
        failures += [[group.name, *failure] for failure in check_resources(group)]

    if failures:
        print(f"\nThere were problems with {len(failures)} resource(s):")
        headers = ["resource_group", "resource", "access URL", "error"]
        print("\n" + tabulate.tabulate(failures, headers=headers))
        sys.exit(1)
    print("\nEvery resource is reachable.")


if __name__ == "__main__":
    run()
