"""The backup mover against a real S3 server, a real Azure emulator and a folder, and the drills."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import threading
import uuid
from pathlib import Path

import pytest
from kb_pg import docker_works

ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "infra/helm/abenix/files"
AZURITE_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


def _module():
    spec = importlib.util.spec_from_file_location(
        "backup_store", FILES / "backup_store.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dir_store(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_STORE", "dir")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "store"))
    (tmp_path / "store").mkdir()
    return _module()


@pytest.fixture
def s3_store(minio_endpoint, monkeypatch):
    import boto3

    bucket = f"bk-{uuid.uuid4().hex[:8]}"
    boto3.client(
        "s3",
        endpoint_url=minio_endpoint["url"],
        aws_access_key_id=minio_endpoint["access"],
        aws_secret_access_key=minio_endpoint["secret"],
        region_name="us-east-1",
    ).create_bucket(Bucket=bucket)
    monkeypatch.setenv("BACKUP_STORE", "s3")
    monkeypatch.setenv("BACKUP_BUCKET", bucket)
    monkeypatch.setenv("STORAGE_S3_ENDPOINT", minio_endpoint["url"])
    monkeypatch.setenv("STORAGE_S3_ACCESS_KEY", minio_endpoint["access"])
    monkeypatch.setenv("STORAGE_S3_SECRET_KEY", minio_endpoint["secret"])
    monkeypatch.setenv("STORAGE_S3_REGION", "us-east-1")
    mod = _module()
    monkeypatch.setattr(mod, "PART_SIZE", 5 * 1024 * 1024)
    return mod


@pytest.fixture
def azure_store(azurite_port, monkeypatch):
    account = "devstoreaccount1"
    monkeypatch.setenv("BACKUP_STORE", "azure")
    monkeypatch.setenv("BACKUP_AZURE_CONTAINER", f"bk{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv(
        "STORAGE_AZURE_CONNECTION_STRING",
        f"DefaultEndpointsProtocol=http;AccountName={account};AccountKey={AZURITE_KEY};"
        f"BlobEndpoint=http://127.0.0.1:{azurite_port}/{account};",
    )
    mod = _module()
    monkeypatch.setattr(mod, "PART_SIZE", 1024 * 1024)
    return mod


def _roundtrip(mod, size: int):
    target = mod.store()
    data = os.urandom(1024) * (size // 1024)
    assert target.put_stream("a/b/big.bin", io.BytesIO(data)) == len(data)
    assert target.put_stream("a/b/small.bin", io.BytesIO(b"x")) == 1
    assert target.list("a/") == ["a/b/big.bin", "a/b/small.bin"]
    out = io.BytesIO()
    target.get_stream("a/b/big.bin", out)
    assert out.getvalue() == data
    target.delete("a/b/small.bin")
    assert target.list("a/") == ["a/b/big.bin"]


def test_folder_round_trip(dir_store):
    _roundtrip(dir_store, 3 * 1024 * 1024)


def test_s3_multipart_round_trip_on_a_real_server(s3_store):
    # three parts and a tail, MinIO refuses parts under 5 MiB like S3 does
    _roundtrip(s3_store, 17 * 1024 * 1024)


def test_s3_exact_part_boundary(s3_store):
    target = s3_store.store()
    data = b"z" * (10 * 1024 * 1024)
    assert target.put_stream("exact", io.BytesIO(data)) == len(data)
    out = io.BytesIO()
    target.get_stream("exact", out)
    assert out.getvalue() == data


def test_azure_blocks_round_trip_on_the_emulator(azure_store):
    _roundtrip(azure_store, 3 * 1024 * 1024)


def test_folder_key_cannot_leave(dir_store):
    with pytest.raises(SystemExit):
        dir_store.store().put_stream("../../evil", io.BytesIO(b"x"))


def test_ship_wal_moves_finished_segments_and_copies_the_open_one(dir_store, tmp_path):
    wal = tmp_path / "wal"
    wal.mkdir()
    done = "000000010000000000000005"
    (wal / done).write_bytes(b"s" * 10)
    (wal / "000000010000000000000006.partial").write_bytes(b"p")
    (wal / "00000002.history").write_bytes(b"h")
    (wal / "junk.txt").write_bytes(b"j")
    dir_store.ship_wal(wal, "pg/wal", 0, once=True)
    target = dir_store.store()
    assert set(target.list("pg/wal")) == {
        f"pg/wal/{done}",
        "pg/wal/00000002.history",
        "pg/wal/partial/000000010000000000000006.partial",
    }
    assert not (wal / done).exists()
    assert (wal / "000000010000000000000006.partial").exists()
    (wal / "000000010000000000000006").write_bytes(b"f")
    (wal / "000000010000000000000006.partial").unlink()
    dir_store.ship_wal(wal, "pg/wal", 0, once=True)
    assert "pg/wal/partial/000000010000000000000006.partial" not in target.list(
        "pg/wal"
    )


def _stream(mod, tmp_path, status, payload=b"tarball", keep=4):
    fifo = tmp_path / "base.fifo"
    if not fifo.exists():
        os.mkfifo(fifo)
    state = tmp_path / "status"
    state.write_text(status)
    (tmp_path / "start_wal").write_text("000000010000000000000005")

    def writer():
        with open(fifo, "wb") as out:
            out.write(payload)

    t = threading.Thread(target=writer)
    t.start()
    try:
        mod.stream_base(fifo, state and "pg/base", state, keep, "pg/wal")
    finally:
        t.join()


def test_a_failed_base_backup_is_never_marked_complete(dir_store, tmp_path):
    with pytest.raises(SystemExit, match="failed with status 1"):
        _stream(dir_store, tmp_path, "1")
    target = dir_store.store()
    assert target.list("pg/base") == []
    assert dir_store.latest_complete_base(target, "pg/base") is None


def test_finished_base_backup_can_be_fetched_with_its_wal(
    dir_store, tmp_path, monkeypatch
):
    _stream(dir_store, tmp_path, "0")
    target = dir_store.store()
    stamp = dir_store.latest_complete_base(target, "pg/base")
    assert stamp
    target.put_stream("pg/wal/000000010000000000000005", io.BytesIO(b"w"))
    target.put_stream(
        "pg/wal/partial/000000010000000000000006.partial", io.BytesIO(b"p")
    )
    out = tmp_path / "restore"
    dir_store.fetch_physical("pg/base", "pg/wal", out, None)
    assert (out / "base.tar.gz").read_bytes() == b"tarball"
    assert (out / "wal/000000010000000000000005").read_bytes() == b"w"
    assert (out / "wal/000000010000000000000006.partial").exists()


def test_prune_keeps_recent_bases_and_the_wal_they_need(dir_store, tmp_path):
    target = dir_store.store()
    for stamp, wal in (("1", "04"), ("2", "06"), ("3", "08")):
        target.put_stream(f"pg/base/{stamp}/base.tar.gz", io.BytesIO(b"t"))
        target.put_stream(f"pg/base/{stamp}/COMPLETE", io.BytesIO(b"1"))
        target.put_stream(
            f"pg/base/{stamp}/START_WAL",
            io.BytesIO(f"0000000100000000000000{wal}".encode()),
        )
    for wal in ("04", "05", "06", "07", "08"):
        target.put_stream(f"pg/wal/0000000100000000000000{wal}", io.BytesIO(b"w"))
    dir_store.prune_base("pg/base", "pg/wal", 2)
    assert dir_store.latest_complete_base(target, "pg/base") == "3"
    assert not target.list("pg/base/1/")
    assert target.list("pg/wal") == [
        f"pg/wal/0000000100000000000000{w}" for w in ("06", "07", "08")
    ]


def test_restore_script_refuses_to_overwrite_a_data_directory(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "PG_VERSION").write_text("16")
    out = subprocess.run(
        ["sh", str(FILES / "restore-postgres.sh"), str(tmp_path), str(data)],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 1 and "not empty" in out.stderr


@pytest.mark.parametrize(
    "script",
    [
        "pg-basebackup.sh",
        "pg-wal-receive.sh",
        "restore-postgres.sh",
        "restore-neo4j.sh",
    ],
)
def test_shell_scripts_parse(script):
    subprocess.run(["sh", "-n", str(FILES / script)], check=True)


def test_drill_script_parses():
    subprocess.run(
        ["bash", "-n", str(ROOT / "scripts/backup/restore-drill.sh")], check=True
    )


def test_compare_counts_finds_a_difference(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("public.x|10\npublic.y|5\n")
    b.write_text("public.x|10\npublic.y|4\n")
    run = lambda *x: subprocess.run(  # noqa: E731
        ["python3", str(ROOT / "scripts/backup/compare-counts.py"), *map(str, x)],
        capture_output=True,
        text=True,
    )
    bad = run(a, b, 0)
    assert bad.returncode == 1 and "MISMATCH public.y source=5 restored=4" in bad.stdout
    assert run(a, a, 0).returncode == 0
    assert run(a, b, 30).returncode == 0
    empty = tmp_path / "empty"
    empty.write_text("")
    assert run(empty, empty, 0).returncode == 1


@pytest.mark.skipif(
    not os.environ.get("RUN_RESTORE_DRILLS"),
    reason="set RUN_RESTORE_DRILLS=1, these take minutes",
)
@pytest.mark.parametrize("mode", ["docker", "neo4j-docker"])
def test_restore_drills(mode):
    assert docker_works()
    out = subprocess.run(
        ["bash", str(ROOT / "scripts/backup/restore-drill.sh"), mode],
        capture_output=True,
        text=True,
        timeout=900,
        env={
            **os.environ,
            "PATH": f"{Path.home()}/.docker/bin:/opt/homebrew/bin:{os.environ['PATH']}",
        },
    )
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert "PASSED" in out.stdout
