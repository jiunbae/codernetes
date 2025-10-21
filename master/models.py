"""Codernetes 마스터 도메인 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """작업 상태."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class RepositorySpec:
    """작업에 포함된 GitHub 레포지토리 명세."""

    url: str
    branch: str | None = None
    subdirectory: str | None = None  # Repo 내에서 작업할 경로


@dataclass(slots=True)
class Job:
    """Codernetes 작업 기본 모델."""

    job_id: str
    prompt: str
    created_at: datetime
    status: JobStatus = JobStatus.PENDING
    target_node_id: str | None = None
    requested_tags: list[str] = field(default_factory=list)
    repositories: list[RepositorySpec] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    log_path: str | None = None
    result_summary: str | None = None
    error_message: str | None = None
    finished_at: datetime | None = None


@dataclass(slots=True)
class NodeMetadata:
    """노드 정보."""

    node_id: str
    display_name: str | None
    tags: list[str]
    capabilities: dict[str, str]
    last_seen: datetime
    status: str = "online"
