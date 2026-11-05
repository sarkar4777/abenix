#!/usr/bin/env python3
"""Move backups to and from S3, Azure Blob or a directory, with no local copy needed.

BACKUP_STORE picks the target. dir uses BACKUP_DIR. s3 uses BACKUP_BUCKET and the
STORAGE_S3_* variables through boto3. azure uses BACKUP_AZURE_CONTAINER and
STORAGE_AZURE_CONNECTION_STRING over plain REST, so it needs only this file.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import formatdate
from pathlib import Path
from typing import IO, Iterator

PART_SIZE = int(os.environ.get("BACKUP_PART_BYTES", str(64 * 1024 * 1024)))
AZURE_VERSION = "2021-08-06"
WAL_NAME = re.compile(r"^[0-9A-F]{24}(\.partial)?$|^[0-9A-F]{8}\.history$")


def log(message: str) -> None:
    print(f"[backup] {message}", flush=True)


def _parts(stream: IO[bytes]) -> Iterator[bytes]:
    while True:
        part = stream.read(PART_SIZE)
        if not part:
            return
        yield part


class DirStore:
    def __init__(self) -> None:
        self.root = Path(os.environ["BACKUP_DIR"])

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise SystemExit(f"[backup] key leaves the backup folder: {key}")
        return path

    def put_stream(self, key: str, stream: IO[bytes]) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        with open(tmp, "wb") as out:
            total = sum(out.write(p) for p in _parts(stream))
        os.replace(tmp, path)
        return total

    def get_stream(self, key: str, out: IO[bytes]) -> None:
        with open(self._path(key), "rb") as fh:
            shutil.copyfileobj(fh, out, 1024 * 1024)

    def list(self, prefix: str) -> list[str]:
        base = self.root / prefix
        found = [p for p in base.rglob("*") if p.is_file()] if base.exists() else []
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in found
            if not p.name.endswith(".part")
        )

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Store:
    def __init__(self) -> None:
        import boto3

        self.bucket = os.environ["BACKUP_BUCKET"]
        if not self.bucket:
            raise SystemExit(
                "[backup] no bucket, set backup.s3Bucket or objectStorage.bucket"
            )
        kw = {"region_name": os.environ.get("STORAGE_S3_REGION") or None}
        if os.environ.get("STORAGE_S3_ENDPOINT"):
            kw["endpoint_url"] = os.environ["STORAGE_S3_ENDPOINT"]
        # empty keys fall back to the pod's role
        if os.environ.get("STORAGE_S3_ACCESS_KEY"):
            kw["aws_access_key_id"] = os.environ["STORAGE_S3_ACCESS_KEY"]
            kw["aws_secret_access_key"] = os.environ.get("STORAGE_S3_SECRET_KEY", "")
        self.s3 = boto3.client("s3", **kw)

    def put_stream(self, key: str, stream: IO[bytes]) -> int:
        current = stream.read(PART_SIZE)
        ahead = stream.read(PART_SIZE) if len(current) == PART_SIZE else b""
        if not ahead:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=current)
            return len(current)
        upload = self.s3.create_multipart_upload(Bucket=self.bucket, Key=key)
        parts, total, number = [], 0, 1
        try:
            while current:
                resp = self.s3.upload_part(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload["UploadId"],
                    PartNumber=number,
                    Body=current,
                )
                parts.append({"PartNumber": number, "ETag": resp["ETag"]})
                total += len(current)
                number += 1
                current, ahead = ahead, stream.read(PART_SIZE) if ahead else b""
            self.s3.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload["UploadId"],
                MultipartUpload={"Parts": parts},
            )
        except BaseException:
            self.s3.abort_multipart_upload(
                Bucket=self.bucket, Key=key, UploadId=upload["UploadId"]
            )
            raise
        return total

    def get_stream(self, key: str, out: IO[bytes]) -> None:
        self.s3.download_fileobj(self.bucket, key, out)

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return sorted(keys)

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=key)


class AzureStore:
    def __init__(self) -> None:
        raw = os.environ["STORAGE_AZURE_CONNECTION_STRING"]
        parts = dict(p.split("=", 1) for p in raw.split(";") if "=" in p)
        self.account = parts.get("AccountName", "")
        self.key = base64.b64decode(parts.get("AccountKey", ""))
        self.base = (
            parts.get("BlobEndpoint")
            or f"{parts.get('DefaultEndpointsProtocol', 'https')}://{self.account}.blob."
            f"{parts.get('EndpointSuffix', 'core.windows.net')}"
        ).rstrip("/")
        self.container = os.environ["BACKUP_AZURE_CONTAINER"]

    def _request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        query = query or {}
        url = f"{self.base}/{urllib.parse.quote(path)}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        all_headers = {
            "x-ms-date": formatdate(usegmt=True),
            "x-ms-version": AZURE_VERSION,
            **(headers or {}),
        }
        # urllib would add its own type, which then is not in the signature
        if body:
            all_headers["Content-Type"] = "application/octet-stream"
        ms = "".join(
            f"{k}:{all_headers[k]}\n"
            for k in sorted(all_headers)
            if k.startswith("x-ms-")
        )
        canonical = "".join(f"\n{k}:{query[k]}" for k in sorted(query))
        size = str(len(body)) if body else ""
        ctype = all_headers.get("Content-Type", "")
        resource = urllib.parse.urlparse(url).path
        to_sign = f"{method}\n\n\n{size}\n\n{ctype}\n\n\n\n\n\n\n{ms}/{self.account}{resource}{canonical}"
        mac = hmac.new(self.key, to_sign.encode(), hashlib.sha256).digest()
        all_headers["Authorization"] = (
            f"SharedKey {self.account}:{base64.b64encode(mac).decode()}"
        )
        req = urllib.request.Request(
            url, data=body or None, method=method, headers=all_headers
        )
        return urllib.request.urlopen(req, timeout=300)

    def _ensure_container(self) -> None:
        try:
            self._request("PUT", self.container, {"restype": "container"}).close()
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise

    def put_stream(self, key: str, stream: IO[bytes]) -> int:
        self._ensure_container()
        path = f"{self.container}/{key}"
        ids, total = [], 0
        for number, part in enumerate(_parts(stream)):
            block = base64.b64encode(f"{number:08d}".encode()).decode()
            self._request(
                "PUT", path, {"comp": "block", "blockid": block}, part
            ).close()
            ids.append(block)
            total += len(part)
        listing = (
            '<?xml version="1.0" encoding="utf-8"?><BlockList>'
            + "".join(f"<Latest>{b}</Latest>" for b in ids)
            + "</BlockList>"
        ).encode()
        self._request("PUT", path, {"comp": "blocklist"}, listing).close()
        return total

    def get_stream(self, key: str, out: IO[bytes]) -> None:
        with self._request("GET", f"{self.container}/{key}") as resp:
            shutil.copyfileobj(resp, out, 1024 * 1024)

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        marker = ""
        while True:
            query = {"restype": "container", "comp": "list", "prefix": prefix}
            if marker:
                query["marker"] = marker
            try:
                with self._request("GET", self.container, query) as resp:
                    root = ET.fromstring(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return []
                raise
            keys += [b.findtext("Name") or "" for b in root.iter("Blob")]
            marker = root.findtext("NextMarker") or ""
            if not marker:
                return sorted(keys)

    def delete(self, key: str) -> None:
        self._request("DELETE", f"{self.container}/{key}").close()


def store():
    kind = os.environ.get("BACKUP_STORE", "dir")
    return {"dir": DirStore, "s3": S3Store, "azure": AzureStore}[kind]()


def put_file(target, path: Path, key: str) -> None:
    with open(path, "rb") as fh:
        size = target.put_stream(key, fh)
    log(f"uploaded {key}, {size} bytes")


def ship_wal(wal_dir: Path, prefix: str, interval: float, once: bool = False) -> None:
    """Finished segments go up and leave the volume, the open one is copied so little is lost."""
    target = store()
    shipped_partial: tuple[str, int] | None = None
    while True:
        for path in sorted(wal_dir.iterdir()):
            if not WAL_NAME.match(path.name):
                continue
            if path.name.endswith(".partial"):
                stamp = (path.name, path.stat().st_mtime_ns)
                if stamp != shipped_partial:
                    put_file(target, path, f"{prefix}/partial/{path.name}")
                    shipped_partial = stamp
                continue
            put_file(target, path, f"{prefix}/{path.name}")
            # a history file is read again by the receiver after a restart
            if not path.name.endswith(".history"):
                path.unlink()
                target.delete(f"{prefix}/partial/{path.name}.partial")
        if once:
            return
        time.sleep(interval)


def latest_complete_base(target, prefix: str) -> str | None:
    done = [k for k in target.list(prefix) if k.endswith("/COMPLETE")]
    return done[-1].rsplit("/", 2)[-2] if done else None


def prune_base(prefix: str, wal_prefix: str, keep: int) -> None:
    """Older base backups go, then the WAL only they could use."""
    target = store()
    keys = target.list(prefix)
    complete = sorted(k.rsplit("/", 2)[-2] for k in keys if k.endswith("/COMPLETE"))
    dropped = complete[:-keep]
    for stamp in dropped:
        for key in keys:
            if f"/{stamp}/" in key:
                target.delete(key)
        log(f"pruned base backup {stamp}")
    if not dropped:
        return
    oldest = complete[-keep:][0]
    start_key = f"{prefix}/{oldest}/START_WAL"
    if start_key not in keys:
        return
    buf = _read(target, start_key).decode().strip()
    for key in target.list(wal_prefix):
        name = key.rsplit("/", 1)[-1]
        if re.fullmatch(r"[0-9A-F]{24}", name) and name[8:] < buf[8:]:
            target.delete(key)


def _read(target, key: str) -> bytes:
    import io

    buf = io.BytesIO()
    target.get_stream(key, buf)
    return buf.getvalue()


def stream_base(
    fifo: Path, prefix: str, status_file: Path, keep: int, wal_prefix: str
) -> None:
    """Reads what pg_basebackup writes to the pipe, COMPLETE only follows a clean exit."""
    target = store()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    with open(fifo, "rb") as fh:
        size = target.put_stream(f"{prefix}/{stamp}/base.tar.gz", fh)
    for _ in range(60):
        if status_file.exists():
            break
        time.sleep(1)
    status = status_file.read_text().strip() if status_file.exists() else "missing"
    if status != "0":
        target.delete(f"{prefix}/{stamp}/base.tar.gz")
        raise SystemExit(
            f"[backup] pg_basebackup failed with status {status}, nothing kept"
        )
    start_wal = status_file.with_name("start_wal")
    if start_wal.exists():
        with open(start_wal, "rb") as fh:
            target.put_stream(f"{prefix}/{stamp}/START_WAL", fh)
    import io

    target.put_stream(f"{prefix}/{stamp}/COMPLETE", io.BytesIO(str(size).encode()))
    log(f"base backup {stamp} complete, {size} bytes")
    prune_base(prefix, wal_prefix, keep)


def fetch_physical(prefix: str, wal_prefix: str, out: Path, stamp: str | None) -> None:
    """Base backup and the WAL to replay it, for restore-postgres.sh to use."""
    target = store()
    stamp = stamp or latest_complete_base(target, prefix)
    if not stamp:
        raise SystemExit(f"[backup] no finished base backup under {prefix}")
    out.mkdir(parents=True, exist_ok=True)
    wal = out / "wal"
    wal.mkdir(exist_ok=True)
    with open(out / "base.tar.gz", "wb") as fh:
        target.get_stream(f"{prefix}/{stamp}/base.tar.gz", fh)
    log(f"fetched base backup {stamp}")
    count = 0
    for key in target.list(wal_prefix):
        name = key.rsplit("/", 1)[-1]
        if not WAL_NAME.match(name):
            continue
        with open(wal / name, "wb") as fh:
            target.get_stream(key, fh)
        count += 1
    log(f"fetched {count} WAL files")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("put")
    p.add_argument("path", type=Path)
    p.add_argument("key")
    p = sub.add_parser("get")
    p.add_argument("key")
    p.add_argument("path", type=Path)
    p = sub.add_parser("list")
    p.add_argument("prefix")
    p = sub.add_parser("prune")
    p.add_argument("prefix")
    p.add_argument("keep", type=int)
    p = sub.add_parser("ship-wal")
    p.add_argument("wal_dir", type=Path)
    p.add_argument("prefix")
    p.add_argument("--interval", type=float, default=15)
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("stream-base")
    p.add_argument("fifo", type=Path)
    p.add_argument("prefix")
    p.add_argument("wal_prefix")
    p.add_argument("--status", type=Path, required=True)
    p.add_argument("--keep", type=int, default=4)
    p = sub.add_parser("fetch-physical")
    p.add_argument("prefix")
    p.add_argument("wal_prefix")
    p.add_argument("out", type=Path)
    p.add_argument("--stamp")
    args = parser.parse_args(argv)

    if args.cmd == "put":
        put_file(store(), args.path, args.key)
    elif args.cmd == "get":
        args.path.parent.mkdir(parents=True, exist_ok=True)
        with open(args.path, "wb") as fh:
            store().get_stream(args.key, fh)
    elif args.cmd == "list":
        for key in store().list(args.prefix):
            print(key)
    elif args.cmd == "prune":
        target = store()
        keys = target.list(args.prefix)
        for key in keys[: -args.keep] if args.keep else keys:
            target.delete(key)
            log(f"pruned {key}")
    elif args.cmd == "ship-wal":
        ship_wal(args.wal_dir, args.prefix, args.interval, args.once)
    elif args.cmd == "stream-base":
        stream_base(args.fifo, args.prefix, args.status, args.keep, args.wal_prefix)
    elif args.cmd == "fetch-physical":
        fetch_physical(args.prefix, args.wal_prefix, args.out, args.stamp)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)
