"""Incremental knowledge connectors."""

from __future__ import annotations

from engine.kb_connectors.azure_blob import AzureBlobConnector
from engine.kb_connectors.base import Connector
from engine.kb_connectors.confluence import ConfluenceConnector
from engine.kb_connectors.filesystem import FilesystemConnector
from engine.kb_connectors.gdrive import GoogleDriveConnector
from engine.kb_connectors.graph import GraphConnector
from engine.kb_connectors.s3 import S3Connector
from engine.kb_connectors.sql_query import SqlQueryConnector

KINDS: dict[str, type[Connector]] = {
    c.kind: c
    for c in (
        S3Connector,
        AzureBlobConnector,
        GraphConnector,
        ConfluenceConnector,
        GoogleDriveConnector,
        SqlQueryConnector,
        FilesystemConnector,
    )
}


def describe() -> list[dict]:
    return [
        {
            "kind": c.kind,
            "label": c.label,
            "needs_admin": c.needs_admin,
            "verified_live": c.verified_live,
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "kind": f.kind,
                    "required": f.required,
                    "help": f.help,
                    "default": f.default,
                    "secret": f.secret,
                }
                for f in c.fields
            ],
        }
        for c in KINDS.values()
    ]


def build(kind: str, config: dict, secrets: dict, **options) -> Connector:
    cls = KINDS.get(kind)
    if cls is None:
        raise KeyError(kind)
    return cls(config, secrets, **options)
