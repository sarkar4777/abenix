from engine.pipeline import alias_labels_to_ids, parse_pipeline_nodes


def _nodes():
    return [
        {
            "id": "step_a",
            "label": "score",
            "tool_name": "llm_call",
            "arguments": {"prompt": "x"},
        },
        {
            "id": "step_b",
            "label": "Exposure Check",
            "tool_name": "llm_call",
            "arguments": {"prompt": "S: {{score.response}}"},
        },
        {
            "id": "step_c",
            "label": "briefing",
            "tool_name": "llm_call",
            "arguments": {
                "prompt": "{{score.response}} {{exposure_check.response}} {{nope.x}}"
            },
        },
    ]


def test_label_refs_become_ids():
    out = alias_labels_to_ids(_nodes())
    assert out[1]["arguments"]["prompt"] == "S: {{step_a.response}}"
    assert (
        out[2]["arguments"]["prompt"]
        == "{{step_a.response}} {{step_b.response}} {{nope.x}}"
    )


def test_label_refs_infer_dependencies():
    deps = {n.id: sorted(n.depends_on) for n in parse_pipeline_nodes(_nodes())}
    assert deps == {"step_a": [], "step_b": ["step_a"], "step_c": ["step_a", "step_b"]}


def test_id_wins_and_duplicate_labels_are_ignored():
    nodes = [
        {"id": "score", "label": "first", "tool_name": "llm_call", "arguments": {}},
        {"id": "step_x", "label": "score", "tool_name": "llm_call", "arguments": {}},
        {"id": "step_y", "label": "dup", "tool_name": "llm_call", "arguments": {}},
        {
            "id": "step_z",
            "label": "dup",
            "tool_name": "llm_call",
            "arguments": {"p": "{{score.response}} {{dup.response}}"},
        },
    ]
    out = alias_labels_to_ids(nodes)
    assert out[3]["arguments"]["p"] == "{{score.response}} {{dup.response}}"


def test_labels_reach_the_result():
    nodes = parse_pipeline_nodes(_nodes())
    assert nodes[0].label == "score"
