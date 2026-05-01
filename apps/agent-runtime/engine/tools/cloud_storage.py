"""Cloud Storage Tool — S3, GCS, Azure Blob, and local filesystem operations."""

from __future__ import annotations

import json
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class CloudStorageTool(BaseTool):
    name = "cloud_storage"
    description = (
        "Perform operations on cloud storage: S3, GCS, Azure Blob, or local filesystem. "
        "Supports list, read, write, and delete operations. "
        "Use URL schemes: s3://bucket/key, gs://bucket/key, az://container/blob, file:///path."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "list_objects",
                    "read_object",
                    "write_object",
                    "delete_object",
                    "get_info",
                ],
                "description": "Storage operation to perform",
            },
            "path": {
                "type": "string",
                "description": "Storage path (e.g., s3://my-bucket/data/file.csv)",
            },
            "content": {
                "type": "string",
                "description": "Content to write (for write_object only)",
            },
            "prefix": {
                "type": "string",
                "description": "Prefix filter for list_objects",
            },
            "max_keys": {
                "type": "integer",
                "description": "Max objects to list (default: 100)",
                "default": 100,
            },
        },
        "required": ["operation", "path"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation", "")
        path = arguments.get("path", "")

        if not operation or not path:
            return ToolResult(
                content="Error: operation and path are required", is_error=True
            )

        # Detect backend from URL scheme
        if path.startswith("s3://"):
            return await self._s3_operation(operation, path, arguments)
        elif path.startswith("gs://"):
            return await self._gcs_operation(operation, path, arguments)
        elif path.startswith("az://"):
            return await self._azure_operation(operation, path, arguments)
        elif path.startswith("file://"):
            return await self._local_operation(operation, path, arguments)
        else:
            return ToolResult(
                content="Error: Unrecognized URL scheme. Use s3://, gs://, az://, or file://",
                is_error=True,
            )

    async def _s3_operation(self, operation: str, path: str, args: dict) -> ToolResult:
        try:
            import boto3

            # Parse s3://bucket/key
            parts = path[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""

            s3 = boto3.client("s3")

            if operation == "list_objects":
                prefix = args.get("prefix", key)
                max_keys = min(args.get("max_keys", 100), 1000)
                resp = s3.list_objects_v2(
                    Bucket=bucket, Prefix=prefix, MaxKeys=max_keys
                )
                objects = [
                    {
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "modified": obj["LastModified"].isoformat(),
                    }
                    for obj in resp.get("Contents", [])
                ]
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "bucket": bucket,
                            "prefix": prefix,
                            "objects": objects,
                            "count": len(objects),
                        }
                    )
                )

            elif operation == "read_object":
                resp = s3.get_object(Bucket=bucket, Key=key)
                body = resp["Body"].read()
                # Try text, fallback to base64
                try:
                    text = body.decode("utf-8")
                    if len(text) > 500_000:
                        text = text[:500_000] + "\n[Truncated at 500KB]"
                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "success",
                                "key": key,
                                "size": len(body),
                                "content_type": resp.get("ContentType", ""),
                                "content": text,
                            }
                        )
                    )
                except UnicodeDecodeError:
                    import base64

                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "success",
                                "key": key,
                                "size": len(body),
                                "content_type": resp.get("ContentType", ""),
                                "encoding": "base64",
                                "content": base64.b64encode(body[:100_000]).decode(),
                            }
                        )
                    )

            elif operation == "write_object":
                content = args.get("content", "")
                s3.put_object(Bucket=bucket, Key=key, Body=content.encode("utf-8"))
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "action": "written",
                            "key": key,
                            "size": len(content),
                        }
                    )
                )

            elif operation == "delete_object":
                s3.delete_object(Bucket=bucket, Key=key)
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "action": "deleted",
                            "key": key,
                        }
                    )
                )

            elif operation == "get_info":
                resp = s3.head_object(Bucket=bucket, Key=key)
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "key": key,
                            "size": resp["ContentLength"],
                            "content_type": resp.get("ContentType", ""),
                            "modified": resp["LastModified"].isoformat(),
                        }
                    )
                )

            return ToolResult(
                content=f"Error: Unknown operation: {operation}", is_error=True
            )

        except ImportError:
            return ToolResult(
                content="Error: boto3 not installed. Install with: pip install boto3",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(content=f"S3 error: {str(e)[:500]}", is_error=True)

    async def _gcs_operation(self, operation: str, path: str, args: dict) -> ToolResult:
        """Google Cloud Storage operations."""
        try:
            from google.cloud import storage

            client = storage.Client()
            parts = path[5:].split("/", 1)
            bucket_name = parts[0]
            blob_name = parts[1] if len(parts) > 1 else ""
            bucket = client.bucket(bucket_name)

            if operation == "list_objects":
                prefix = args.get("prefix", blob_name)
                max_keys = min(args.get("max_keys", 100), 1000)
                blobs = list(bucket.list_blobs(prefix=prefix, max_results=max_keys))
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "bucket": bucket_name,
                            "objects": [{"key": b.name, "size": b.size} for b in blobs],
                            "count": len(blobs),
                        }
                    )
                )

            elif operation == "read_object":
                blob = bucket.blob(blob_name)
                content = blob.download_as_text()
                if len(content) > 500_000:
                    content = content[:500_000] + "\n[Truncated]"
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "key": blob_name,
                            "content": content,
                        }
                    )
                )

            elif operation == "write_object":
                blob = bucket.blob(blob_name)
                blob.upload_from_string(args.get("content", ""))
                return ToolResult(
                    content=json.dumps(
                        {"status": "success", "action": "written", "key": blob_name}
                    )
                )

            return ToolResult(
                content=f"Error: Unknown operation: {operation}", is_error=True
            )

        except ImportError:
            return ToolResult(
                content="Error: google-cloud-storage not installed", is_error=True
            )
        except Exception as e:
            return ToolResult(content=f"GCS error: {str(e)[:500]}", is_error=True)

    async def _azure_operation(
        self, operation: str, path: str, args: dict
    ) -> ToolResult:
        """Azure Blob Storage operations."""
        try:
            from azure.storage.blob import BlobServiceClient

            conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            if not conn_str:
                return ToolResult(
                    content="Error: AZURE_STORAGE_CONNECTION_STRING not set",
                    is_error=True,
                )

            client = BlobServiceClient.from_connection_string(conn_str)
            parts = path[5:].split("/", 1)
            container = parts[0]
            blob_name = parts[1] if len(parts) > 1 else ""

            if operation == "list_objects":
                container_client = client.get_container_client(container)
                blobs = list(
                    container_client.list_blobs(name_starts_with=args.get("prefix", ""))
                )[:100]
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "container": container,
                            "objects": [{"key": b.name, "size": b.size} for b in blobs],
                        }
                    )
                )

            elif operation == "read_object":
                blob_client = client.get_blob_client(container, blob_name)
                content = blob_client.download_blob().readall().decode("utf-8")
                if len(content) > 500_000:
                    content = content[:500_000] + "\n[Truncated]"
                return ToolResult(
                    content=json.dumps({"status": "success", "content": content})
                )

            return ToolResult(
                content=f"Error: Unknown operation: {operation}", is_error=True
            )

        except ImportError:
            return ToolResult(
                content="Error: azure-storage-blob not installed", is_error=True
            )
        except Exception as e:
            return ToolResult(content=f"Azure error: {str(e)[:500]}", is_error=True)

    async def _local_operation(
        self, operation: str, path: str, args: dict
    ) -> ToolResult:
        """Local filesystem operations (for development/testing)."""
        import pathlib

        local_path = pathlib.Path(path.replace("file://", ""))

        if operation == "list_objects":
            if not local_path.is_dir():
                return ToolResult(
                    content=f"Error: {local_path} is not a directory", is_error=True
                )
            files = sorted(local_path.iterdir())[:100]
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "success",
                        "path": str(local_path),
                        "objects": [
                            {
                                "key": f.name,
                                "size": f.stat().st_size if f.is_file() else 0,
                                "type": "file" if f.is_file() else "dir",
                            }
                            for f in files
                        ],
                    }
                )
            )

        elif operation == "read_object":
            if not local_path.is_file():
                return ToolResult(
                    content=f"Error: {local_path} not found", is_error=True
                )
            content = local_path.read_text(errors="replace")
            if len(content) > 500_000:
                content = content[:500_000] + "\n[Truncated]"
            return ToolResult(
                content=json.dumps({"status": "success", "content": content})
            )

        elif operation == "write_object":
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(args.get("content", ""))
            return ToolResult(
                content=json.dumps(
                    {"status": "success", "action": "written", "path": str(local_path)}
                )
            )

        return ToolResult(
            content=f"Error: Unknown operation: {operation}", is_error=True
        )
