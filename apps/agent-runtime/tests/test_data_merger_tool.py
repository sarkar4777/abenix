"""Tests for the data merger pipeline tool."""

from __future__ import annotations

import json

import pytest

from engine.tools.data_merger import DataMergerTool


@pytest.fixture
def tool() -> DataMergerTool:
    return DataMergerTool()


class TestDataMergerTool:
    @pytest.mark.asyncio
    async def test_flat_merge(self, tool: DataMergerTool) -> None:
        """Flat strategy merges dict values into a single top-level dict."""
        result = await tool.execute(
            {
                "merge_strategy": "flat",
                "input_a": {"x": 1},
                "input_b": {"y": 2},
            }
        )

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert parsed["x"] == 1
        assert parsed["y"] == 2

    @pytest.mark.asyncio
    async def test_nested_merge(self, tool: DataMergerTool) -> None:
        """Nested strategy preserves each input under its original key."""
        result = await tool.execute(
            {
                "merge_strategy": "nested",
                "input_a": {"x": 1},
                "input_b": {"y": 2},
            }
        )

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert "input_a" in parsed
        assert "input_b" in parsed
        assert parsed["input_a"]["x"] == 1
        assert parsed["input_b"]["y"] == 2

    @pytest.mark.asyncio
    async def test_comparison_merge(self, tool: DataMergerTool) -> None:
        """Comparison strategy creates a labeled items array."""
        result = await tool.execute(
            {
                "merge_strategy": "comparison",
                "labels": {"input_a": "Source A", "input_b": "Source B"},
                "input_a": "data1",
                "input_b": "data2",
            }
        )

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert "items" in parsed
        assert len(parsed["items"]) == 2

        labels = [item["label"] for item in parsed["items"]]
        assert "Source A" in labels
        assert "Source B" in labels

        data_values = [item["data"] for item in parsed["items"]]
        assert "data1" in data_values
        assert "data2" in data_values

    @pytest.mark.asyncio
    async def test_single_input_passthrough(self, tool: DataMergerTool) -> None:
        """A single input is preserved in the output."""
        result = await tool.execute(
            {
                "merge_strategy": "nested",
                "input_a": "hello",
            }
        )

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert parsed["input_a"] == "hello"

    @pytest.mark.asyncio
    async def test_empty_inputs(self, tool: DataMergerTool) -> None:
        """With only a merge strategy and no data inputs, output is valid."""
        result = await tool.execute({"merge_strategy": "flat"})

        assert result.is_error is False
        parsed = json.loads(result.content)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_labels_applied(self, tool: DataMergerTool) -> None:
        """Custom labels appear in the comparison output items."""
        result = await tool.execute(
            {
                "merge_strategy": "comparison",
                "labels": {"input_a": "First Result", "input_b": "Second Result"},
                "input_a": 100,
                "input_b": 200,
            }
        )

        assert result.is_error is False
        parsed = json.loads(result.content)
        items = parsed["items"]
        label_map = {item["key"]: item["label"] for item in items}
        assert label_map["input_a"] == "First Result"
        assert label_map["input_b"] == "Second Result"

    @pytest.mark.asyncio
    async def test_complex_nested_data(self, tool: DataMergerTool) -> None:
        """Nested dicts and arrays are preserved through the merge."""
        complex_a = {
            "users": [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
            ],
            "metadata": {"source": "db"},
        }
        complex_b = {
            "scores": [95, 87, 73],
            "config": {"normalize": True, "weights": [0.5, 0.3, 0.2]},
        }

        result = await tool.execute(
            {
                "merge_strategy": "nested",
                "input_a": complex_a,
                "input_b": complex_b,
            }
        )

        assert result.is_error is False
        parsed = json.loads(result.content)

        # Verify nested structures are intact
        assert parsed["input_a"]["users"][0]["name"] == "Alice"
        assert parsed["input_a"]["users"][1]["age"] == 25
        assert parsed["input_a"]["metadata"]["source"] == "db"
        assert parsed["input_b"]["scores"] == [95, 87, 73]
        assert parsed["input_b"]["config"]["normalize"] is True
        assert parsed["input_b"]["config"]["weights"] == [0.5, 0.3, 0.2]
