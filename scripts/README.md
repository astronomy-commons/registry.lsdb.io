# Resource Collector

Enclosed is a script to collect VOResources, and add them to the `resources` directory as XML files.

## from_catalogs_json.py

This uses the list of catalogs from the data.lsdb.io repository. This file contains good registry information, and uses nearly all of the fields present in that file.

The script assumes you have the two repositories checked out into a common parent folder, but you can
specify the path to the data.lsdb.io `data` directory with the `--data_dir` argument.

```
$ tree -L 1 git_root/
git_root/
├── data.lsdb.io
├── ...
├── registry.lsdb.io
└── ...
```

By default, this script will only add new resources, or mark missing resources for deletion.

If you would like to update all existing resources, pass `--refresh_resources`, and the full XML
will be re-generated. This can be useful if you significantly modify the script, template, or
underlying data.

If you want to update particular resources only, you can use the `--rerender_list` argument,
and provide a comma-separated list of labels. Note that you'll probably want to put some quotes
around the list, since your labels might have parens in them.

## Resource IDs

Each catalog in data.lsdb.io has an `id` in its `catalog.json`, e.g. `"id": "gaia_dr3"`. It's made of
lowercase letters, digits and underscores, and it's used for:

- the XML file name, e.g. `gaia_dr3.xml`.
- the resource's identifier, e.g. `ivo://data.lsdb/uw/gaia_dr3`.
- the resource's `shortName`, truncated to `--short_name_max` characters (16 by default).

Registry harvesters track resources by their identifier, so a catalog's `id` should not change once
it's registered. Changing it marks the old resource as deleted and registers the catalog as a new resource.

The registry also refuses to load resources that share an identifier, deleted ones included. So before
writing anything, the script checks that every resource (existing and deleted) to register has a valid and
unique catalog `id`. If either check fails, it lists the problems and exits without writing any file.
