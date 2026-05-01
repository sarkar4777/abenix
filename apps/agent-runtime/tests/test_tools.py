from __future__ import annotations

import json
import os
import tempfile

import pytest

from engine.tools.base import ToolRegistry
from engine.tools.calculator import CalculatorTool
from engine.tools.current_time import CurrentTimeTool
from engine.tools.file_reader import FileReaderTool


class TestCalculatorTool:
    @pytest.fixture
    def calc(self):
        return CalculatorTool()

    @pytest.mark.asyncio
    async def test_basic_addition(self, calc):
        result = await calc.execute({"expression": "2 + 3"})
        assert result.content == "5"
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_multiplication(self, calc):
        result = await calc.execute({"expression": "(4 + 5) * 3"})
        assert result.content == "27"

    @pytest.mark.asyncio
    async def test_division(self, calc):
        result = await calc.execute({"expression": "10 / 3"})
        assert float(result.content) == pytest.approx(3.333, rel=1e-2)

    @pytest.mark.asyncio
    async def test_power(self, calc):
        result = await calc.execute({"expression": "2 ** 10"})
        assert result.content == "1024"

    @pytest.mark.asyncio
    async def test_sqrt(self, calc):
        result = await calc.execute({"expression": "sqrt(144)"})
        assert float(result.content) == 12.0

    @pytest.mark.asyncio
    async def test_pi(self, calc):
        result = await calc.execute({"expression": "pi"})
        assert float(result.content) == pytest.approx(3.14159, rel=1e-4)

    @pytest.mark.asyncio
    async def test_abs(self, calc):
        result = await calc.execute({"expression": "abs(-42)"})
        assert result.content == "42"

    @pytest.mark.asyncio
    async def test_nested_functions(self, calc):
        result = await calc.execute({"expression": "round(sqrt(2), 2)"})
        assert result.content == "1.41"

    @pytest.mark.asyncio
    async def test_invalid_expression(self, calc):
        result = await calc.execute({"expression": "2 ++"})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_missing_expression(self, calc):
        result = await calc.execute({})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_division_by_zero(self, calc):
        result = await calc.execute({"expression": "1 / 0"})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_metadata_present(self, calc):
        result = await calc.execute({"expression": "5 + 5"})
        assert "expression" in result.metadata
        assert "result" in result.metadata

    def test_to_dict(self, calc):
        d = calc.to_dict()
        assert d["name"] == "calculator"
        assert "description" in d
        assert "input_schema" in d


class TestCurrentTimeTool:
    @pytest.fixture
    def time_tool(self):
        return CurrentTimeTool()

    @pytest.mark.asyncio
    async def test_utc(self, time_tool):
        result = await time_tool.execute({"timezone": "UTC"})
        assert result.is_error is False
        assert "UTC" in result.content

    @pytest.mark.asyncio
    async def test_default_utc(self, time_tool):
        result = await time_tool.execute({})
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_est(self, time_tool):
        result = await time_tool.execute({"timezone": "EST"})
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_iana_timezone(self, time_tool):
        result = await time_tool.execute({"timezone": "America/New_York"})
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_invalid_timezone(self, time_tool):
        result = await time_tool.execute({"timezone": "Invalid/Zone"})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_metadata_iso(self, time_tool):
        result = await time_tool.execute({"timezone": "UTC"})
        assert "iso" in result.metadata


class TestFileReaderTool:
    @pytest.fixture
    def reader(self):
        return FileReaderTool()

    @pytest.mark.asyncio
    async def test_read_txt_file(self, reader):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Hello, world!")
            f.flush()
            result = await reader.execute({"file_path": f.name})
        os.unlink(f.name)
        assert result.is_error is False
        assert "Hello, world!" in result.content

    @pytest.mark.asyncio
    async def test_read_json_file(self, reader):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"key": "value"}, f)
            f.flush()
            result = await reader.execute({"file_path": f.name})
        os.unlink(f.name)
        assert result.is_error is False
        assert "key" in result.content

    @pytest.mark.asyncio
    async def test_read_md_file(self, reader):
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Title\n\nContent here.")
            f.flush()
            result = await reader.execute({"file_path": f.name})
        os.unlink(f.name)
        assert result.is_error is False
        assert "Title" in result.content

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, reader):
        with tempfile.NamedTemporaryFile(suffix=".exe", mode="w", delete=False) as f:
            f.write("binary stuff")
            f.flush()
            result = await reader.execute({"file_path": f.name})
        os.unlink(f.name)
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_file_not_found(self, reader):
        result = await reader.execute({"file_path": "/nonexistent/file.txt"})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_missing_file_path(self, reader):
        result = await reader.execute({})
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_metadata_present(self, reader):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("test")
            f.flush()
            result = await reader.execute({"file_path": f.name})
        os.unlink(f.name)
        assert "extension" in result.metadata
        assert "size_bytes" in result.metadata


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        calc = CalculatorTool()
        registry.register(calc)
        assert registry.get("calculator") is calc

    def test_get_unknown(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_names(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        registry.register(CurrentTimeTool())
        names = registry.names()
        assert "calculator" in names
        assert "current_time" in names

    def test_list_all(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        tools = registry.list_all()
        assert len(tools) == 1
        assert tools[0]["name"] == "calculator"
        assert "description" in tools[0]
        assert "input_schema" in tools[0]
