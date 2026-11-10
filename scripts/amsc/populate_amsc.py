"""Register the HATS catalogs hosted on data.lsdb.io in the SLAC Cosmic public catalog.

Each catalog is registered under its data.lsdb.io folder:

    <catalog FQN>
    └── <folder>                scientificWork       e.g. Gaia
        └── <catalog.json id>   artifactCollection   HATS collection, or standalone catalog
            ├── <primary dir>   artifact             primary catalog
            ├── <margin dir>    artifact             one per margin
            └── <index dir>     artifact             one per index

Existing entities are skipped, or updated with --update. See scripts/amsc/README.md for setup and usage.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import batched
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urljoin, urlparse

from amsc_api_autogen.models import (
    Artifact,
    ArtifactCollection,
    CreateEntityTypeEnum,
    EntityTypeEnum,
    ScientificWork,
)
from amsc_client import Client
from amsc_client.core.exceptions import AmscError, NotFoundError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT.parent / "data.lsdb.io" / "data"
DEFAULT_CATALOG = "slac-cosmic-public-repository.slac-cosmic-public-catalog"
DEFAULT_API = "http://localhost:8000/api/current"

HOST = "data.lsdb.io"
PARQUET = "application/vnd.apache.parquet"
PROPERTY_FILES = ("hats.properties", "properties")


@dataclass
class HatsTable:
    """A primary catalog, margin or index of a data.lsdb.io catalog."""

    name: str
    url: str
    role: Literal["primary", "margin", "index"]
    properties: dict[str, str]
    index_column: str | None = None

    @property
    def size(self) -> int | None:
        """The estimated size in bytes (hats_estsize is in KiB)."""
        estsize = self.properties.get("hats_estsize")
        return int(estsize) * 1024 if estsize else None


@dataclass
class Catalog:
    """A catalog.json of data.lsdb.io, with the HATS tables read from its URL."""

    folder: str
    id: str
    title: str
    description: str
    url: str
    margin_url: str | None
    tables: list[HatsTable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def select_catalogs(data_dir: Path) -> tuple[list[Catalog], Counter]:
    """Return the catalogs to register, and how many were skipped for each reason."""
    catalogs, skipped = [], Counter()
    for path in sorted(data_dir.rglob("catalog.json")):
        info = json.loads(path.read_text(encoding="utf-8"))
        urls = info.get("urls", {})
        url = urls.get("collection") or urls.get("catalog")

        if info.get("skip_connectivity_check"):
            skipped["marked skip_connectivity_check"] += 1
        elif not url:
            skipped["no catalog URL"] += 1
        elif url.endswith(".parquet"):
            skipped["single Parquet file"] += 1
        elif urlparse(url).hostname != HOST:
            skipped[f"not hosted on {HOST}"] += 1
        else:
            title = info.get("name") or info["id"]
            catalog = Catalog(
                folder=path.relative_to(data_dir).parts[0],
                id=info["id"],
                title=title,
                description=info.get("description") or title,
                url=url.rstrip("/"),
                margin_url=urls.get("margin_catalog"),
            )
            catalogs.append(catalog)
    return catalogs, skipped


def by_folder(catalogs: list[Catalog]) -> dict[str, list[Catalog]]:
    """Group catalogs by folder, keeping their order."""
    folders = defaultdict(list)
    for catalog in catalogs:
        folders[catalog.folder].append(catalog)
    return folders


def read_properties(url: str) -> dict[str, str] | None:
    """Read a key=value properties file, or return None if there's none at url."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

    properties = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()
    return properties


def read_table(role: str, url: str, index_column: str | None = None) -> HatsTable:
    """Read the properties of the HATS catalog at url."""
    for filename in PROPERTY_FILES:
        properties = read_properties(f"{url}/{filename}")
        if properties is not None:
            return HatsTable(url.rsplit("/", 1)[-1], url, role, properties, index_column)
    raise FileNotFoundError(f"no HATS properties at {url}")


def list_tables(catalog: Catalog) -> list[tuple[str, str, str | None]]:
    """List the (role, URL, index column) of a catalog's HATS tables, primary first."""
    collection = read_properties(f"{catalog.url}/collection.properties")

    if collection is None:  # A standalone catalog, whose margin is in catalog.json.
        tables = [("primary", catalog.url, None)]
        if catalog.margin_url:
            tables.append(("margin", catalog.margin_url.rstrip("/"), None))
        return tables

    def url_of(directory: str) -> str:
        return urljoin(f"{catalog.url}/", directory).rstrip("/")

    tables = [("primary", url_of(collection["hats_primary_table_url"]), None)]
    for margin in collection.get("all_margins", "").split():
        tables.append(("margin", url_of(margin), None))
    # all_indexes alternates index columns and directories, e.g. "source_id gaia_source_id".
    for column, directory in batched(collection.get("all_indexes", "").split(), 2):
        tables.append(("index", url_of(directory), column))
    return tables


def read_tables(catalog: Catalog) -> Catalog:
    """Read a catalog's HATS tables, skipping missing margins and indexes with a warning."""
    try:
        primary, *others = list_tables(catalog)
        catalog.tables = [read_table(*primary)]
        for role, url, column in others:
            try:
                catalog.tables.append(read_table(role, url, column))
            except FileNotFoundError as e:
                catalog.warnings.append(f"skipped {role}: {e}")
    except (OSError, KeyError, ValueError) as e:
        catalog.error = f"{type(e).__name__}: {e}"
    return catalog


def folder_entity(folder: str, titles: list[str]) -> ScientificWork:
    """Return the scientificWork of a folder."""
    title = folder.replace("_", " ")  # Folder names are the site's labels with "_" for " ".
    return ScientificWork(
        type_=EntityTypeEnum.SCIENTIFICWORK,
        name=folder,
        display_name=title,
        description=f"{title} catalogs on {HOST}: {', '.join(titles)}.",
        location=f"https://{HOST}/{quote(folder, safe='()')}/",
    )


def collection_entity(catalog: Catalog, parent_fqn: str) -> ArtifactCollection:
    """Return the artifactCollection of a catalog."""
    return ArtifactCollection(
        type_=EntityTypeEnum.ARTIFACTCOLLECTION,
        parent_fqn=parent_fqn,
        name=catalog.id,
        display_name=catalog.title,
        description=catalog.description,
        location=catalog.url,
    )


def table_entity(catalog: Catalog, table: HatsTable, parent_fqn: str) -> Artifact:
    """Return the artifact of a HATS table."""
    label, description = describe(table, primary=catalog.tables[0].name)
    return Artifact(
        type_=EntityTypeEnum.ARTIFACT,
        parent_fqn=parent_fqn,
        name=table.name,
        display_name=f"{catalog.title} ({label})",
        description=description,
        location=table.url,
        format_=PARQUET,
        size=table.size,
    )


def describe(table: HatsTable, primary: str) -> tuple[str, str]:
    """Return a short label and a one-sentence description of a HATS table."""
    properties = table.properties
    if table.role == "primary":
        label = "primary catalog"
        text = f"Primary HATS catalog ({properties.get('dataproduct_type', 'object')})"
    elif table.role == "margin":
        threshold = properties.get("hats_margin_threshold")
        label = f"margin, {float(threshold):g} arcsec" if threshold else "margin"
        text = f"Margin cache of {primary}"
        if threshold:
            text += f", {float(threshold):g} arcsec threshold"
        text += ", for cross-matching at partition edges"
    else:
        label = f"index on {table.index_column}"
        text = f"Index table of {primary} on {table.index_column}, for fast ID lookups"

    details = []
    if "hats_nrows" in properties:
        details.append(f"{int(properties['hats_nrows']):,} rows")
    if "hats_order" in properties:
        details.append(f"HEALPix order {properties['hats_order']}")
    return label, f"{text}: {', '.join(details)}." if details else f"{text}."


def child_fqn(parent: str, name: str) -> str:
    """Return the FQN of a child entity. OpenMetadata quotes names that contain dots."""
    return f'{parent}."{name}"' if "." in name else f"{parent}.{name}"


class Registrar:
    """Create entities with amsc-client, skipping or updating the ones that exist."""

    def __init__(self, client: Client, catalog_fqn: str, update: bool):
        self.client = client
        self.catalog_fqn = catalog_fqn
        self.update = update
        self.counts = Counter()

    def exists(self, fqn: str) -> bool:
        """Return whether an entity exists."""
        try:
            self.client.catalog.get(fqn)
        except NotFoundError:
            return False
        return True

    def save(self, fqn: str, entity_type: CreateEntityTypeEnum, entity) -> None:
        """Create an entity, or update it if it exists and updating is on."""
        if not self.exists(fqn):
            self.client.catalog.create(self.catalog_fqn, entity_type, entity)
            action = "create"
        elif self.update:
            self.client.catalog.update(fqn, entity)
            action = "update"
        else:
            action = "exists"
        self.counts[action] += 1
        print(f"  {action:7} {fqn}")

    def register_folder(self, folder: str, titles: list[str]) -> str:
        """Register a folder, and return its FQN."""
        fqn = child_fqn(self.catalog_fqn, folder)
        self.save(fqn, CreateEntityTypeEnum.SCIENTIFICWORK, folder_entity(folder, titles))
        return fqn

    def register_catalog(self, catalog: Catalog, folder_fqn: str) -> None:
        """Register a catalog and its HATS tables under its folder."""
        fqn = child_fqn(folder_fqn, catalog.id)
        self.save(
            fqn,
            CreateEntityTypeEnum.ARTIFACTCOLLECTION,
            collection_entity(catalog, folder_fqn),
        )
        for table in catalog.tables:
            table_fqn = child_fqn(fqn, table.name)
            self.save(
                table_fqn,
                CreateEntityTypeEnum.ARTIFACT,
                table_entity(catalog, table, fqn),
            )


def register(
    registrar: Registrar,
    folders: dict[str, list[Catalog]],
    titles: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Register every folder and its catalogs. Return the (catalog id, error) of failures."""
    failures = []
    for folder, catalogs in folders.items():
        print(f"\n{folder}")
        try:
            folder_fqn = registrar.register_folder(folder, titles[folder])
        except AmscError as e:
            failures += [(catalog.id, one_line(e)) for catalog in catalogs]
            print(f"  FAILED  {one_line(e)}")
            continue
        for catalog in catalogs:
            try:
                registrar.register_catalog(catalog, folder_fqn)
            except AmscError as e:
                failures.append((catalog.id, one_line(e)))
                print(f"  FAILED  {catalog.id}: {one_line(e)}")
    return failures


def one_line(error: Exception) -> str:
    """Return an error message on a single line."""
    return " ".join(str(error).split())


def print_plan(folders: dict[str, list[Catalog]]) -> None:
    """Print the folders, catalogs and HATS tables that would be registered."""
    for folder, catalogs in folders.items():
        print(f"\n{folder}")
        for catalog in catalogs:
            print(f"  {catalog.id}: {catalog.title} ({catalog.url})")
            for table in catalog.tables:
                rows = int(table.properties.get("hats_nrows", 0))
                print(f"    {table.role:7} {table.name:34} {rows:>17,} rows  {human_size(table.size)}")


def human_size(size: int | None) -> str:
    """Format a size in bytes, e.g. "457.4 GiB"."""
    if size is None:
        return "size unknown"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def print_summary(catalogs: list[Catalog], skipped: Counter, failures: list[tuple[str, str]]) -> None:
    """Print the skipped catalogs, warnings and failures."""
    if skipped:
        print(f"\nSkipped {sum(skipped.values())} catalogs:")
        for reason, count in skipped.most_common():
            print(f"  {count:3}  {reason}")
    warnings = [(catalog.id, warning) for catalog in catalogs for warning in catalog.warnings]
    if warnings:
        print(f"\n{len(warnings)} warnings:")
        for catalog_id, warning in warnings:
            print(f"  {catalog_id}: {warning}")
    if failures:
        print(f"\n{len(failures)} catalogs failed:")
        for catalog_id, error in failures:
            print(f"  {catalog_id}: {error}")


def parse_args() -> argparse.Namespace:
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument(
        "--data_dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="data directory of data.lsdb.io",
    )
    parser.add_argument(
        "--catalog",
        default=os.environ.get("CATALOG_FQN", DEFAULT_CATALOG),
        help="FQN of the AmSC catalog to register into (env CATALOG_FQN)",
    )
    parser.add_argument(
        "--api",
        default=os.environ.get("AMSC_API", DEFAULT_API),
        help="AmSC API base URL (env AMSC_API)",
    )
    parser.add_argument(
        "--only",
        type=lambda value: set(value.split(",")),
        default=set(),
        help="comma-separated catalog.json ids to register",
    )
    parser.add_argument("--update", action="store_true", help="update entities that exist")
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="print what would be registered, and stop",
    )
    return parser.parse_args()


def main() -> None:
    """Select the catalogs, read their HATS properties, and register them."""
    args = parse_args()
    token = os.environ.get("AMSC_TOKEN")
    if not token and not args.dry_run:
        sys.exit("Set AMSC_TOKEN to an AmSC API token. See scripts/amsc/README.md.")
    if not args.data_dir.is_dir():
        sys.exit(f"Not a directory: {args.data_dir}. Pass data.lsdb.io's data dir with --data_dir.")

    catalogs, skipped = select_catalogs(args.data_dir)
    # Folder descriptions list all their catalogs, even when registering only some.
    titles = {folder: [c.title for c in members] for folder, members in by_folder(catalogs).items()}
    if args.only:
        unknown = args.only - {catalog.id for catalog in catalogs}
        if unknown:
            sys.exit(f"Not a data.lsdb.io catalog id: {', '.join(sorted(unknown))}")
        catalogs = [catalog for catalog in catalogs if catalog.id in args.only]
        skipped = Counter()

    print(f"Reading the HATS properties of {len(catalogs)} catalogs...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        catalogs = list(pool.map(read_tables, catalogs))
    failures = [(catalog.id, catalog.error) for catalog in catalogs if catalog.error]
    folders = by_folder([catalog for catalog in catalogs if not catalog.error])

    if args.dry_run:
        print_plan(folders)
    else:
        registrar = Registrar(Client(base_url=args.api, token=token), args.catalog, args.update)
        failures += register(registrar, folders, titles)
        print("\n" + ", ".join(f"{n} {action}" for action, n in sorted(registrar.counts.items())))

    print_summary(catalogs, skipped, failures)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
