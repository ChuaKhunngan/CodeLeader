from __future__ import annotations

from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    # v0 single-session: must be the fixed id "CodeLeader".
    session_id: str = Field("CodeLeader", min_length=1, max_length=128)


class SendPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8192)


class ApproveRequest(BaseModel):
    decision: str = Field(..., pattern="^(yes|always|no)$")
    approval_id: str | None = Field(default=None, max_length=256)


class WebhookStateChange(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    event_type: str = Field(..., min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=512)
    input_kind: str | None = Field(default=None, max_length=128)
    raw_context: str | None = Field(default=None, max_length=4096)
    fingerprint: str | None = Field(default=None, max_length=256)
    observed_at: str | None = Field(default=None, max_length=128)


class TailLinesRequest(BaseModel):
    session_id: str = Field("CodeLeader", min_length=1, max_length=128)
    lines: int = Field(..., ge=1, le=2000)


class StateResponse(BaseModel):
    session_id: str
    state: str
    blocked_reason: str | None = None
    control_state: str | None = None
    automation_blocked: bool = False
    human_reason: str | None = None


class RemoteBootstrapChecks(BaseModel):
    python3_ok: bool
    venv_ok: bool
    zellij_ok: bool
    zellij_session_ok: bool | None = None


class RemoteBootstrapRequest(BaseModel):
    action: str = Field(..., pattern="^(check|status|apply|start|stop)$")
    remote_host: str | None = Field(default=None, max_length=256)
    zellij_session: str | None = Field(default=None, max_length=128)
    webhook_url: str | None = Field(default=None, max_length=2048)


class RemoteBootstrapWatcher(BaseModel):
    running: bool
    pid: int | None = None
    cmd: str | None = None
    python: str | None = None
    err_tail: list[str] | None = None


class RemoteBootstrapResponse(BaseModel):
    ok: bool
    action: str
    rc: int
    stdout: str = ""
    stderr: str = ""
    remote_host: str | None = None
    zellij_session: str | None = None
    webhook_url: str | None = None
    running: bool | None = None
    pid: int | None = None
    checks: RemoteBootstrapChecks | None = None
    watcher: RemoteBootstrapWatcher | None = None
