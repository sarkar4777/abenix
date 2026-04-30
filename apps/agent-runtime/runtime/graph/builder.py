"""LangGraph graph builder for agent execution."""

from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

from runtime.agents.base import AgentConfig


class AgentState(TypedDict):
    """State tracked through the agent execution graph."""

    messages: list[dict[str, Any]]
    current_step: str
    iteration_count: int
    final_output: str | None


def build_agent_graph(config: AgentConfig) -> StateGraph:
    """Build a LangGraph state graph from an agent configuration."""
    graph = StateGraph(AgentState)

    async def process_message(state: AgentState) -> AgentState:
        state["iteration_count"] += 1
        return state

    async def should_continue(state: AgentState) -> str:
        if state["iteration_count"] >= config.max_iterations:
            return "end"
        if state.get("final_output") is not None:
            return "end"
        return "continue"

    graph.add_node("process", process_message)
    graph.add_conditional_edges(
        "process",
        should_continue,
        {"continue": "process", "end": END},
    )
    graph.set_entry_point("process")

    return graph
