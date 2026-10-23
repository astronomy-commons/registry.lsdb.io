<img src="https://github.com/astronomy-commons/lsdb/blob/main/docs/lincc-logo.png?raw=true" width="300">

# registry.lsdb.io

[![Template](https://img.shields.io/badge/Template-LINCC%20Frameworks%20Python%20Project%20Template-brightgreen)](https://lincc-ppt.readthedocs.io/en/latest/)

`registry.lsdb.io` is the IVOA publishing registry for LINCC
Frameworks HATS catalogs. It serves a
[VOResource](https://www.ivoa.net/documents/VOResource/) record per catalog over
[OAI-PMH](https://www.openarchives.org/OAI/openarchivesprotocol.html), under the `ivo://data.lsdb`
authority. It's listed in the [Registry of Registries](http://rofr.ivoa.net) (RofR), so searchable
registries like GAVO RegTAP harvest it.

- [Using the registry](#using-the-registry)
  - [Query the registry](#query-the-registry)
  - [Request a resource](#request-a-resource)
- [Maintaining the registry](#maintaining-the-registry)
  - [Getting started](#getting-started)
  - [Resource files](#resource-files)
  - [Add resources](#add-resources)
  - [Deploy](#deploy)
  - [Validate](#validate)

## Using the registry

### Query the registry

Send OAI-PMH requests to `https://registry.lsdb.io/registry`:

| Verb                                                                                                                          | Returns                                                                                        |
| ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| [`Identify`](https://registry.lsdb.io/registry?verb=Identify)                                                                 | Registry info and its `vg:Registry` record.                                                    |
| [`ListMetadataFormats`](https://registry.lsdb.io/registry?verb=ListMetadataFormats)                                           | `ivo_vor` (full VOResource) and `oai_dc` (Dublin Core summary).                                |
| [`ListSets`](https://registry.lsdb.io/registry?verb=ListSets)                                                                 | `ivo_managed`, the only set.                                                                   |
| [`ListIdentifiers`](https://registry.lsdb.io/registry?verb=ListIdentifiers&metadataPrefix=ivo_vor)                            | Every record's header: identifier, datestamp and set. Deleted records have `status="deleted"`. |
| [`ListRecords`](https://registry.lsdb.io/registry?verb=ListRecords&metadataPrefix=ivo_vor)                                    | Every record, with its metadata. Deleted records only have a header.                           |
| [`GetRecord`](https://registry.lsdb.io/registry?verb=GetRecord&identifier=ivo://data.lsdb/uw/gaia_dr3&metadataPrefix=ivo_vor) | One record, by `identifier`.                                                                   |

- `ListIdentifiers`, `ListRecords` and `GetRecord` require a `metadataPrefix`.
- `ListIdentifiers` and `ListRecords` accept `from`/`until`, to filter by datestamp (the record's
  `updated`), and `set`.
- Errors are returned as `<error code="...">` with HTTP 200, e.g. `badVerb` or `idDoesNotExist`.

To search for catalogs across the VO, query a searchable registry instead, e.g. with
[pyvo](https://pyvo.readthedocs.io):

```python
import pyvo

resources = pyvo.registry.search(
    pyvo.registry.Servicetype("ivo://ivoa.net/std/hats#hats-1.0"),
    pyvo.registry.Author("LINCC Frameworks"),
    pyvo.registry.Freetext("gaia"),
)
for resource in resources:
    print(resource.ivoid, resource.get_interface(service_type="hats").access_url)
```

### Request a resource

Check your resource isn't registered already, then
[open an issue](https://github.com/astronomy-commons/registry.lsdb.io/issues/new?template=0-general_issue.md)
with:

| Field               | Required | Description                                                                                                             |
| ------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------- |
| Resource identifier | Yes      | `ivo://data.lsdb/<short_location>/<resource_name>` (see below).                                                         |
| Name                | Yes      | The catalog's name, used in the resource's title.                                                                       |
| Description         | Yes      | What the catalog contains.                                                                                              |
| Catalog URL         | Yes      | Where the HATS catalog or collection is read from (`https://`, `s3://` or `hf://`). It must open with `hats.read_hats`. |
| Reference URL       | No       | A page about the catalog, e.g. its official release.                                                                    |

The `<resource_name>` uses letters, digits and underscores, and the identifier must not match any existing
one, ignoring case, deleted ones included. The short location depends on the host: we currently use `uw` for
data.lsdb.io, and `hf_mmu` for Multimodal Universe datasets on HuggingFace.

There are other fields, but they are either the same for every resource, or should be read from the catalog's metadata.

## Maintaining the registry

### Getting started

Create a virtual environment and install the project for local development:

```
>> conda create -n <env_name> python=3.12
>> conda activate <env_name>
>> ./.setup_dev.sh
```

`./.setup_dev.sh` also sets up [pre-commit](https://lincc-ppt.readthedocs.io/en/latest/practices/precommit.html),
which runs checks before each local commit.

### Resource files

[`resources/`](resources) has a VOResource XML file per catalog, grouped by source:

| Directory                                       | Catalogs                                                                                                                | Identifiers                     | Generated by                                             |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------- | -------------------------------------------------------- |
| [`data.lsdb.io/`](resources/data.lsdb.io)       | [data.lsdb.io](https://github.com/astronomy-commons/data.lsdb.io) catalogs hosted by LINCC Frameworks                   | `ivo://data.lsdb/uw/<id>`       | [`from_catalogs_json.py`](scripts/from_catalogs_json.py) |
| [`UniverseTBD_mmu/`](resources/UniverseTBD_mmu) | [Multimodal Universe](https://huggingface.co/collections/UniverseTBD/multimodal-universe-hats) datasets on Hugging Face | `ivo://data.lsdb/hf_mmu/<name>` | [`from_huggingface.py`](scripts/from_huggingface.py)     |

The scripts render the files from [`templates/`](templates). When changing them:

- **Do not delete files.** Set `status="deleted"` instead, so harvesters learn about the removal.
- **Do not change `updated` manually.** The scripts take care of that. It's the datestamp harvesters use to find changes.
- **Never change an `identifier`.** Identifiers must be unique across all files, deleted ones included.

`authority.xml` and `registry.xml` are not expected to change and, therefore, are stored on the server, not in this repository.

### Add resources

Generate resource files using the available scripts rather than by hand (see
[`scripts/README.md`](scripts/README.md)). The scripts only write new resources, but mark the resources
missing from their source as deleted, so check that `git status` only shows the changes you expect before
opening a PR.

### Deploy

The registry runs as the `vo_registry` Docker container on `lsdb.phys.cmu.edu`.
On every push to `main`, [`deploy.yml`](.github/workflows/deploy.yml) connects to the server over SSH, pulls the updated resources, and restarts the container, which reads the bind-mounted directory. Merges to `main` are live within a minute. To redeploy, re-run the workflow.

### Validate

- **Connectivity checks:** `python scripts/check_resources.py` loads every active catalog with hats, and fails
  if any can't be loaded. The [Connectivity Check](.github/workflows/connectivity-checks.yml) workflow
  also runs it daily at 07:45 UTC, and alerts the team's internal Slack on failure.
- In the **[RofR validator](<(http://rofr.ivoa.net/regvalidate/)>):** enter
  `https://registry.lsdb.io/registry`, keep "Use built-in schemas" checked, and press "validate". It checks
  OAI-PMH compliance, the IVOA harvesting profile, and every record against VOResource, which should all pass.
