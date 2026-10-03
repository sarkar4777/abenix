"""Unified cloud cost / billing reader for AWS, GCP, and Azure."""

from __future__ import annotations

from datetime import date
from typing import Any

from engine import credentials
from engine.tools.base import BaseTool, ConfigField, ToolResult


def _month_window() -> tuple[str, str]:
    today = date.today()
    start = today.replace(day=1).isoformat()
    return start, today.isoformat()


async def _aws_summary() -> dict[str, Any]:
    if not credentials.get("AWS_ACCESS_KEY_ID"):
        return {
            "provider": "aws",
            "skipped": True,
            "reason": "AWS_ACCESS_KEY_ID is not configured, an admin can add it under Admin -> Tool Configuration",
        }
    try:
        import boto3  # type: ignore
    except ImportError:
        return {"provider": "aws", "skipped": True, "reason": "boto3 not installed"}
    start, end = _month_window()
    try:
        client = boto3.client(
            "ce",
            aws_access_key_id=credentials.get("AWS_ACCESS_KEY_ID") or None,
            aws_secret_access_key=credentials.get("AWS_SECRET_ACCESS_KEY") or None,
            region_name=credentials.get("AWS_REGION") or None,
        )
        resp = client.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        rows = []
        total = 0.0
        for group in resp.get("ResultsByTime", [{}])[0].get("Groups", []):
            svc = group.get("Keys", [""])[0]
            amt = float(
                group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0)
            )
            rows.append({"service": svc, "cost_usd": round(amt, 2)})
            total += amt
        rows.sort(key=lambda r: -r["cost_usd"])
        return {
            "provider": "aws",
            "period": {"start": start, "end": end},
            "total_usd": round(total, 2),
            "by_service": rows,
        }
    except Exception as e:
        return {"provider": "aws", "skipped": True, "reason": str(e)[:200]}


async def _gcp_summary() -> dict[str, Any]:
    project = credentials.get("GCP_BILLING_PROJECT").strip()
    dataset = credentials.get("GCP_BILLING_BQ_DATASET").strip()
    if not (project and dataset):
        return {
            "provider": "gcp",
            "skipped": True,
            "reason": "GCP_BILLING_PROJECT and GCP_BILLING_BQ_DATASET not set",
        }
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError:
        return {
            "provider": "gcp",
            "skipped": True,
            "reason": "google-cloud-bigquery not installed",
        }
    try:
        client = bigquery.Client(project=project)
        sql = f"""
            SELECT service.description AS service, SUM(cost) AS cost_usd
            FROM `{project}.{dataset}.gcp_billing_export_v1_*`
            WHERE DATE(usage_start_time) >= DATE_TRUNC(CURRENT_DATE(), MONTH)
            GROUP BY service
            ORDER BY cost_usd DESC
            LIMIT 100
        """
        rows = [
            {"service": r["service"], "cost_usd": round(float(r["cost_usd"] or 0), 2)}
            for r in client.query(sql).result()
        ]
        total = round(sum(r["cost_usd"] for r in rows), 2)
        return {"provider": "gcp", "total_usd": total, "by_service": rows}
    except Exception as e:
        return {"provider": "gcp", "skipped": True, "reason": str(e)[:200]}


async def _azure_summary() -> dict[str, Any]:
    sub = credentials.get("AZURE_SUBSCRIPTION_ID").strip()
    if not sub:
        return {
            "provider": "azure",
            "skipped": True,
            "reason": "AZURE_SUBSCRIPTION_ID not set (also need AZURE_CLIENT_ID/SECRET/TENANT)",
        }
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore
        from azure.mgmt.consumption import ConsumptionManagementClient  # type: ignore
    except ImportError:
        return {
            "provider": "azure",
            "skipped": True,
            "reason": "azure-identity / azure-mgmt-consumption not installed",
        }
    try:
        cred = DefaultAzureCredential()
        client = ConsumptionManagementClient(cred, sub)
        scope = f"/subscriptions/{sub}"
        usage = client.usage_details.list(scope=scope, top=200)
        agg: dict[str, float] = {}
        for u in usage:
            svc = (
                getattr(u, "instance_name", None)
                or getattr(u, "consumed_service", None)
                or "unknown"
            )
            cost = float(getattr(u, "cost_in_usd", 0) or 0)
            agg[svc] = agg.get(svc, 0.0) + cost
        rows = [
            {"service": k, "cost_usd": round(v, 2)}
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1])
        ]
        return {
            "provider": "azure",
            "total_usd": round(sum(r["cost_usd"] for r in rows), 2),
            "by_service": rows,
        }
    except Exception as e:
        return {"provider": "azure", "skipped": True, "reason": str(e)[:200]}


def _format(s: dict[str, Any]) -> str:
    p = s.get("provider", "?").upper()
    if s.get("skipped"):
        return f"  {p}: skipped ({s.get('reason')})"
    rows = s.get("by_service") or []
    lines = [f"  {p}: total ${s.get('total_usd', 0):,.2f}"]
    for r in rows[:8]:
        lines.append(f"    - {r['service'][:40]:40s} ${r['cost_usd']:>10,.2f}")
    if len(rows) > 8:
        lines.append(f"    ... +{len(rows) - 8} more services")
    return "\n".join(lines)


class CloudCostTool(BaseTool):
    name = "cloud_cost"
    risk_tier = "low"
    config_fields = (
        ConfigField(
            "AWS_ACCESS_KEY_ID",
            label="Access key id",
            kind="secret",
            required=False,
            group="AWS",
            signup_url="https://console.aws.amazon.com/iam",
        ),
        ConfigField(
            "AWS_SECRET_ACCESS_KEY",
            label="Secret access key",
            kind="secret",
            required=False,
            group="AWS",
        ),
        ConfigField(
            "AWS_REGION",
            label="Region",
            kind="string",
            required=False,
            group="AWS",
            default="us-east-1",
        ),
        ConfigField(
            "AZURE_SUBSCRIPTION_ID",
            label="Subscription id",
            kind="string",
            required=False,
            group="Azure",
        ),
        ConfigField(
            "GCP_BILLING_BQ_DATASET",
            label="Billing dataset",
            kind="string",
            required=False,
            group="Google Cloud",
        ),
        ConfigField(
            "GCP_BILLING_PROJECT",
            label="Billing project",
            kind="string",
            required=False,
            group="Google Cloud",
        ),
    )
    description = (
        "Read current-month cloud spend grouped by service from AWS Cost "
        "Explorer, GCP BigQuery billing export, and Azure Consumption. "
        "Each provider is skipped gracefully when its credentials or SDK "
        "aren't present. Operation 'all' aggregates whatever's configured."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["aws_summary", "gcp_summary", "azure_summary", "all"],
                "default": "all",
            },
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "all")
        try:
            if op == "aws_summary":
                results = [await _aws_summary()]
            elif op == "gcp_summary":
                results = [await _gcp_summary()]
            elif op == "azure_summary":
                results = [await _azure_summary()]
            elif op == "all":
                results = [
                    await _aws_summary(),
                    await _gcp_summary(),
                    await _azure_summary(),
                ]
            else:
                return ToolResult(content=f"Unknown operation: {op}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"cloud_cost error: {e}", is_error=True)

        total = sum(r.get("total_usd", 0) for r in results if not r.get("skipped"))
        active = [r for r in results if not r.get("skipped")]
        lines = [
            f"Cloud cost — {len(active)} provider(s) reporting, "
            f"{len(results) - len(active)} skipped",
            f"Combined month-to-date: ${total:,.2f}",
            "",
        ]
        for r in results:
            lines.append(_format(r))
        return ToolResult(
            content="\n".join(lines),
            metadata={"providers": results, "combined_total_usd": round(total, 2)},
        )
