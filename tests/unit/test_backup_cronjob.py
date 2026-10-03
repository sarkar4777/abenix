"""The Postgres backup CronJob uploads to S3 without an aws cli and keeps the PVC path."""

from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "infra/helm/abenix"

needs_helm = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _render(values_file: str, *sets: str) -> dict:
    cmd = [
        "helm",
        "template",
        "abenix",
        str(CHART),
        "-f",
        str(CHART / values_file),
        "--set",
        "backup.enabled=true",
        "--show-only",
        "templates/backup-cronjob.yaml",
    ]
    for s in sets:
        cmd += ["--set", s]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    job = next(d for d in docs if d["metadata"]["name"].endswith("-pg-backup"))
    return job["spec"]["jobTemplate"]["spec"]["template"]["spec"]


S3 = ("objectStorage.type=s3", "objectStorage.bucket=abenix-files")


@needs_helm
@pytest.mark.parametrize("values_file", ["values-local.yaml", "values-azure.yaml"])
def test_s3_dump_then_upload_with_boto3(values_file):
    spec = _render(values_file, *S3)
    (dump,) = spec["initContainers"]
    (upload,) = spec["containers"]
    assert dump["image"].startswith("postgres:")
    assert "pg_dump" in dump["command"][-1]
    assert "/backup/.latest" in dump["command"][-1]
    assert upload["command"] == ["python3", "-c"]
    script = upload["args"][0]
    assert "import boto3" in script
    assert "aws s3" not in dump["command"][-1] + script
    assert "postgres:" not in upload["image"]
    env = {e["name"]: e for e in upload["env"]}
    assert env["BACKUP_BUCKET"]["value"] == "abenix-files"
    assert env["STORAGE_S3_ACCESS_KEY"]["valueFrom"]["secretKeyRef"]["optional"]
    mount = upload["volumeMounts"][0]
    assert mount["mountPath"] == "/backup" and mount["readOnly"]


@needs_helm
def test_backup_bucket_override_wins():
    spec = _render("values-local.yaml", *S3, "backup.s3Bucket=pg-dumps")
    env = {e["name"]: e for e in spec["containers"][0]["env"]}
    assert env["BACKUP_BUCKET"]["value"] == "pg-dumps"


@needs_helm
def test_local_storage_keeps_the_single_pg_container():
    spec = _render("values-local.yaml")
    assert "initContainers" not in spec
    (pg,) = spec["containers"]
    assert pg["image"].startswith("postgres:")
    assert "/backup/weekly" in pg["command"][-1]
    assert "emptyDir" in spec["volumes"][0]


@needs_helm
def test_pvc_is_mounted_when_enabled():
    for sets in ((), S3):
        spec = _render(
            "values-local.yaml", "backup.persistentVolume.enabled=true", *sets
        )
        claim = spec["volumes"][0]["persistentVolumeClaim"]["claimName"]
        assert claim.endswith("-backup")


class _FakeS3:
    def __init__(self, existing):
        self.objects = set(existing)
        self.uploads = []
        self.deleted = []

    def upload_file(self, path, bucket, key):
        assert Path(path).exists()
        self.uploads.append((bucket, key))
        self.objects.add(key)

    def get_paginator(self, _name):
        store = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k}
                        for k in sorted(store.objects)
                        if k.startswith(Prefix)
                    ]
                }

        return _P()

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.objects.discard(Key)


def _upload_script() -> str:
    text = (CHART / "templates/backup-cronjob.yaml").read_text(encoding="utf-8")
    marker = text.index("import datetime, os\n                  import boto3")
    start = text.rindex("\n", 0, marker) + 1
    end = text.index("              env:", start)
    lines = text[start:end].splitlines()
    return "\n".join(line[18:] if line.strip() else "" for line in lines)


def test_upload_script_uploads_and_prunes(tmp_path, monkeypatch):
    name = "abenix-pg-20261003-020000.dump"
    (tmp_path / name).write_bytes(b"PGDMP")
    (tmp_path / ".latest").write_text(name + "\n", encoding="utf-8")
    old_daily = [f"backups/daily/abenix-pg-2026090{i}-020000.dump" for i in range(1, 9)]
    fake = _FakeS3(old_daily + ["backups/daily/README"])
    seen = {}

    def client(service, **kw):
        seen.update(service=service, **kw)
        return fake

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=client))
    monkeypatch.setenv("BACKUP_BUCKET", "bk")
    monkeypatch.setenv("STORAGE_S3_REGION", "eu-west-1")
    monkeypatch.setenv("STORAGE_S3_ENDPOINT", "")
    monkeypatch.setenv("STORAGE_S3_ACCESS_KEY", "")
    script = _upload_script().replace("/backup", str(tmp_path).replace("\\", "/"))
    exec(compile(script, "s3-upload", "exec"), {})

    assert seen == {"service": "s3", "region_name": "eu-west-1"}
    assert ("bk", f"backups/daily/{name}") in fake.uploads
    daily = sorted(k for k in fake.objects if k.startswith("backups/daily/abenix-pg-"))
    assert len(daily) == 7 and daily[-1].endswith(name)
    assert "backups/daily/README" in fake.objects
    assert fake.deleted == old_daily[:2]


def test_upload_script_refuses_without_a_bucket(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "boto3", types.SimpleNamespace(client=lambda *a, **k: None)
    )
    monkeypatch.setenv("BACKUP_BUCKET", "")
    with pytest.raises(SystemExit, match="no bucket"):
        exec(compile(_upload_script(), "s3-upload", "exec"), {})
