"""code_executor hands a computed value to the next pipeline step as plain JSON."""

from __future__ import annotations

import asyncio
import json

from engine.tools.code_executor import CodeExecutorTool


def _run(code: str):
    return asyncio.run(CodeExecutorTool().execute({"code": code}))


def test_result_variable_is_the_output_when_nothing_is_printed():
    r = _run(
        "prices = [1.0, 2.0, 3.0]\nresult = {'count': len(prices), 'avg': sum(prices) / len(prices)}"
    )
    assert not r.is_error
    assert json.loads(r.content) == {"count": 3, "avg": 2.0}


def test_last_expression_alone_is_plain_json():
    r = _run("x = 2\n{'double': x * 2}")
    assert json.loads(r.content) == {"double": 4}


def test_printed_output_keeps_the_result_label():
    r = _run("print('hello')\nresult = 5")
    assert r.content.startswith("hello")
    assert "Result: 5" in r.content


def test_a_result_passed_in_as_a_variable_is_not_echoed_back():
    r = asyncio.run(
        CodeExecutorTool().execute({"code": "y = 1", "variables": {"result": "old"}})
    )
    assert r.content == "(no output)"
