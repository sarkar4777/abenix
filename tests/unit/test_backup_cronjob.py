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


def _render_all(values_file: str, *sets: str) -> list[dict]:
    cmd = ["helm", "template", "abenix", str(CHART), "-f", str(CHART / values_file)]
    for s in ("backup.enabled=true", *sets):
        cmd += ["--set", s]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _named(docs: list[dict], suffix: str) -> dict:
    return next(d for d in docs if d["metadata"]["name"].endswith(suffix))


@needs_helm
def test_dump_job_takes_its_limits_from_values():
    spec = _named(
        _render_all(
            "values-local.yaml",
            "backup.activeDeadlineSeconds=14400",
            "backup.scratchSize=200Gi",
            "backup.resources.limits.cpu=4",
            "backup.compress=3",
        ),
        "-pg-backup",
    )["spec"]["jobTemplate"]["spec"]
    assert spec["activeDeadlineSeconds"] == 14400
    pod = spec["template"]["spec"]
    assert pod["volumes"][0]["emptyDir"]["sizeLimit"] == "200Gi"
    assert pod["containers"][0]["resources"]["limits"]["cpu"] == 4
    assert "--compress=3" in pod["containers"][0]["command"][-1]


@needs_helm
@pytest.mark.parametrize(
    "values_file,sets,store",
    [
        ("values-production.yaml", (), "s3"),
        ("values-azure.yaml", ("backup.target.type=azure",), "azure"),
        ("values-backup-physical.yaml", ("objectStorage.type=local",), "dir"),
    ],
)
def test_physical_strategy_has_no_dump_and_ships_to_the_target(
    values_file, sets, store
):
    docs = _render_all(values_file, "backup.postgres.strategy=physical", *sets)
    names = {d["metadata"]["name"] for d in docs}
    assert "abenix-pg-backup" not in names
    base = _named(docs, "-pg-basebackup")["spec"]["jobTemplate"]["spec"]["template"][
        "spec"
    ]
    assert {c["name"] for c in base["containers"]} == {"pg-basebackup", "uploader"}
    # the pipe is the only local storage, a base backup never sits on a volume
    work = next(v for v in base["volumes"] if v["name"] == "work")
    assert work["emptyDir"]["sizeLimit"] == "16Mi"
    uploader = next(c for c in base["containers"] if c["name"] == "uploader")
    env = {e["name"]: e.get("value") for e in uploader["env"]}
    assert env["BACKUP_STORE"] == store
    archiver = _named(docs, "-pg-wal-archiver")
    assert archiver["kind"] == "StatefulSet"
    assert archiver["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"][
        "storage"
    ]
    scripts = _named(docs, "-backup-scripts")["data"]
    assert (CHART / "files/backup_store.py").read_text().strip() == scripts[
        "backup_store.py"
    ].strip()
    pod = __import__("json").loads(_named(docs, "-backup-drill")["data"]["pod.json"])
    assert pod["spec"]["initContainers"][1]["command"][1].endswith(
        "restore-postgres.sh"
    )


@needs_helm
def test_external_strategy_renders_no_postgres_backup():
    docs = _render_all(
        "values-local.yaml",
        "backup.postgres.strategy=external",
        "backup.neo4j.enabled=true",
    )
    names = {d["metadata"]["name"] for d in docs}
    assert not {
        n for n in names if "pg-backup" in n or "basebackup" in n or "wal-archiver" in n
    }
    assert "abenix-neo4j-backup" in names


@needs_helm
def test_physical_without_any_target_is_refused_at_install():
    cmd = [
        "helm",
        "template",
        "abenix",
        str(CHART),
        "-f",
        str(CHART / "values-local.yaml"),
        "--set",
        "backup.enabled=true",
        "--set",
        "backup.postgres.strategy=physical",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode != 0 and "needs objectStorage" in out.stderr


@needs_helm
def test_production_uses_physical_and_a_slot_limit():
    docs = _render_all("values-production.yaml")
    assert any(d["metadata"]["name"].endswith("-pg-wal-archiver") for d in docs)
    values = yaml.safe_load((CHART / "values-production.yaml").read_text())
    assert (
        "max_slot_wal_keep_size"
        in values["postgresql"]["primary"]["extendedConfiguration"]
    )


@needs_helm
def test_wal_archiver_may_reach_postgres():
    docs = _render_all("values-production.yaml", "networkPolicy.enabled=true")
    text = yaml.safe_dump(docs)
    assert "wal-archiver" in text
