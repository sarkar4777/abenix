"""Direct uploads through the real boto3 client against a local S3 protocol server."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import uuid
from threading import Thread

import httpx
import pytest

pytest.importorskip("moto.server")


@pytest.fixture(scope="module")
def s3_url():
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def storage(s3_url, monkeypatch):
    import boto3

    from engine.storage import service

    monkeypatch.setattr(service, "STORAGE_S3_ENDPOINT", s3_url)
    monkeypatch.setattr(service, "STORAGE_S3_BUCKET", "kb-scale")
    monkeypatch.setattr(service, "STORAGE_S3_ACCESS_KEY", "test")
    monkeypatch.setattr(service, "STORAGE_S3_SECRET_KEY", "test")
    monkeypatch.setattr(service, "STORAGE_S3_REGION", "us-east-1")
    monkeypatch.setattr(service, "MIN_DIRECT_PART", 5 * 1024 * 1024)
    boto3.client(
        "s3",
        endpoint_url=s3_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    ).create_bucket(Bucket="kb-scale")
    return service.StorageService("s3")


def test_presigned_multipart_round_trip(storage, tmp_path):
    part = 5 * 1024 * 1024
    body = b"a" * part + b"b" * part + b"c" * 1234

    async def go():
        plan = await storage.start_direct_upload(
            "t", "kb/x/big.txt", len(body), "text/plain"
        )
        assert plan["kind"] == "s3_multipart" and len(plan["parts"]) == 3
        parts = []
        async with httpx.AsyncClient() as client:
            for p in plan["parts"]:
                start = (p["part_number"] - 1) * plan["part_size"]
                resp = await client.put(
                    p["url"], content=body[start : start + plan["part_size"]]
                )
                assert resp.status_code == 200, resp.text
                parts.append(
                    {"part_number": p["part_number"], "etag": resp.headers["etag"]}
                )
        uri = await storage.finish_direct_upload(plan, parts)
        size = await storage.size_of(uri)
        dest = tmp_path / "back.txt"
        await storage.download_to_file(uri, str(dest))
        return uri, size, dest

    uri, size, dest = asyncio.run(go())
    assert uri.startswith("s3://kb-scale/t/kb/x/")
    assert size == len(body)
    assert hashlib.sha256(dest.read_bytes()).digest() == hashlib.sha256(body).digest()


def test_abort_leaves_no_object(storage):
    async def go():
        plan = await storage.start_direct_upload("t", "kb/x/gone.txt", 10, "text/plain")
        await storage.abort_direct_upload(plan)
        return await storage.exists(plan["uri"])

    assert asyncio.run(go()) is False


def test_stream_upload_goes_to_s3_in_bounded_pieces(storage, tmp_path):
    async def chunks():
        for i in range(40):
            yield bytes([i]) * (1024 * 1024)

    async def go():
        uri = await storage.upload_stream(
            "t", "kb/x/stream.bin", chunks(), "application/x"
        )
        dest = tmp_path / "s.bin"
        await storage.download_to_file(uri, str(dest))
        return dest

    dest = asyncio.run(go())
    assert dest.stat().st_size == 40 * 1024 * 1024
    with open(dest, "rb") as fh:
        fh.seek(39 * 1024 * 1024)
        assert fh.read(1) == bytes([39])


def test_a_stream_that_breaks_leaves_nothing_in_the_bucket(storage):
    async def broken():
        yield b"x" * (9 * 1024 * 1024)
        raise RuntimeError("client went away")

    with pytest.raises(RuntimeError):
        asyncio.run(storage.upload_stream("t", "kb/x/broken.bin", broken()))
    assert not asyncio.run(storage.exists("s3://kb-scale/t/kb/x/broken.bin"))


def test_worker_downloads_to_a_temp_file(storage, monkeypatch):
    from engine import storage as package
    from worker.tasks import document_processor as dp

    monkeypatch.setattr(package, "get_storage", lambda: storage)

    async def put():
        import io

        return await storage.upload_fileobj(
            "t", "kb/x/w.txt", io.BytesIO(b"hello"), "text/plain"
        )

    uri = asyncio.run(put())
    box = {}

    # asyncio.run inside the worker needs a thread with no running loop
    def work():
        box["out"] = dp._local_path(uri, "txt")

    thread = Thread(target=work)
    thread.start()
    thread.join()
    path, tmp = box["out"]
    assert tmp == path
    with open(path) as fh:
        assert fh.read() == "hello"


AZURITE = os.environ.get("KB_TEST_AZURITE_CONN")
azurite = pytest.mark.skipif(
    not AZURITE, reason="set KB_TEST_AZURITE_CONN to run against Azurite"
)


@pytest.fixture
def azure_storage(monkeypatch):
    from azure.storage.blob import BlobServiceClient

    from engine.storage import service

    container = f"kb{uuid.uuid4().hex[:8]}"
    BlobServiceClient.from_connection_string(AZURITE).create_container(container)
    monkeypatch.setattr(service, "STORAGE_AZURE_CONN_STR", AZURITE)
    monkeypatch.setattr(service, "STORAGE_AZURE_CONTAINER", container)
    monkeypatch.setattr(service, "MIN_DIRECT_PART", 4 * 1024 * 1024)
    return service.StorageService("azure")


@azurite
def test_azure_blocks_round_trip_through_a_sas_url(azure_storage, tmp_path):
    block = 4 * 1024 * 1024
    body = b"a" * block + b"b" * 1000

    async def go():
        plan = await azure_storage.start_direct_upload("t", "kb/x/big.txt", len(body))
        assert plan["kind"] == "azure_blocks" and plan["part_size"] == block
        ids = []
        async with httpx.AsyncClient() as client:
            for n, start in enumerate(range(0, len(body), block)):
                block_id = base64.b64encode(f"{n:010d}".encode()).decode()
                resp = await client.put(
                    plan["url"],
                    params={"comp": "block", "blockid": block_id},
                    content=body[start : start + block],
                    headers={"x-ms-blob-type": "BlockBlob"},
                )
                assert resp.status_code == 201, resp.text
                ids.append({"block_id": block_id})
        uri = await azure_storage.finish_direct_upload(plan, ids)
        size = await azure_storage.size_of(uri)
        dest = tmp_path / "back.txt"
        await azure_storage.download_to_file(uri, str(dest))
        return uri, size, dest

    uri, size, dest = asyncio.run(go())
    assert uri.startswith("az://")
    assert size == len(body)
    assert dest.read_bytes() == body


@azurite
def test_azure_stream_upload(azure_storage, tmp_path):
    async def chunks():
        for i in range(10):
            yield bytes([i]) * (1024 * 1024)

    async def go():
        uri = await azure_storage.upload_stream("t", "kb/x/s.bin", chunks())
        dest = tmp_path / "s.bin"
        await azure_storage.download_to_file(uri, str(dest))
        return dest

    assert asyncio.run(go()).stat().st_size == 10 * 1024 * 1024
