#!/usr/bin/env python3
"""Build the hybrid pipeline's Qdrant collection from Cube /meta.

    cd oasys-backend && venv/bin/python scripts/index_cube_members_v2.py
    venv/bin/python scripts/index_cube_members_v2.py --collection my_test_collection

Safe to re-run: the collection is dropped and rebuilt. Does NOT touch
`cube_metadata_openai`, which the production pipeline reads.
"""
import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.hybrid.indexer import COLLECTION, collection_info, reindex  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collection", default=COLLECTION)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    summary = await reindex(collection=args.collection)

    print(f"\nIndexed {summary['indexed']} members into '{summary['collection']}'")
    for view, n in sorted(summary["per_view"].items(), key=lambda kv: -kv[1]):
        print(f"  {view:26s} {n:4d}")
    if summary["undescribed"]:
        print(f"\nWARNING — {len(summary['undescribed'])} members have no description "
              f"and will retrieve poorly. Add them to DESC_OVERRIDES in "
              f"app/services/hybrid/cube_meta.py:")
        for q in summary["undescribed"]:
            print(f"  {q}")
    else:
        print("\nEvery member has a description.")

    info = await collection_info(args.collection)
    print(f"\nQdrant reports: {info}")
    if info.get("points") != summary["indexed"]:
        print("MISMATCH — point count differs from indexed count.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
