from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ExtractedBlock:
    text: str
    block_type: str = "paragraph"
    page: int | None = None
    paragraph_idx: int | None = None
    char_offset_start: int | None = None
    char_offset_end: int | None = None
    table: list[list[str]] | None = None
    figure_caption: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Extractor(Protocol):
    method: str

    async def extract(
        self, *, blob_path: str, content_type: str | None = None
    ) -> list[ExtractedBlock]: ...
