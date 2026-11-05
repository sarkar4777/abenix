"""Rows from a read only query become documents, one row one document."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from engine.kb_connectors.base import (
    AuthError,
    ConfigError,
    Connector,
    ConnectorError,
    Field,
    Page,
    RemoteItem,
    TransientError,
    safe_filename,
    with_retries,
)
from engine.kb_connectors.http import check_url

PAGE = 500
_DRIVERS = {
    "postgresql": "postgresql+psycopg2",
    "postgres": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "mariadb": "mysql+pymysql",
    "mssql": "mssql+pymssql",
    "oracle": "oracle+oracledb",
}
_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|merge|call|copy|into)\b",
    re.I,
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def check_query(query: str) -> str:
    q = (query or "").strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", q, re.I):
        raise ConfigError("The query must start with SELECT or WITH.")
    if ";" in q:
        raise ConfigError("The query must be a single statement.")
    # the transaction is read only too, this only gives a clearer message first
    stripped = re.sub(r"'(?:[^']|'')*'", "''", q)
    if _WRITE_WORDS.search(stripped):
        raise ConfigError("The query must only read. It contains a word that writes.")
    return q


def _text(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return "<binary>"
    return "" if value is None else str(value)


class SqlQueryConnector(Connector):
    kind = "sql"
    label = "SQL database query"
    verified_live = True
    needs_admin = True
    fields = [
        Field(
            "query",
            "Read only query",
            kind="textarea",
            required=True,
            help="One row becomes one document.",
        ),
        Field(
            "id_column", "Id column", required=True, help="Unique, stable, sortable."
        ),
        Field("title_column", "Title column"),
        Field(
            "updated_column",
            "Updated at column",
            help="With this only changed rows are read. Without it every row is hashed.",
        ),
        Field(
            "acl_column",
            "Allowed emails column",
            help="Comma separated emails that may read the row. Empty means only you.",
        ),
        Field(
            "url",
            "Database URL",
            kind="secret",
            secret=True,
            required=True,
            help="postgresql://, mysql://, mssql:// or oracle://user:password@host/db",
        ),
    ]

    def __init__(self, config, secrets, **options) -> None:
        super().__init__(config, secrets, **options)
        self._engine: Any = None

    def _parsed(self) -> Any:
        from sqlalchemy.engine import make_url

        try:
            url = make_url(self.secret("url"))
        except Exception as e:
            raise ConfigError("That database URL could not be read.") from e
        base = url.drivername.split("+", 1)[0]
        if base not in _DRIVERS:
            raise ConfigError(
                f"{base} is not supported. Use {', '.join(sorted(set(_DRIVERS)))}."
            )
        return url.set(drivername=_DRIVERS[base])

    async def validate(self) -> None:
        check_query(self.cfg("query", ""))
        for name in ("id_column", "title_column", "updated_column", "acl_column"):
            value = self.cfg(name)
            if value and not _IDENT.match(value):
                raise ConfigError(f"{value} is not a plain column name.")
        url = self._parsed()
        if not url.host:
            raise ConfigError("The database URL must name a host.")
        await check_url(f"http://{url.host}:{url.port or 5432}/", "This database host")

    def _get_engine(self) -> Any:
        if self._engine is None:
            from sqlalchemy import create_engine
            from sqlalchemy.pool import NullPool

            try:
                self._engine = create_engine(self._parsed(), poolclass=NullPool)
            except ModuleNotFoundError as e:
                raise ConfigError(
                    f"The driver for this database is not installed here ({e.name})."
                ) from e
        return self._engine

    def _read_only_begin(self, conn: Any) -> None:
        from sqlalchemy import text

        name = conn.engine.dialect.name
        if name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = 300000"))
        elif name in ("mysql", "mariadb"):
            conn.rollback()
            conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        elif name == "oracle":
            conn.execute(text("SET TRANSACTION READ ONLY"))

    def _select(self, columns: str, where: str, order: str, limit: int) -> str:
        inner = check_query(self.cfg("query", ""))
        dialect = self._get_engine().dialect.name
        tail = (
            f"FETCH FIRST {limit} ROWS ONLY"
            if dialect in ("oracle", "mssql")
            else f"LIMIT {limit}"
        )
        if dialect == "mssql":
            tail = f"OFFSET 0 ROWS FETCH NEXT {limit} ROWS ONLY"
        return (
            f"SELECT {columns} FROM ({inner}) abenix_q {where} ORDER BY {order} {tail}"
        )

    def _run(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

        try:
            with self._get_engine().connect() as conn:
                self._read_only_begin(conn)
                rows = conn.execute(text(sql), params).mappings().all()
                conn.rollback()
                return [dict(r) for r in rows]
        except OperationalError as e:
            message = str(e.orig)
            if "password" in message or "denied" in message.lower():
                raise AuthError(f"The database refused the login. {message[:200]}")
            raise TransientError(f"Could not reach the database. {message[:200]}")
        except ProgrammingError as e:
            raise ConnectorError(f"The query failed. {str(e.orig)[:300]}")
        except SQLAlchemyError as e:
            raise ConnectorError(f"The database answered with an error. {str(e)[:300]}")

    async def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        async def once() -> list[dict[str, Any]]:
            return await asyncio.to_thread(self._run, sql, params)

        return await with_retries(once)

    def _item(self, row: dict[str, Any]) -> RemoteItem:
        rid = row.get(self.cfg("id_column"))
        title = (
            _text(row.get(self.cfg("title_column"))) if self.cfg("title_column") else ""
        )
        lines = [f"# {title}", ""] if title else []
        acl_col = self.cfg("acl_column")
        for key, value in row.items():
            if key != acl_col:
                lines.append(f"{key}: {_text(value)}")
        data = "\n".join(lines).encode("utf-8")
        acl = None
        if acl_col:
            emails = [
                e.strip() for e in _text(row.get(acl_col)).split(",") if e.strip()
            ]
            acl = {
                "public": False,
                "principals": [
                    {"type": "user", "email": e, "role": "read"} for e in emails
                ],
            }
        return RemoteItem(
            external_id=str(rid),
            name=safe_filename(f"{title or rid}".replace("/", "-")) + ".txt",
            version=hashlib.sha256(data).hexdigest(),
            size=len(data),
            acl=acl,
            content=data,
        )

    async def list_page(self, page_cursor, sync_cursor) -> Page:
        cur = dict(page_cursor or {})
        id_col = self.cfg("id_column")
        updated = self.cfg("updated_column")
        phase = cur.get("phase") or "rows"
        params: dict[str, Any] = {}
        where: list[str] = []

        if phase == "ids":
            if "after" in cur:
                where.append(f"{id_col} > :after")
                params["after"] = cur["after"]
            sql = self._select(
                id_col,
                "WHERE " + " AND ".join(where) if where else "",
                id_col,
                PAGE * 4,
            )
            rows = await self._rows(sql, params)
            page = Page(seen=[str(r[id_col]) for r in rows])
            if len(rows) < PAGE * 4:
                page.finished = True
                page.sync_cursor = {"watermark": cur.get("watermark")}
            else:
                page.next_cursor = {**cur, "after": rows[-1][id_col]}
            return page

        since = (sync_cursor or {}).get("watermark") if updated else None
        watermark = cur.get("watermark") or since
        if since:
            where.append(f"{updated} > :since")
            params["since"] = since
        if "after" in cur:
            where.append(f"{id_col} > :after")
            params["after"] = cur["after"]
        sql = self._select(
            "*", "WHERE " + " AND ".join(where) if where else "", id_col, PAGE
        )
        rows = await self._rows(sql, params)
        items = [self._item(r) for r in rows]
        if updated:
            for r in rows:
                value = r.get(updated)
                if value is not None:
                    text = _text(value)
                    if not watermark or text > watermark:
                        watermark = text
        if len(rows) == PAGE:
            return Page(
                items=items,
                next_cursor={
                    "phase": "rows",
                    "after": rows[-1][id_col],
                    "watermark": watermark,
                },
            )
        if updated:
            # changed rows are read, an id pass still finds the ones that went away
            return Page(
                items=items, next_cursor={"phase": "ids", "watermark": watermark}
            )
        return Page(items=items, finished=True, sync_cursor={"watermark": watermark})

    async def aclose(self) -> None:
        if self._engine is not None:
            await asyncio.to_thread(self._engine.dispose)
