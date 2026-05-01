"""Tests for MemPalace memory system."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_aaak_system_prompt_exists():
    """AAAK compressor has the compression prompt."""
    from engine.memory.aaak_compressor import AAAK_SYSTEM_PROMPT
    assert "entity codes" in AAAK_SYSTEM_PROMPT
    assert "P=person" in AAAK_SYSTEM_PROMPT


def test_memory_palace_models_import():
    """MemPalace models can be imported."""
    from models.memory_palace import MemoryWing, MemoryHall, MemoryRoom, MemoryDrawer
    from models.memory_palace import MemoryEntity, MemoryRelation, HallType
    assert HallType.FACTUAL.value == "factual"
    assert HallType.EPISODIC.value == "episodic"


def test_palace_class_init():
    """MemoryPalace can be instantiated."""
    import uuid
    from engine.memory.palace import MemoryPalace
    palace = MemoryPalace(db=MagicMock(), agent_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    assert palace is not None
