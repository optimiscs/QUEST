from pydantic import BaseModel, ConfigDict, JsonValue


class TaskSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    revision: str
    index: int | None = None
    topicZh: str = ""
    durationSeconds: float | None = None
    stats: dict[str, JsonValue] = {}
    correct: bool | None = None
    inProgress: bool = False


class RunInfo(BaseModel):
    id: str
    revision: str
    metadata: dict[str, JsonValue]
    run: dict[str, JsonValue]
    counts: dict[str, int]


class TaskPage(BaseModel):
    runRevision: str
    items: list[TaskSummary]
    nextCursor: int | None


class TraceDocument(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    steps: list[dict[str, JsonValue]]


class Manifest(BaseModel):
    datasets: list[dict[str, JsonValue]]


class WorkspaceStatus(BaseModel):
    datasets: dict[str, dict[str, int]]
