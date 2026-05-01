from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    agent_id: str | None = None
    title: str = "New Chat"
    model_used: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    is_archived: bool | None = None


class SaveMessageRequest(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = ""
    blocks: list | None = None
    tool_calls: list | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0
    model_used: str | None = None
    duration_ms: int | None = None
    attachments: list | None = None
