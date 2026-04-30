"""Comprehensive tests for all advanced agent tools."""

from __future__ import annotations

import json
import os
import tempfile
import csv
import io

import pytest

from engine.tools.base import ToolRegistry
from engine.tools.document_extractor import DocumentExtractorTool
from engine.tools.csv_analyzer import CsvAnalyzerTool
from engine.tools.financial_calculator import FinancialCalculatorTool
from engine.tools.risk_analyzer import RiskAnalyzerTool
from engine.tools.json_transformer import JsonTransformerTool
from engine.tools.text_analyzer import TextAnalyzerTool
from engine.tools.code_executor import CodeExecutorTool
from engine.tools.date_calculator import DateCalculatorTool
from engine.tools.regex_extractor import RegexExtractorTool
from engine.tools.unit_converter import UnitConverterTool
from engine.tools.market_data import MarketDataTool
from engine.tools.http_client import HttpClientTool
from engine.tools.data_exporter import DataExporterTool
from engine.tools.spreadsheet_analyzer import SpreadsheetAnalyzerTool
from engine.tools.api_connector import ApiConnectorTool


# ---------- DocumentExtractorTool ----------

class TestDocumentExtractorTool:
    @pytest.fixture
    def extractor(self):
        return DocumentExtractorTool()

    @pytest.mark.asyncio
    async def test_extract_key_values_dates(self, extractor):
        text = "The contract was signed on January 15, 2024 and expires on 12/31/2029."
        result = await extractor.execute({"text": text, "extract_type": "key_values"})
        assert not result.is_error
        data = json.loads(result.content)
        assert len(data["key_values"]["dates"]) > 0

    @pytest.mark.asyncio
    async def test_extract_key_values_money(self, extractor):
        text = "The base price is $45.50/MWh with a total contract value of $12,500,000."
        result = await extractor.execute({"text": text, "extract_type": "key_values"})
        data = json.loads(result.content)
        assert len(data["key_values"]["monetary_amounts"]) >= 1

    @pytest.mark.asyncio
    async def test_extract_key_values_percentages(self, extractor):
        text = "Annual escalation of 2.5% applies. Capacity factor is expected at 35%."
        result = await extractor.execute({"text": text, "extract_type": "key_values"})
        data = json.loads(result.content)
        assert len(data["key_values"]["percentages"]) >= 2

    @pytest.mark.asyncio
    async def test_extract_tables_pipe(self, extractor):
        text = "| Name | Price |\n| --- | --- |\n| Solar | $45 |\n| Wind | $38 |\n"
        result = await extractor.execute({"text": text, "extract_type": "tables"})
        data = json.loads(result.content)
        assert len(data["tables"]) >= 1

    @pytest.mark.asyncio
    async def test_extract_entities_emails(self, extractor):
        text = "Contact us at support@example.com or sales@company.org for details."
        result = await extractor.execute({"text": text, "extract_type": "entities"})
        data = json.loads(result.content)
        assert len(data["entities"]["emails"]) >= 2

    @pytest.mark.asyncio
    async def test_extract_sections(self, extractor):
        text = "# Introduction\nSome text.\n\n# Methods\nMore text.\n\n# Results\nFinal text."
        result = await extractor.execute({"text": text, "extract_type": "sections"})
        data = json.loads(result.content)
        assert len(data["sections"]) >= 3

    @pytest.mark.asyncio
    async def test_custom_patterns(self, extractor):
        text = "Contract ID: PPA-2024-001. Reference: PPA-2024-002."
        result = await extractor.execute({
            "text": text,
            "extract_type": "key_values",
            "patterns": [r"PPA-\d{4}-\d{3}"],
        })
        data = json.loads(result.content)
        assert data["custom_matches"][0]["count"] == 2

    @pytest.mark.asyncio
    async def test_extract_from_file(self, extractor):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Contract signed on 2024-01-15 for $1,000,000")
            f.flush()
            result = await extractor.execute({"file_path": f.name, "extract_type": "all"})
        os.unlink(f.name)
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_missing_inputs(self, extractor):
        result = await extractor.execute({})
        assert result.is_error

    def test_to_dict(self, extractor):
        d = extractor.to_dict()
        assert d["name"] == "document_extractor"


# ---------- CsvAnalyzerTool ----------

class TestCsvAnalyzerTool:
    @pytest.fixture
    def analyzer(self):
        return CsvAnalyzerTool()

    @pytest.fixture
    def sample_csv(self):
        return "name,price,quantity\nWidget A,10.50,100\nWidget B,25.00,50\nWidget C,5.75,200\nWidget D,15.00,75"

    @pytest.mark.asyncio
    async def test_describe(self, analyzer, sample_csv):
        result = await analyzer.execute({"csv_text": sample_csv, "operation": "describe"})
        assert not result.is_error
        data = json.loads(result.content)
        assert data["shape"]["rows"] == 4
        assert data["shape"]["columns"] == 3

    @pytest.mark.asyncio
    async def test_filter(self, analyzer, sample_csv):
        result = await analyzer.execute({
            "csv_text": sample_csv,
            "operation": "filter",
            "filter_expr": "price > 10",
        })
        data = json.loads(result.content)
        assert data["matched"] == 3

    @pytest.mark.asyncio
    async def test_sort(self, analyzer, sample_csv):
        result = await analyzer.execute({
            "csv_text": sample_csv,
            "operation": "sort",
            "sort_by": "price",
            "sort_desc": True,
        })
        data = json.loads(result.content)
        first_price = float(data["rows"][0]["price"])
        assert first_price == 25.0

    @pytest.mark.asyncio
    async def test_quality(self, analyzer, sample_csv):
        result = await analyzer.execute({"csv_text": sample_csv, "operation": "quality"})
        data = json.loads(result.content)
        assert data["total_rows"] == 4
        assert data["duplicate_rows"] == 0

    @pytest.mark.asyncio
    async def test_frequency(self, analyzer):
        csv_text = "status\nactive\nactive\npending\nactive\nclosed"
        result = await analyzer.execute({
            "csv_text": csv_text,
            "operation": "frequency",
            "columns": ["status"],
        })
        data = json.loads(result.content)
        assert data["frequency"]["status"][0]["value"] == "active"
        assert data["frequency"]["status"][0]["count"] == 3

    @pytest.mark.asyncio
    async def test_group_by(self, analyzer):
        csv_text = "category,amount\nA,100\nB,200\nA,150\nB,50"
        result = await analyzer.execute({
            "csv_text": csv_text,
            "operation": "group_by",
            "group_column": "category",
            "columns": ["amount"],
            "agg_func": "sum",
        })
        data = json.loads(result.content)
        rows = {r["category"]: r["amount"] for r in data["rows"]}
        assert rows["A"] == 250.0
        assert rows["B"] == 250.0

    @pytest.mark.asyncio
    async def test_correlate(self, analyzer, sample_csv):
        result = await analyzer.execute({
            "csv_text": sample_csv,
            "operation": "correlate",
            "columns": ["price", "quantity"],
        })
        data = json.loads(result.content)
        assert "price" in data["correlation_matrix"]

    @pytest.mark.asyncio
    async def test_file_read(self, analyzer, sample_csv):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write(sample_csv)
            f.flush()
            result = await analyzer.execute({"file_path": f.name, "operation": "describe"})
        os.unlink(f.name)
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_missing_inputs(self, analyzer):
        result = await analyzer.execute({"operation": "describe"})
        assert result.is_error


# ---------- FinancialCalculatorTool ----------

class TestFinancialCalculatorTool:
    @pytest.fixture
    def fin_calc(self):
        return FinancialCalculatorTool()

    @pytest.mark.asyncio
    async def test_npv(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "npv",
            "params": {
                "discount_rate": 0.1,
                "initial_investment": 100000,
                "cash_flows": [30000, 35000, 40000, 45000],
            },
        })
        data = json.loads(result.content)
        assert "npv" in data
        assert isinstance(data["npv"], (int, float))

    @pytest.mark.asyncio
    async def test_irr(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "irr",
            "params": {
                "initial_investment": 100000,
                "cash_flows": [30000, 35000, 40000, 45000],
            },
        })
        data = json.loads(result.content)
        assert "irr" in data
        assert data["irr"] > 0

    @pytest.mark.asyncio
    async def test_lcoe(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "lcoe",
            "params": {
                "capex": 1500000,
                "annual_opex": 25000,
                "annual_generation_mwh": 2500,
                "lifetime_years": 25,
                "discount_rate": 0.08,
            },
        })
        data = json.loads(result.content)
        assert "lcoe_per_mwh" in data
        assert data["lcoe_per_mwh"] > 0

    @pytest.mark.asyncio
    async def test_amortization(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "amortization",
            "params": {"principal": 300000, "annual_rate": 0.06, "years": 30},
        })
        data = json.loads(result.content)
        assert data["monthly_payment"] > 0
        assert data["total_interest"] > 0

    @pytest.mark.asyncio
    async def test_escalation(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "escalation",
            "params": {"base_price": 45.0, "escalation_rate": 0.025, "years": 20},
        })
        data = json.loads(result.content)
        assert data["price_final_year"] > 45.0
        assert len(data["schedule"]) == 20

    @pytest.mark.asyncio
    async def test_wacc(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "wacc",
            "params": {
                "equity_value": 600000,
                "debt_value": 400000,
                "cost_of_equity": 0.12,
                "cost_of_debt": 0.06,
                "tax_rate": 0.21,
            },
        })
        data = json.loads(result.content)
        assert data["wacc"] > 0

    @pytest.mark.asyncio
    async def test_cagr(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "cagr",
            "params": {"beginning_value": 100, "ending_value": 200, "years": 5},
        })
        data = json.loads(result.content)
        assert data["cagr_percent"] > 0

    @pytest.mark.asyncio
    async def test_breakeven(self, fin_calc):
        result = await fin_calc.execute({
            "calculation": "breakeven",
            "params": {
                "fixed_costs": 50000,
                "variable_cost_per_unit": 20,
                "price_per_unit": 50,
            },
        })
        data = json.loads(result.content)
        assert data["breakeven_units"] > 0

    @pytest.mark.asyncio
    async def test_unknown_calculation(self, fin_calc):
        result = await fin_calc.execute({"calculation": "nonexistent", "params": {}})
        assert result.is_error


# ---------- RiskAnalyzerTool ----------

class TestRiskAnalyzerTool:
    @pytest.fixture
    def risk(self):
        return RiskAnalyzerTool()

    @pytest.mark.asyncio
    async def test_monte_carlo(self, risk):
        result = await risk.execute({
            "analysis_type": "monte_carlo",
            "params": {
                "variables": {
                    "revenue": {"distribution": "normal", "mean": 100000, "std": 15000},
                    "costs": {"distribution": "normal", "mean": 70000, "std": 10000},
                },
                "formula": "revenue - costs",
                "iterations": 1000,
                "seed": 42,
            },
        })
        data = json.loads(result.content)
        assert data["iterations"] == 1000
        assert "mean" in data
        assert "percentiles" in data

    @pytest.mark.asyncio
    async def test_sensitivity(self, risk):
        result = await risk.execute({
            "analysis_type": "sensitivity",
            "params": {
                "base_values": {"price": 50, "volume": 1000, "cost": 30000},
                "formula": "price * volume - cost",
                "variation_pct": 20,
            },
        })
        data = json.loads(result.content)
        assert "tornado" in data
        assert len(data["tornado"]) == 3

    @pytest.mark.asyncio
    async def test_scenario(self, risk):
        result = await risk.execute({
            "analysis_type": "scenario",
            "params": {
                "scenarios": {
                    "best": {"price": 60, "volume": 1200},
                    "base": {"price": 50, "volume": 1000},
                    "worst": {"price": 40, "volume": 800},
                },
                "formula": "price * volume",
                "probabilities": {"best": 0.25, "base": 0.50, "worst": 0.25},
            },
        })
        data = json.loads(result.content)
        assert data["best_case"] > data["worst_case"]

    @pytest.mark.asyncio
    async def test_risk_matrix(self, risk):
        result = await risk.execute({
            "analysis_type": "risk_matrix",
            "params": {
                "risks": [
                    {"name": "Market Risk", "likelihood": 4, "impact": 5},
                    {"name": "Tech Risk", "likelihood": 2, "impact": 3},
                    {"name": "Reg Risk", "likelihood": 3, "impact": 4},
                ],
            },
        })
        data = json.loads(result.content)
        assert data["total_risks"] == 3
        assert data["risks"][0]["risk_score"] >= data["risks"][-1]["risk_score"]

    @pytest.mark.asyncio
    async def test_expected_value(self, risk):
        result = await risk.execute({
            "analysis_type": "expected_value",
            "params": {
                "outcomes": [
                    {"name": "Win", "value": 100, "probability": 0.3},
                    {"name": "Break Even", "value": 0, "probability": 0.5},
                    {"name": "Lose", "value": -50, "probability": 0.2},
                ],
            },
        })
        data = json.loads(result.content)
        assert data["expected_value"] == 20.0


# ---------- JsonTransformerTool ----------

class TestJsonTransformerTool:
    @pytest.fixture
    def transformer(self):
        return JsonTransformerTool()

    @pytest.mark.asyncio
    async def test_query_nested(self, transformer):
        result = await transformer.execute({
            "data": {"users": [{"name": "Alice"}, {"name": "Bob"}]},
            "operation": "query",
            "path": "users.0.name",
        })
        data = json.loads(result.content)
        assert data == "Alice"

    @pytest.mark.asyncio
    async def test_filter(self, transformer):
        result = await transformer.execute({
            "data": [{"name": "A", "age": 30}, {"name": "B", "age": 20}],
            "operation": "filter",
            "condition": {"age": {"gt": 25}},
        })
        data = json.loads(result.content)
        assert data["matched"] == 1

    @pytest.mark.asyncio
    async def test_flatten(self, transformer):
        result = await transformer.execute({
            "data": {"a": {"b": {"c": 1}}, "d": 2},
            "operation": "flatten",
        })
        data = json.loads(result.content)
        assert data["a.b.c"] == 1
        assert data["d"] == 2

    @pytest.mark.asyncio
    async def test_aggregate(self, transformer):
        result = await transformer.execute({
            "data": [{"amount": 10}, {"amount": 20}, {"amount": 30}],
            "operation": "aggregate",
            "agg_field": "amount",
            "agg_func": "sum",
        })
        data = json.loads(result.content)
        assert data["result"] == 60

    @pytest.mark.asyncio
    async def test_diff(self, transformer):
        result = await transformer.execute({
            "data": {"a": 1, "b": 2},
            "operation": "diff",
            "second_data": {"a": 1, "b": 3, "c": 4},
        })
        data = json.loads(result.content)
        assert "c" in data["added"]
        assert "b" in data["changed"]

    @pytest.mark.asyncio
    async def test_schema(self, transformer):
        result = await transformer.execute({
            "data": {"name": "test", "count": 42, "items": [1, 2]},
            "operation": "schema",
        })
        data = json.loads(result.content)
        assert data["type"] == "object"


# ---------- TextAnalyzerTool ----------

class TestTextAnalyzerTool:
    @pytest.fixture
    def text_tool(self):
        return TextAnalyzerTool()

    @pytest.mark.asyncio
    async def test_statistics(self, text_tool):
        text = "This is a sample text. It has multiple sentences. Three in total."
        result = await text_tool.execute({"text": text, "operation": "statistics"})
        data = json.loads(result.content)
        assert data["sentence_count"] == 3
        assert data["word_count"] > 0

    @pytest.mark.asyncio
    async def test_keywords(self, text_tool):
        text = "Energy markets are growing. Renewable energy is important. Energy prices vary."
        result = await text_tool.execute({"text": text, "operation": "keywords"})
        data = json.loads(result.content)
        assert data["keywords"][0]["word"] == "energy"

    @pytest.mark.asyncio
    async def test_readability(self, text_tool):
        text = "The quick brown fox jumps over the lazy dog. Simple sentences are easy to read."
        result = await text_tool.execute({"text": text, "operation": "readability"})
        data = json.loads(result.content)
        assert "flesch_reading_ease" in data

    @pytest.mark.asyncio
    async def test_compare(self, text_tool):
        result = await text_tool.execute({
            "text": "The power purchase agreement covers wind energy.",
            "second_text": "The PPA document describes solar power generation.",
            "operation": "compare",
        })
        data = json.loads(result.content)
        assert "cosine_similarity" in data
        assert data["cosine_similarity"] >= 0

    @pytest.mark.asyncio
    async def test_entities(self, text_tool):
        text = "John Smith works at Microsoft Corp. Contact: john@example.com. Price: $500."
        result = await text_tool.execute({"text": text, "operation": "entities"})
        data = json.loads(result.content)
        assert len(data["money"]) >= 1

    @pytest.mark.asyncio
    async def test_sentiment_words(self, text_tool):
        text = "The opportunity for growth is excellent. Strong performance with significant profit."
        result = await text_tool.execute({"text": text, "operation": "sentiment_words"})
        data = json.loads(result.content)
        assert data["tone"] == "positive"

    @pytest.mark.asyncio
    async def test_empty_text(self, text_tool):
        result = await text_tool.execute({"text": "", "operation": "statistics"})
        assert result.is_error


# ---------- CodeExecutorTool ----------

class TestCodeExecutorTool:
    @pytest.fixture
    def executor(self):
        return CodeExecutorTool()

    @pytest.mark.asyncio
    async def test_basic_print(self, executor):
        result = await executor.execute({"code": "print('hello world')"})
        assert not result.is_error
        assert "hello world" in result.content

    @pytest.mark.asyncio
    async def test_math_computation(self, executor):
        result = await executor.execute({"code": "import math\nprint(math.sqrt(144))"})
        assert "12.0" in result.content

    @pytest.mark.asyncio
    async def test_statistics(self, executor):
        result = await executor.execute({
            "code": "import statistics\ndata = [10, 20, 30, 40, 50]\nprint(statistics.mean(data))",
        })
        assert "30" in result.content

    @pytest.mark.asyncio
    async def test_expression_result(self, executor):
        result = await executor.execute({"code": "2 + 3"})
        assert "5" in result.content

    @pytest.mark.asyncio
    async def test_variables_injection(self, executor):
        result = await executor.execute({
            "code": "print(x * 2)",
            "variables": {"x": 21},
        })
        assert "42" in result.content

    @pytest.mark.asyncio
    async def test_forbidden_import(self, executor):
        result = await executor.execute({"code": "import os"})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_forbidden_open(self, executor):
        result = await executor.execute({"code": "open('/etc/passwd')"})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_syntax_error(self, executor):
        result = await executor.execute({"code": "def f(:"})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_runtime_error(self, executor):
        result = await executor.execute({"code": "1 / 0"})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_list_comprehension(self, executor):
        result = await executor.execute({
            "code": "squares = [x**2 for x in range(5)]\nprint(squares)",
        })
        assert "[0, 1, 4, 9, 16]" in result.content


# ---------- DateCalculatorTool ----------

class TestDateCalculatorTool:
    @pytest.fixture
    def date_calc(self):
        return DateCalculatorTool()

    @pytest.mark.asyncio
    async def test_add_days(self, date_calc):
        result = await date_calc.execute({
            "operation": "add",
            "date": "2024-01-15",
            "days": 30,
        })
        data = json.loads(result.content)
        assert data["result_date"] == "2024-02-14"

    @pytest.mark.asyncio
    async def test_add_months(self, date_calc):
        result = await date_calc.execute({
            "operation": "add",
            "date": "2024-01-31",
            "months": 1,
        })
        data = json.loads(result.content)
        assert data["result_date"] == "2024-02-29"

    @pytest.mark.asyncio
    async def test_difference(self, date_calc):
        result = await date_calc.execute({
            "operation": "difference",
            "date": "2024-01-01",
            "second_date": "2024-12-31",
        })
        data = json.loads(result.content)
        assert data["total_days"] == 365

    @pytest.mark.asyncio
    async def test_business_days(self, date_calc):
        result = await date_calc.execute({
            "operation": "business_days",
            "date": "2024-01-15",
            "business_days": 5,
        })
        data = json.loads(result.content)
        assert data["result_date"] == "2024-01-22"

    @pytest.mark.asyncio
    async def test_contract_milestones(self, date_calc):
        result = await date_calc.execute({
            "operation": "contract_milestones",
            "contract_start": "2024-01-01",
            "contract_years": 10,
        })
        data = json.loads(result.content)
        assert data["contract_end"] == "2034-01-01"
        assert len(data["milestones"]) > 5

    @pytest.mark.asyncio
    async def test_format(self, date_calc):
        result = await date_calc.execute({
            "operation": "format",
            "date": "2024-07-04",
        })
        data = json.loads(result.content)
        assert data["day_of_week"] == "Thursday"
        assert data["quarter"] == 3


# ---------- RegexExtractorTool ----------

class TestRegexExtractorTool:
    @pytest.fixture
    def regex(self):
        return RegexExtractorTool()

    @pytest.mark.asyncio
    async def test_extract_emails(self, regex):
        result = await regex.execute({
            "text": "Contact alice@example.com or bob@test.org",
            "operation": "extract",
            "preset": "email",
        })
        data = json.loads(result.content)
        assert data["match_count"] == 2

    @pytest.mark.asyncio
    async def test_extract_ppa_prices(self, regex):
        result = await regex.execute({
            "text": "The price is $45.50/MWh with a floor of $40.00/MWh",
            "operation": "extract",
            "preset": "ppa_price",
        })
        data = json.loads(result.content)
        assert data["match_count"] == 2

    @pytest.mark.asyncio
    async def test_extract_preset_multiple(self, regex):
        result = await regex.execute({
            "text": "Email: test@example.com. Price: $100. Date: 2024-01-15.",
            "operation": "extract_preset",
            "presets": ["email", "currency_usd", "date_iso"],
        })
        data = json.loads(result.content)
        assert "email" in data["extracted"]

    @pytest.mark.asyncio
    async def test_replace(self, regex):
        result = await regex.execute({
            "text": "Hello World Hello",
            "operation": "replace",
            "pattern": "Hello",
            "replacement": "Hi",
        })
        data = json.loads(result.content)
        assert data["replacements_made"] == 2

    @pytest.mark.asyncio
    async def test_list_presets(self, regex):
        result = await regex.execute({
            "text": "dummy",
            "operation": "list_presets",
        })
        data = json.loads(result.content)
        assert "email" in data
        assert "ppa_price" in data

    @pytest.mark.asyncio
    async def test_custom_pattern(self, regex):
        result = await regex.execute({
            "text": "ID-001 ID-002 ID-003",
            "operation": "extract",
            "pattern": r"ID-\d{3}",
        })
        data = json.loads(result.content)
        assert data["match_count"] == 3


# ---------- UnitConverterTool ----------

class TestUnitConverterTool:
    @pytest.fixture
    def converter(self):
        return UnitConverterTool()

    @pytest.mark.asyncio
    async def test_energy_mwh_to_kwh(self, converter):
        result = await converter.execute({"value": 1, "from_unit": "MWh", "to_unit": "kWh"})
        data = json.loads(result.content)
        assert data["result"] == 1000

    @pytest.mark.asyncio
    async def test_energy_gwh_to_mwh(self, converter):
        result = await converter.execute({"value": 1, "from_unit": "GWh", "to_unit": "MWh"})
        data = json.loads(result.content)
        assert data["result"] == 1000

    @pytest.mark.asyncio
    async def test_temperature_c_to_f(self, converter):
        result = await converter.execute({"value": 100, "from_unit": "C", "to_unit": "F"})
        data = json.loads(result.content)
        assert data["result"] == 212

    @pytest.mark.asyncio
    async def test_temperature_f_to_c(self, converter):
        result = await converter.execute({"value": 32, "from_unit": "F", "to_unit": "C"})
        data = json.loads(result.content)
        assert abs(data["result"]) < 0.01

    @pytest.mark.asyncio
    async def test_mass_kg_to_lb(self, converter):
        result = await converter.execute({"value": 1, "from_unit": "kg", "to_unit": "lb"})
        data = json.loads(result.content)
        assert abs(data["result"] - 2.20462) < 0.01

    @pytest.mark.asyncio
    async def test_power_mw_to_kw(self, converter):
        result = await converter.execute({"value": 1, "from_unit": "MW", "to_unit": "kW"})
        data = json.loads(result.content)
        assert data["result"] == 1000

    @pytest.mark.asyncio
    async def test_unknown_units(self, converter):
        result = await converter.execute({"value": 1, "from_unit": "xyz", "to_unit": "abc"})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_all_conversions_included(self, converter):
        result = await converter.execute({"value": 1, "from_unit": "MWh", "to_unit": "kWh"})
        data = json.loads(result.content)
        assert "all_conversions" in data


# ---------- MarketDataTool ----------

class TestMarketDataTool:
    @pytest.fixture
    def market(self):
        return MarketDataTool()

    @pytest.mark.asyncio
    async def test_stock_quote_mock(self, market):
        result = await market.execute({"data_type": "stock_quote", "symbol": "AAPL"})
        data = json.loads(result.content)
        assert "price" in data
        assert data["mode"] == "mock"

    @pytest.mark.asyncio
    async def test_forex_mock(self, market):
        result = await market.execute({"data_type": "forex", "symbol": "EUR/USD"})
        data = json.loads(result.content)
        assert "exchange_rate" in data

    @pytest.mark.asyncio
    async def test_commodity_mock(self, market):
        result = await market.execute({"data_type": "commodity", "symbol": "WTI"})
        data = json.loads(result.content)
        assert len(data["data"]) > 0

    @pytest.mark.asyncio
    async def test_energy_price_mock(self, market):
        result = await market.execute({"data_type": "energy_price"})
        data = json.loads(result.content)
        assert len(data["data"]) > 0

    @pytest.mark.asyncio
    async def test_economic_indicator_mock(self, market):
        result = await market.execute({"data_type": "economic_indicator", "symbol": "GDP"})
        data = json.loads(result.content)
        assert data["indicator"] == "GDP"


# ---------- DataExporterTool ----------

class TestDataExporterTool:
    @pytest.fixture
    def exporter(self):
        return DataExporterTool()

    @pytest.mark.asyncio
    async def test_export_json_file(self, exporter):
        result = await exporter.execute({
            "destination": "file",
            "data": {"key": "value", "count": 42},
            "format": "json",
            "filename": "test_export.json",
        })
        data = json.loads(result.content)
        assert data["status"] == "success"
        assert data["format"] == "json"
        if os.path.exists(data["file_path"]):
            os.unlink(data["file_path"])

    @pytest.mark.asyncio
    async def test_export_csv_file(self, exporter):
        result = await exporter.execute({
            "destination": "file",
            "data": [{"name": "A", "value": 1}, {"name": "B", "value": 2}],
            "format": "csv",
        })
        data = json.loads(result.content)
        assert data["status"] == "success"
        if os.path.exists(data["file_path"]):
            os.unlink(data["file_path"])

    @pytest.mark.asyncio
    async def test_export_email_mock(self, exporter):
        result = await exporter.execute({
            "destination": "email",
            "data": {"report": "test"},
            "email_to": "test@example.com",
            "email_subject": "Test Report",
        })
        data = json.loads(result.content)
        assert data["status"] == "mock"

    @pytest.mark.asyncio
    async def test_export_s3_mock(self, exporter):
        result = await exporter.execute({
            "destination": "s3",
            "data": {"key": "value"},
            "s3_bucket": "my-bucket",
            "s3_key": "exports/test.json",
        })
        data = json.loads(result.content)
        assert data["status"] == "mock"


# ---------- SpreadsheetAnalyzerTool ----------

class TestSpreadsheetAnalyzerTool:
    @pytest.fixture
    def analyzer(self):
        return SpreadsheetAnalyzerTool()

    @pytest.mark.asyncio
    async def test_csv_overview(self, analyzer):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write("name,price,quantity\nA,10,100\nB,20,200")
            f.flush()
            result = await analyzer.execute({"file_path": f.name, "operation": "overview"})
        os.unlink(f.name)
        data = json.loads(result.content)
        assert data["total_rows"] == 2

    @pytest.mark.asyncio
    async def test_csv_statistics(self, analyzer):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write("value\n10\n20\n30\n40\n50")
            f.flush()
            result = await analyzer.execute({"file_path": f.name, "operation": "statistics"})
        os.unlink(f.name)
        data = json.loads(result.content)
        assert data["statistics"]["value"]["mean"] == 30.0

    @pytest.mark.asyncio
    async def test_csv_search(self, analyzer):
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write("name,status\nAlice,active\nBob,inactive")
            f.flush()
            result = await analyzer.execute({"file_path": f.name, "operation": "search", "search_term": "active"})
        os.unlink(f.name)
        data = json.loads(result.content)
        assert data["match_count"] >= 1

    @pytest.mark.asyncio
    async def test_file_not_found(self, analyzer):
        result = await analyzer.execute({"file_path": "/nonexistent/file.csv"})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_unsupported_format(self, analyzer):
        with tempfile.NamedTemporaryFile(suffix=".xyz", mode="w", delete=False) as f:
            f.write("data")
            f.flush()
            result = await analyzer.execute({"file_path": f.name})
        os.unlink(f.name)
        assert result.is_error


# ---------- ApiConnectorTool ----------

class TestApiConnectorTool:
    @pytest.fixture
    def connector(self):
        return ApiConnectorTool()

    @pytest.mark.asyncio
    async def test_slack_mock(self, connector):
        result = await connector.execute({
            "service": "slack",
            "params": {"message": "Hello from test", "channel": "#test"},
        })
        data = json.loads(result.content)
        assert data["status"] == "mock"

    @pytest.mark.asyncio
    async def test_airtable_read_mock(self, connector):
        result = await connector.execute({
            "service": "airtable_read",
            "params": {"base_id": "appXXXX", "table_name": "Tasks"},
        })
        data = json.loads(result.content)
        assert data["status"] == "mock"

    @pytest.mark.asyncio
    async def test_jira_create_mock(self, connector):
        result = await connector.execute({
            "service": "jira_create",
            "params": {"project": "PROJ", "summary": "Test Issue"},
        })
        data = json.loads(result.content)
        assert data["status"] == "mock"

    @pytest.mark.asyncio
    async def test_unknown_service(self, connector):
        result = await connector.execute({
            "service": "nonexistent",
            "params": {},
        })
        assert result.is_error


# ---------- Tool Registry Integration ----------

class TestToolRegistryIntegration:
    def test_all_new_tools_register(self):
        from engine.agent_executor import build_tool_registry
        all_tool_names = [
            "calculator", "current_time", "file_reader", "web_search",
            "document_extractor", "csv_analyzer", "financial_calculator",
            "risk_analyzer", "market_data", "json_transformer",
            "text_analyzer", "http_client", "code_executor",
            "date_calculator", "regex_extractor", "unit_converter",
            "spreadsheet_analyzer", "presentation_analyzer",
            "data_exporter", "api_connector",
        ]
        registry = build_tool_registry(all_tool_names)
        registered = registry.names()
        for name in all_tool_names:
            assert name in registered, f"Tool '{name}' not registered"

    def test_all_tools_have_schema(self):
        from engine.agent_executor import build_tool_registry
        all_tool_names = [
            "document_extractor", "csv_analyzer", "financial_calculator",
            "risk_analyzer", "market_data", "json_transformer",
            "text_analyzer", "http_client", "code_executor",
            "date_calculator", "regex_extractor", "unit_converter",
            "spreadsheet_analyzer", "presentation_analyzer",
            "data_exporter", "api_connector",
        ]
        registry = build_tool_registry(all_tool_names)
        for tool_dict in registry.list_all():
            assert "name" in tool_dict
            assert "description" in tool_dict
            assert "input_schema" in tool_dict
            assert len(tool_dict["description"]) > 20


# ---------- NodeTrace Integration ----------

class TestNodeTrace:
    def test_node_trace_serialization(self):
        from engine.agent_executor import NodeTrace
        trace = NodeTrace(
            node_id="node_0",
            node_type="tool_call",
            iteration=0,
            timestamp_ms=1000,
            duration_ms=50,
            input_data={"tool": "calculator", "arguments": {"expression": "2+2"}},
            output_data={"content_preview": "4", "is_error": False},
        )
        d = trace.to_dict()
        assert d["node_id"] == "node_0"
        assert d["node_type"] == "tool_call"
        assert d["input"]["tool"] == "calculator"

    def test_execution_result_traces(self):
        from engine.agent_executor import ExecutionResult, NodeTrace
        traces = [
            NodeTrace(node_id="n0", node_type="user_input", iteration=0, timestamp_ms=1000),
            NodeTrace(node_id="n1", node_type="llm_call", iteration=0, timestamp_ms=1100),
            NodeTrace(node_id="n2", node_type="tool_call", iteration=0, timestamp_ms=1200),
        ]
        result = ExecutionResult(output="test", node_traces=traces)
        summary = result.get_trace_summary()
        assert len(summary) == 3
        assert summary[0]["node_type"] == "user_input"
        assert summary[2]["node_type"] == "tool_call"
