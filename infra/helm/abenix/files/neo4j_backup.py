#!/usr/bin/env python3
"""Stream an APOC Cypher export over Bolt, compressed, then keep it and ship it."""

from __future__ import annotations

import datetime
import glob
import gzip
import os
import subprocess
import sys
from pathlib import Path

QUERY = (
    "CALL apoc.export.cypher.all(null, {stream: true, format: 'cypher-shell', "
    "useOptimizations: {type: 'UNWIND_BATCH', unwindBatchSize: 500}, batchSize: 5000}) "
    "YIELD nodes, relationships, cypherStatements "
    "RETURN nodes, relationships, cypherStatements"
)


def export(path: str) -> tuple[int, int]:
    from neo4j import GraphDatabase

    nodes = rels = 0
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    try:
        with driver.session(
            database=os.environ["NEO4J_DATABASE"]
        ) as session, gzip.open(path + ".part", "wt", encoding="utf-8") as out:
            for record in session.run(QUERY):
                nodes = max(nodes, record["nodes"] or 0)
                rels = max(rels, record["relationships"] or 0)
                if record["cypherStatements"]:
                    out.write(record["cypherStatements"])
    finally:
        driver.close()
    os.replace(path + ".part", path)
    return nodes, rels


def main() -> None:
    keep = int(os.environ.get("KEEP", "7"))
    out_dir = os.environ.get("BACKUP_LOCAL_DIR", "/backup/neo4j")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = f"{out_dir}/abenix-neo4j-{stamp}.cypher.gz"
    print(f"[backup] Neo4j export starting at {stamp}", flush=True)
    nodes, rels = export(path)
    print(
        f"[backup] wrote {path}, {nodes} nodes, {rels} relationships, "
        f"{os.path.getsize(path)} bytes",
        flush=True,
    )
    for old in sorted(glob.glob(f"{out_dir}/abenix-neo4j-*.cypher.gz"))[:-keep]:
        os.remove(old)
    for part in glob.glob(f"{out_dir}/*.part"):
        os.remove(part)
    if os.environ.get("BACKUP_STORE") not in ("s3", "azure"):
        return
    store = str(Path(__file__).with_name("backup_store.py"))
    prefix = os.environ.get("BACKUP_NEO4J_PREFIX", "backups/neo4j")
    key = f"{prefix}/{os.path.basename(path)}"
    subprocess.run([sys.executable, store, "put", path, key], check=True)
    subprocess.run([sys.executable, store, "prune", prefix, str(keep)], check=True)


if __name__ == "__main__":
    main()
