"""The live DAG of a queue-routed pipeline follows its node events."""

from __future__ import annotations

from app.core.execution_state import node_statuses_from_events


def test_events_replay_into_node_statuses():
    events = [
        {"event": "start"},
        {"event": "node_start", "node_id": "feed"},
        {"event": "node_complete", "node_id": "feed", "status": "completed"},
        {"event": "node_start", "node_id": "edge_rust"},
        {"event": "node_start", "node_id": "edge_c"},
        {"event": "node_complete", "node_id": "edge_c", "status": "failed"},
    ]
    assert node_statuses_from_events(events) == {
        "feed": "completed",
        "edge_rust": "running",
        "edge_c": "failed",
    }


def test_a_late_start_event_does_not_undo_a_completion():
    events = [
        {"event": "node_complete", "node_id": "a", "status": "completed"},
        {"event": "node_start", "node_id": "a"},
    ]
    assert node_statuses_from_events(events) == {"a": "completed"}


def test_for_each_items_report_on_their_node():
    events = [
        {"event": "node_start", "node_id": "publish[0]"},
        {"event": "node_complete", "node_id": "publish[0]", "status": "completed"},
        {"event": "node_start", "node_id": "publish[1]"},
        {"event": "node_complete", "node_id": "publish[1]", "status": "completed"},
    ]
    assert node_statuses_from_events(events) == {"publish": "completed"}
