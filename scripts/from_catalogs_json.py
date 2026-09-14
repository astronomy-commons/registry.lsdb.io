"""
Generate the registry's VOResource XML files from the catalogs in data.lsdb.io.

See scripts/README.md for how resources are named, refreshed and deleted.
Install its dependencies with `pip install -e '.[dev]'` from the root of the repository.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import hats
import tabulate
from hats.catalog.catalog_collection import CatalogCollection
from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Environment(loader=FileSystemLoader(ROOT_DIR / "templates"))
TIMESTAMP = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

# Hosts of the catalogs we register, mapped to their (location, short location).
LOCATIONS = {"data.lsdb.io": ("UW/Epyc", "uw")}

# Format of the catalog ids set in data.lsdb.io.
ID_PATTERN = re.compile(r"[a-z0-9_]+")


class ResourceError(Exception):
    """Raised when the resources can't be written without breaking the registry."""


@dataclass
class Catalog:
    """A catalog from data.lsdb.io to be registered."""

    label: str  # Its directory in data.lsdb.io, e.g. "ZTF/ZTF_DR14_(objects)".
    info: dict  # The contents of its catalog.json.
    url: str
    location: str
    short_location: str

    @property
    def id(self):
        """The catalog's id in data.lsdb.io, which names its resource file."""
        return self.info.get("id")

    @property
    def identifier(self):
        """The IVOA identifier of the catalog's resource."""
        return f"ivo://data.lsdb/{self.short_location}/{self.id}"


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


def read_resources(resource_dir):
    """Map the name of each resource in resource_dir, active or deleted, to its metadata."""
    resources = {}
    for path in sorted(resource_dir.glob("*.xml")):
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as e:
            e.add_note(f"While reading {path}")
            raise
        resources[path.stem] = {
            "name": path.stem,
            "status": root.get("status"),
            "created": root.get("created"),
            **{tag: root.findtext(tag) for tag in ("title", "shortName", "identifier")},
        }
    return resources


def render_resource(catalog, existing, short_name_max):
    """Render the XML resource of a catalog, reading its properties with hats."""
    hats_catalog = hats.read_hats(catalog.url)
    if isinstance(hats_catalog, CatalogCollection):
        hats_catalog = hats_catalog.main_catalog
    properties = hats_catalog.catalog_info.extra_dict()

    other_urls = catalog.info.get("other_urls", [])
    return TEMPLATES.get_template("vo-registry.xml.jinja").render(
        name=catalog.info.get("name", ""),
        description=catalog.info.get("description", ""),
        accessUrl=catalog.url,
        referenceUrl=other_urls[0]["url"] if other_urls else "",
        shortName=catalog.id[:short_name_max],
        identifier=catalog.identifier,
        location=catalog.location,
        wavebands=properties.get("obs_regime", "Optical").split(" "),
        created=existing["created"] if existing else properties.get("hats_creation_date", TIMESTAMP),
        updated=TIMESTAMP,
        all_sky=float(properties.get("moc_sky_fraction", 0.0)) == 1.0,
    )


def _duplicates(values_by_key):
    """Map each value shared by several keys to those keys."""
    keys_by_value = defaultdict(list)
    for key, value in sorted(values_by_key.items()):
        keys_by_value[value].append(key)
    return {value: keys for value, keys in keys_by_value.items() if len(keys) > 1}


def find_problems(catalogs, resources, to_render, retired):
    """
    List what would break the registry: invalid or duplicated catalog ids, deleted records that
    would overwrite another file, and identifiers that several resources would share once written.
    """
    problems = [
        f"{catalog.label} has an invalid id: {catalog.id!r}"
        for catalog in catalogs
        if not (isinstance(catalog.id, str) and ID_PATTERN.fullmatch(catalog.id))
    ]
    for catalog_id, labels in _duplicates({catalog.label: catalog.id for catalog in catalogs}).items():
        problems.append(f"{catalog_id} is the id of {', '.join(labels)}")
    if problems:
        return problems

    taken_names = resources.keys() | {catalog.id for catalog in catalogs}
    for name, old in retired.values():
        if name in taken_names:
            problems.append(
                f"{name}.xml can't be the deleted record of {old['identifier']}: the name is taken"
            )

    identifiers = {name: resource["identifier"] for name, resource in resources.items()}
    identifiers |= {catalog.id: catalog.identifier for catalog in to_render}
    identifiers |= {name: old["identifier"] for name, old in retired.values()}
    for identifier, names in _duplicates(identifiers).items():
        problems.append(f"{identifier} would be the identifier of {', '.join(f'{n}.xml' for n in names)}")
    return problems


def run(data_dir, resource_dir, short_name_max=16, refresh_resources=False, rerender_list=()):
    """
    Write a resource for every new catalog (and every existing one, if refreshing), and write
    deleted records for the resources of catalogs that are no longer registered, and for old
    identifiers of re-rendered resources.

    Raises a ResourceError, before writing any file, if that would break the registry.
    """
    report = []
    catalogs = read_catalogs(data_dir, report)
    resources = read_resources(resource_dir)
    active = {name: resource for name, resource in resources.items() if resource["status"] == "active"}

    to_render = []
    for catalog in catalogs:
        if catalog.id in active and not (refresh_resources or catalog.label in rerender_list):
            report.append([catalog.label, "", "skipped = existing"])
        else:
            to_render.append(catalog)

    # Deleted records to write, by file name. Resources of catalogs that are no longer registered
    # are marked as deleted in place. When a re-rendered resource gets a new identifier, the old one
    # is kept as a deleted record named after its last segment (by catalog id, until it's rendered).
    to_delete = {name: active[name] for name in active.keys() - {catalog.id for catalog in catalogs}}
    retired = {
        catalog.id: (active[catalog.id]["identifier"].rsplit("/", 1)[-1], active[catalog.id])
        for catalog in to_render
        if catalog.id in active and active[catalog.id]["identifier"] != catalog.identifier
    }

    if problems := find_problems(catalogs, resources, to_render, retired):
        raise ResourceError(
            "No resources were written, because of these problems:\n  " + "\n  ".join(problems)
        )

    for catalog in tqdm(to_render, desc="Rendering catalogs"):
        try:
            resource = render_resource(catalog, active.get(catalog.id), short_name_max)
        except Exception as e:
            report.append([catalog.label, "", e])
            continue
        (resource_dir / f"{catalog.id}.xml").write_text(resource, encoding="utf-8")
        report.append([catalog.label, "SUCCESS", ""])
        if catalog.id in retired:
            name, old = retired[catalog.id]
            to_delete[name] = old

    for name, old in sorted(to_delete.items()):
        record = TEMPLATES.get_template("vo-registry-deleted.xml.jinja").render(**old, updated=TIMESTAMP)
        (resource_dir / f"{name}.xml").write_text(record, encoding="utf-8")
        report.append([name, "REMOVED", old["identifier"]])

    print(tabulate.tabulate(report, headers=["label", "success", "exception notes"]))

    # Quickly validate that the new XML files can be read.
    read_resources(resource_dir)


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
        run(
            args.data_dir,
            args.out_dir,
            short_name_max=args.short_name_max,
            refresh_resources=args.refresh_resources,
            rerender_list=args.rerender_list.split(",") if args.rerender_list else [],
        )
    except ResourceError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
