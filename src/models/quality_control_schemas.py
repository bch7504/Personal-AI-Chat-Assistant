from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScopedQualityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=128)
    release_id: str = Field(min_length=1, max_length=128)


class QualityRequirementCreate(ScopedQualityCreate):
    requirement_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    required: bool = True


class QualityTestCaseCreate(ScopedQualityCreate):
    test_case_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    requirement_id: str | None = None
    test_kind: Literal["functional", "regression", "security", "performance", "compliance"]
    required: bool = False


class QualityEvidenceCreate(ScopedQualityCreate):
    artifact_type: Literal["url", "report", "log", "screenshot", "other"]
    uri: str = Field(min_length=1, max_length=2_000)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityTestRunCreate(ScopedQualityCreate):
    test_case_id: str
    release_candidate_id: str | None = None
    evidence_id: str | None = None
    build_number: str = Field(min_length=1, max_length=64)
    environment: Literal["development", "staging", "production"]
    status: Literal["queued", "running", "passed", "failed", "blocked"] = "queued"


class QualityDefectCreate(ScopedQualityCreate):
    defect_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    severity: Literal["low", "medium", "high", "critical"]
    test_run_id: str | None = None
    requirement_id: str | None = None
    evidence_id: str | None = None
    owner_id: str | None = None


class QualityPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=64)
    block_severities: list[Literal["low", "medium", "high", "critical"]] = Field(
        default_factory=lambda: ["critical", "high"]
    )
    required_test_kinds: list[
        Literal["functional", "regression", "security", "performance", "compliance"]
    ] = Field(default_factory=lambda: ["functional", "security"])
    require_verified_evidence: bool = True
    allow_waivers: bool = True
    activate: bool = False


class QualityWaiverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: str = Field(min_length=1, max_length=128)
    target_type: Literal["defect", "test_run", "requirement"]
    target_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=10, max_length=2_000)
    expires_at: datetime

    @model_validator(mode="after")
    def expiry_has_timezone(self) -> QualityWaiverCreate:
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return self


class QualityRecordTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    expected_row_version: int = Field(ge=1)


class QualityControlRecordOut(BaseModel):
    record_type: str
    record: dict[str, Any]


class QualityControlPlaneOut(BaseModel):
    release_id: str
    policy: dict[str, Any]
    assessment: dict[str, Any]
    traceability: dict[str, Any]
    requirements: list[dict[str, Any]]
    test_cases: list[dict[str, Any]]
    test_runs: list[dict[str, Any]]
    defects: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    waivers: list[dict[str, Any]]
