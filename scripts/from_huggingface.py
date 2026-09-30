import argparse
import sys
from pathlib import Path

from common import ROOT_DIR, Catalog, ResourceError, run
from huggingface_hub import HfApi, hf_hub_download


def list_collection():
    """Helper to list the items in a collection."""
    hf_api = HfApi()
    # UniverseTBD/multimodal-universe-hats
    # MultimodalUniverse/multimodal-universe-v15-6a451ba46c643209b19d88d9
    collection = hf_api.get_collection(collection_slug="UniverseTBD/multimodal-universe-hats")

    print(f"Collection Title: {collection.title}")
    print(f"Description: {collection.description}")

    # Loop through items in the collection
    titles = []
    for item in collection.items:
        if item.item_type == "dataset":
            titles.append(item.item_id)
            # print(f"Item ID: {item.item_id} | Type: {item.item_type}")
        # else:
        #     print(f"     Item ID: {item.item_id} | Type: {item.item_type}")
        if item.note:
            print(f"Item ID: {item.item_id} | Type: {item.item_type}")
            print("    ", item.note)

    for title in sorted(titles):
        print(title)


def get_readme():
    """Helper to download a single readme."""
    new_path = hf_hub_download(repo_id="UniverseTBD/mmu_sdss_sdss", filename="README.md", repo_type="dataset")
    print(new_path)


def _unify_label(label):
    label = label.split("/")[-1]
    label = label.replace("-", "_")

    # Convoluted, but this is how we turn
    # input:  mmu_jwst_ceers_full_grizli_v7.0_all_96
    # output: mmu_jwst_ceers_full_grizli
    if "." in label:
        tokens = label.split("_")
        with_dot = 0
        for i, t in enumerate(tokens):
            if "." in t:
                with_dot = i
                break
        label = "_".join(tokens[0:with_dot])

    return label


def _read_hf_collection(collection_slug):
    catalogs = []

    hf_api = HfApi()
    collection = hf_api.get_collection(collection_slug=collection_slug)

    # Loop through items in the collection
    titles = []
    for item in collection.items:
        if item.item_type == "dataset":
            titles.append(item.item_id)

    for title in sorted(titles):
        label = _unify_label(title)
        catalogs.append(
            Catalog(label, {"id": label, "name": label}, f"hf://datasets/{title}", "Hugging Face", "hf_mmu")
        )
    return catalogs


def main():
    """Parse the command-line arguments and generate the resources."""
    parser = argparse.ArgumentParser("vo-resource-gen")
    parser.add_argument(
        "--collection_slug",
        type=str,
        default="UniverseTBD/multimodal-universe-hats",
        help="HuggingFace collection.",
    )
    parser.add_argument(
        "--out_dir",
        type=Path,
        default=ROOT_DIR / "resources" / "UniverseTBD_mmu",
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
            _read_hf_collection(args.collection_slug),
            args.out_dir,
            short_name_max=args.short_name_max,
            refresh_resources=args.refresh_resources,
            rerender_list=args.rerender_list.split(",") if args.rerender_list else [],
        )
    except ResourceError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
