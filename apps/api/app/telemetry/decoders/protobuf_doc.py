"""Protocol Buffers, from an uploaded .proto or a descriptor set."""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from typing import Any

from app.telemetry.connectors.base import ConfigField
from app.telemetry.decoders.base import DecodeError, DocumentDecoder


def _descriptor_set(cfg: dict[str, Any]) -> bytes:
    if cfg.get("descriptor_set"):
        try:
            return base64.b64decode(cfg["descriptor_set"])
        except ValueError:
            raise DecodeError(
                "The descriptor set must be base64, as protoc --descriptor_set_out writes it"
            ) from None
    text = cfg.get("proto")
    if not text:
        raise DecodeError("Upload a .proto file or a descriptor set for this decoder")
    try:
        import grpc_tools
        from grpc_tools import protoc
    except ImportError:  # pragma: no cover
        raise DecodeError(
            "Compiling a .proto needs grpcio-tools, upload a descriptor set instead"
        ) from None
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "upload.proto")
        out = os.path.join(d, "out.desc")
        with open(src, "w", encoding="utf-8") as f:
            f.write(text)
        inc = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
        args = [
            "protoc",
            f"-I{d}",
            f"-I{inc}",
            "--include_imports",
            f"--descriptor_set_out={out}",
            src,
        ]
        if protoc.main(args) != 0 or not os.path.exists(out):
            raise DecodeError(
                "The .proto file did not compile, check its syntax and imports"
            )
        with open(out, "rb") as f:
            return f.read()


def message_class(cfg: dict[str, Any]) -> Any:
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    fds = descriptor_pb2.FileDescriptorSet()
    try:
        fds.ParseFromString(_descriptor_set(cfg))
    except DecodeError:
        raise
    except Exception:  # noqa: BLE001
        raise DecodeError("The descriptor set is not a FileDescriptorSet") from None
    pool = descriptor_pool.DescriptorPool()
    for fd in fds.file:
        pool.Add(fd)
    names = []
    for fd in fds.file:
        prefix = f"{fd.package}." if fd.package else ""
        names.extend(prefix + m.name for m in fd.message_type)
    want = cfg.get("message") or (names[-1] if names else "")
    try:
        desc = pool.FindMessageTypeByName(want)
    except KeyError:
        raise DecodeError(
            f"There is no message {want!r} in the schema, it has {', '.join(names[:10])}"
        ) from None
    return message_factory.GetMessageClass(desc)


class ProtobufDecoder(DocumentDecoder):
    name = "protobuf"
    label = "Protocol Buffers"
    description = "Messages of one type from an uploaded .proto or descriptor set, read field by field."
    config_fields = (
        ConfigField(
            key="proto",
            label=".proto file",
            kind="string",
            required=False,
            description="Paste or upload the schema.",
        ),
        ConfigField(
            key="descriptor_set",
            label="Descriptor set",
            kind="string",
            required=False,
            description="Base64 of protoc --include_imports --descriptor_set_out, instead of a .proto.",
        ),
        ConfigField(
            key="message",
            label="Message type",
            kind="string",
            required=False,
            description="Full name, such as acme.Reading. Empty takes the last one.",
        ),
    )

    _cache: dict[str, Any] = {}

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        from google.protobuf import json_format

        key = hashlib.sha1(
            repr(sorted((k, str(v)) for k, v in config.items())).encode()
        ).hexdigest()
        cls = self._cache.get(key)
        if cls is None:
            cls = message_class(config)
            self._cache[key] = cls
        msg = cls()
        try:
            msg.ParseFromString(payload)
        except Exception:  # noqa: BLE001
            raise DecodeError(
                f"The payload is not a {cls.DESCRIPTOR.full_name} message"
            ) from None
        return [json_format.MessageToDict(msg, preserving_proto_field_name=True)]
