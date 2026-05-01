"""Unit tests for the 18 new ecosystem tools."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Make engine.* importable the same way agent_executor.py does.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.tools.address_normalize import AddressNormalizeTool
from engine.tools.browser_automation import BrowserAutomationTool
from engine.tools.cloud_cost import CloudCostTool
from engine.tools.crypto_market import CryptoMarketTool
from engine.tools.sandboxed_job import SandboxedJobTool
from engine.tools.fred_economic import FredEconomicTool
from engine.tools.geocoding import GeocodingTool
from engine.tools.gov_data_us import GovDataUSTool
from engine.tools.mermaid_diagram import MermaidDiagramTool
from engine.tools.patents_trademarks import PatentsTrademarksTool
from engine.tools.plotly_chart import PlotlyChartTool
from engine.tools.semantic_diff import SemanticDiffTool
from engine.tools.translation import TranslationTool
from engine.tools.twilio_sms import TwilioSmsTool
from engine.tools.weather import WeatherTool
from engine.tools.world_bank import WorldBankTool
from engine.tools.zapier_pass_through import ZapierPassThroughTool

ALL_TOOL_CLASSES = [
    WeatherTool,
    GeocodingTool,
    WorldBankTool,
    CryptoMarketTool,
    FredEconomicTool,
    GovDataUSTool,
    PatentsTrademarksTool,
    MermaidDiagramTool,
    SemanticDiffTool,
    AddressNormalizeTool,
    TranslationTool,
    PlotlyChartTool,
    TwilioSmsTool,
    BrowserAutomationTool,
    SandboxedJobTool,
    CloudCostTool,
    ZapierPassThroughTool,
]


# ───────────────────────────── shape / contract ─────────────────────────────
class TestContract:
    """Every new tool must satisfy the BaseTool contract."""

    @pytest.mark.parametrize("cls", ALL_TOOL_CLASSES)
    def test_has_required_attrs(self, cls):
        t = cls()
        assert isinstance(t.name, str) and t.name
        assert isinstance(t.description, str) and len(t.description) > 20
        assert isinstance(t.input_schema, dict)
        assert t.input_schema.get("type") == "object"
        assert "properties" in t.input_schema
        # Every required field must be declared in properties
        for req in t.input_schema.get("required", []):
            assert (
                req in t.input_schema["properties"]
            ), f"{cls.__name__}: required field '{req}' missing from properties"


# ────────────────────────── pure-compute tests ──────────────────────────────
class TestPureCompute:
    def test_mermaid_flowchart(self):
        t = MermaidDiagramTool()
        r = asyncio.run(
            t.execute(
                {
                    "diagram_type": "flowchart",
                    "direction": "LR",
                    "nodes": [
                        {"id": "a", "label": "Start"},
                        {"id": "b", "label": "Process"},
                        {"id": "c", "label": "End"},
                    ],
                    "edges": [
                        {"from": "a", "to": "b"},
                        {"from": "b", "to": "c", "label": "done"},
                    ],
                }
            )
        )
        assert not r.is_error
        assert "flowchart LR" in r.metadata["source"]
        assert '"Start"' in r.metadata["source"]
        assert "-- done -->" in r.metadata["source"]

    def test_mermaid_pie(self):
        t = MermaidDiagramTool()
        r = asyncio.run(
            t.execute(
                {
                    "diagram_type": "pie",
                    "title": "Portfolio split",
                    "slices": [
                        {"label": "PPA", "value": 5},
                        {"label": "Gas", "value": 2},
                    ],
                }
            )
        )
        assert not r.is_error
        assert "pie title Portfolio split" in r.metadata["source"]
        assert '"PPA" : 5' in r.metadata["source"]

    def test_semantic_diff_text(self):
        t = SemanticDiffTool()
        r = asyncio.run(
            t.execute(
                {
                    "mode": "text",
                    "left": "Payment due in 30 days.\n\nLate fee is 2%.",
                    "right": "Payment due in 45 days.\n\nLate fee is 2%.\n\nArbitration in London.",
                }
            )
        )
        assert not r.is_error
        m = r.metadata
        # One paragraph changed (30->45 days), one added (arbitration clause)
        assert len(m["changed_paragraphs"]) >= 1
        assert any("45 days" in p["after"] for p in m["changed_paragraphs"])
        assert any("Arbitration" in p for p in m["added_paragraphs"])
        assert 0 < m["similarity_ratio"] < 1

    def test_semantic_diff_json(self):
        t = SemanticDiffTool()
        r = asyncio.run(
            t.execute(
                {
                    "mode": "json",
                    "left": {"price": 100, "term_years": 10, "party": "ACME"},
                    "right": {
                        "price": 120,
                        "term_years": 10,
                        "party": "ACME",
                        "jurisdiction": "UK",
                    },
                }
            )
        )
        assert not r.is_error
        ops = r.metadata["ops"]
        ops_by_path = {o["path"]: o for o in ops}
        assert ops_by_path["/price"]["op"] == "changed"
        assert ops_by_path["/price"]["before"] == 100
        assert ops_by_path["/price"]["after"] == 120
        assert ops_by_path["/jurisdiction"]["op"] == "added"

    def test_address_normalize_us(self):
        t = AddressNormalizeTool()
        r = asyncio.run(
            t.execute(
                {"address": "1600 Amphitheatre Parkway, Mountain View, CA 94043, USA"}
            )
        )
        assert not r.is_error
        m = r.metadata
        assert m["country"] == "US"
        assert m["state"] == "CA"
        assert m["postal_code"] == "94043"
        assert "Mountain View" in (m["city"] or "")

    def test_address_normalize_uk(self):
        t = AddressNormalizeTool()
        r = asyncio.run(
            t.execute(
                {"address": "10 Downing Street, London, SW1A 2AA, United Kingdom"}
            )
        )
        assert not r.is_error
        m = r.metadata
        assert m["country"] == "GB"
        assert m["postal_code"] and m["postal_code"].replace(" ", "") == "SW1A2AA"

    def test_plotly_line(self):
        t = PlotlyChartTool()
        r = asyncio.run(
            t.execute(
                {
                    "chart_type": "line",
                    "title": "Test",
                    "series": [{"name": "s1", "x": [1, 2, 3], "y": [10, 20, 15]}],
                }
            )
        )
        assert not r.is_error
        fig = r.metadata["figure"]
        assert fig["data"][0]["type"] == "scatter"
        assert fig["layout"]["title"] == "Test"

    def test_plotly_pie(self):
        t = PlotlyChartTool()
        r = asyncio.run(
            t.execute(
                {
                    "chart_type": "pie",
                    "slices": [
                        {"label": "A", "value": 30},
                        {"label": "B", "value": 70},
                    ],
                    "donut": True,
                }
            )
        )
        assert not r.is_error
        fig = r.metadata["figure"]
        assert fig["data"][0]["type"] == "pie"
        assert fig["data"][0]["hole"] == 0.4


# ─────────────────── auth-gated tools gracefully skip ──────────────────────
class TestGracefulSkip:
    """Tools that need credentials must return a structured 'skipped' result
    (not raise, not crash) when the credentials aren't present."""

    def test_translation_skips_without_key(self, monkeypatch):
        monkeypatch.delenv("DEEPL_API_KEY", raising=False)
        monkeypatch.delenv("LIBRETRANSLATE_URL", raising=False)
        r = asyncio.run(
            TranslationTool().execute({"text": "hello", "target_lang": "de"})
        )
        assert not r.is_error
        assert r.metadata.get("skipped") is True
        assert r.metadata.get("provider") == "none"

    def test_twilio_skips_without_creds(self, monkeypatch):
        for k in (
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_FROM_NUMBER",
            "TWILIO_WHATSAPP_FROM",
        ):
            monkeypatch.delenv(k, raising=False)
        r = asyncio.run(
            TwilioSmsTool().execute(
                {"to": "+447700900123", "body": "hello", "channel": "sms"}
            )
        )
        assert not r.is_error
        assert r.metadata.get("skipped") is True
        assert r.metadata.get("queued", {}).get("body") == "hello"

    def test_zapier_nla_skips_without_key(self, monkeypatch):
        monkeypatch.delenv("ZAPIER_NLA_KEY", raising=False)
        r = asyncio.run(ZapierPassThroughTool().execute({"operation": "list_actions"}))
        assert not r.is_error
        assert r.metadata.get("skipped") is True

    def test_sandboxed_job_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SANDBOXED_JOB_ENABLED", raising=False)
        r = asyncio.run(
            SandboxedJobTool().execute({"image": "alpine", "command": "echo hi"})
        )
        assert r.is_error
        assert "SANDBOXED_JOB_ENABLED" in r.metadata.get("reason", "")

    def test_sandboxed_job_image_allowlist_enforced(self, monkeypatch):
        monkeypatch.setenv("SANDBOXED_JOB_ENABLED", "true")
        monkeypatch.setenv(
            "SANDBOXED_JOB_ALLOWED_IMAGES", "alpine:3.20,python:3.12-slim"
        )
        r = asyncio.run(
            SandboxedJobTool().execute(
                {
                    "image": "ubuntu:latest",
                    "command": "echo hi",
                }
            )
        )
        assert r.is_error
        assert "not in SANDBOXED_JOB_ALLOWED_IMAGES" in r.content

    def test_sandboxed_job_network_requires_host_opt_in(self, monkeypatch):
        monkeypatch.setenv("SANDBOXED_JOB_ENABLED", "true")
        monkeypatch.setenv("SANDBOXED_JOB_ALLOWED_IMAGES", "alpine:3.20")
        monkeypatch.delenv("SANDBOXED_JOB_ALLOW_NETWORK", raising=False)
        r = asyncio.run(
            SandboxedJobTool().execute(
                {
                    "image": "alpine:3.20",
                    "command": "echo hi",
                    "network": True,
                }
            )
        )
        assert r.is_error
        assert "SANDBOXED_JOB_ALLOW_NETWORK" in r.content

    def test_cloud_cost_all_providers_skipped(self, monkeypatch):
        for k in (
            "AWS_ACCESS_KEY_ID",
            "GCP_BILLING_PROJECT",
            "GCP_BILLING_BQ_DATASET",
            "AZURE_SUBSCRIPTION_ID",
        ):
            monkeypatch.delenv(k, raising=False)
        r = asyncio.run(CloudCostTool().execute({"operation": "all"}))
        assert not r.is_error
        providers = r.metadata["providers"]
        assert len(providers) == 3
        assert all(p.get("skipped") for p in providers)


# ─────────────────────────── real public APIs ──────────────────────────────
# These hit the real internet. Mark them as slow / network so CI can skip if
# offline. They're kept in-file so a developer can run them locally to check
# the provider is still up.

NETWORK = pytest.mark.skipif(
    os.environ.get("SKIP_NETWORK_TESTS", "").lower() in ("1", "true", "yes"),
    reason="SKIP_NETWORK_TESTS is set",
)


class TestPublicAPIs:
    @NETWORK
    def test_weather_berlin(self):
        r = asyncio.run(
            WeatherTool().execute({"location": "Berlin", "forecast_days": 2})
        )
        assert not r.is_error, r.content
        assert "Berlin" in r.content
        assert "Forecast" in r.content or r.metadata.get("daily")

    @NETWORK
    def test_weather_coords(self):
        r = asyncio.run(
            WeatherTool().execute({"location": "52.52,13.405", "forecast_days": 0})
        )
        assert not r.is_error
        assert r.metadata.get("current")

    @NETWORK
    def test_geocoding_forward(self):
        r = asyncio.run(GeocodingTool().execute({"query": "Eiffel Tower"}))
        assert not r.is_error
        assert r.metadata.get("results")
        first = r.metadata["results"][0]
        # Eiffel Tower is ~48.858, 2.294
        assert 48 < first["lat"] < 49
        assert 2 < first["lon"] < 3

    @NETWORK
    def test_world_bank_gdp(self):
        r = asyncio.run(
            WorldBankTool().execute(
                {
                    "country_code": "USA",
                    "indicator": "gdp_usd",
                    "start_year": 2018,
                    "end_year": 2022,
                }
            )
        )
        assert not r.is_error, r.content
        assert any("GDP" in r.content for _ in [0]) or r.metadata.get("values")

    @NETWORK
    def test_crypto_price(self):
        r = asyncio.run(
            CryptoMarketTool().execute(
                {"operation": "price", "coin_id": "bitcoin", "vs_currency": "usd"}
            )
        )
        # CoinGecko rate-limits; treat 429 as soft-ok but not a code failure
        if r.is_error and "429" in r.content:
            pytest.skip("CoinGecko rate limit hit")
        assert not r.is_error, r.content
        assert r.metadata.get("current_price") or "Price:" in r.content

    @NETWORK
    def test_fred_cpi_public_csv(self, monkeypatch):
        # Force the public-CSV path so we don't depend on FRED_API_KEY
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        r = asyncio.run(FredEconomicTool().execute({"series_id": "cpi", "limit": 5}))
        if r.is_error:
            pytest.skip(f"FRED CSV fallback unavailable: {r.content[:150]}")
        assert r.metadata.get("source") == "fred-csv-public"
        assert r.metadata.get("observations")

    @NETWORK
    def test_gov_data_us_lookup(self):
        r = asyncio.run(
            GovDataUSTool().execute(
                {
                    "operation": "lookup_company",
                    "query": "MSFT",
                    "limit": 3,
                }
            )
        )
        if r.is_error:
            pytest.skip(f"SEC EDGAR unavailable: {r.content[:100]}")
        assert (
            "MICROSOFT"
            in (r.metadata.get("company", {}).get("title", "") or r.content).upper()
        )
        assert r.metadata.get("filings")
