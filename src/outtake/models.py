"""Versioned public data. Plans are values; changing one creates a new revision."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class OuttakeError(Exception):
    def __init__(self, code: str, message: str, remedy: str, identity: str | None = None):
        super().__init__(message)
        self.code, self.remedy, self.identity = code, remedy, identity

    def result(self):
        return {
            "schema_version": 1,
            "status": "cancelled" if self.code == "CANCELLED" else "failed",
            "error": {
                "code": self.code,
                "message": str(self),
                "remediation": self.remedy,
                "identity": self.identity,
            },
        }


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Limits(Value):
    timeout_seconds: float = Field(default=120, gt=0, le=3600)
    max_output_bytes: int = Field(default=256 * 1024**2, gt=0)
    max_temporary_bytes: int = Field(default=512 * 1024**2, gt=0)
    max_duration_seconds: float = Field(default=120, gt=0, le=3600)


class Settings(Value):
    source_roots: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    output_root: str = Field(min_length=1)
    state_root: str | None = Field(default=None, min_length=1)
    limits: Limits = Field(default_factory=Limits)


class Overlay(Value):
    text: str = Field(max_length=2000)
    size: int = Field(default=32, ge=8, le=256)
    color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    outline_color: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    outline_width: int = Field(default=2, ge=0, le=12)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.85, ge=0, le=1)
    alignment: Literal["left", "center", "right"] = "center"
    font: str = Field(default="pillow-default", min_length=1, max_length=100)


class TextCue(Overlay):
    id: str = Field(pattern=r"^cue_[a-zA-Z0-9_-]{1,80}$")
    start: Seconds
    end: Seconds
    enabled: bool = True
    origin: Literal["manual", "caption"] = "manual"
    evidence_id: str | None = None
    extraction: Literal["source_text", "ocr"] = "source_text"
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_required: bool = False

    @model_validator(mode="after")
    def ordered(self):
        if self.start >= self.end:
            raise ValueError("Cue end must follow start.")
        if self.origin == "caption" and not self.evidence_id:
            raise ValueError("Caption cues require retained caption evidence.")
        return self


class Source(Value):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(gt=0)
    duration: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    has_audio: bool
    color_transfer: str
    sample_aspect_ratio: str = "1:1"


class Plan(Value):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^plan_[a-f0-9]{32}$")
    parent_id: str | None = None
    revision: int = Field(default=1, ge=1)
    source: Source
    start: Seconds
    end: Seconds
    frame: Seconds
    format: Literal["mp4", "gif", "png"] = "mp4"
    profile: Literal["mobile", "share", "editing"] = "share"
    audio: Literal["preserve", "mute"] = "preserve"
    overlay: Overlay | None = None
    title: str = Field(default="", max_length=120)
    cues: tuple[TextCue, ...] = Field(default=(), max_length=100)
    captions_enabled: bool = True
    caption_status: str = "not_imported"
    caption_mode: Literal["editable", "original"] = "editable"
    caption_evidence_id: str | None = None
    warnings: tuple[str, ...] = ()
    max_width: int | None = Field(default=None, ge=160, le=3840)
    fps: int | None = Field(default=None, ge=1, le=60)
    provenance: Literal["caller_range", "model_proposal"] = "caller_range"
    evidence_ids: tuple[str, ...] = ()
    finding_id: str | None = None
    candidate_id: str | None = None
    sound_verification: Literal["user_review_required"] = "user_review_required"
    time_basis: Literal["seconds_from_video_start"] = "seconds_from_video_start"

    @model_validator(mode="after")
    def valid_range(self):
        if not self.start < self.end <= self.source.duration + 0.000001:
            raise ValueError("Require 0 <= start < end <= source duration.")
        if not self.start <= self.frame < self.end:
            raise ValueError("Still frame must be within [start, end).")
        if self.format != "mp4" and self.audio != "mute":
            raise ValueError("GIF and PNG require audio=mute.")
        if len({cue.id for cue in self.cues}) != len(self.cues):
            raise ValueError("Cue identities must be unique.")
        if any(cue.end > self.source.duration for cue in self.cues):
            raise ValueError("Cue timing must be within the source.")
        return self


class FindRequest(Value):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    context: str = Field(default="", max_length=8000)
    source_ids: tuple[str, ...] = Field(default=(), max_length=20)
    scope: str | None = None
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")


class ModelGrant(Value):
    provider: Literal["openai", "anthropic", "gemini"]
    model: str = Field(min_length=1, max_length=200)
    allow_request: bool = False
    allow_metadata: bool = False
    allow_captions: bool = False
    allow_frames: bool = False
    vision: bool = False
    max_model_calls: int = Field(default=8, ge=1, le=40)
    max_tool_calls: int = Field(default=24, ge=1, le=200)
    max_frames: int = Field(default=24, ge=0, le=200)
    max_text_bytes: int = Field(default=250_000, ge=1, le=10_000_000)
    max_image_bytes: int = Field(default=8_000_000, ge=1, le=50_000_000)
    max_response_tokens: int = Field(default=2048, ge=128, le=8192)


class CandidateInput(Value):
    title: str = Field(default="", max_length=80)
    source_id: str
    start: Seconds
    end: Seconds
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    explanation: str = Field(min_length=1, max_length=2000)
    uncertainty: str = Field(min_length=1, max_length=2000)
