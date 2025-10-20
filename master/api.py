"""REST API 라우트."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from aiohttp import web

from .models import Job, JobStatus, RepositorySpec
from .storage import Storage


class ApiHandler:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def routes(self) -> tuple[web.RouteDef, ...]:
        return (
            web.get("/api/jobs", self.list_jobs),
            web.get("/api/jobs/{job_id}", self.get_job),
            web.post("/api/jobs", self.create_job),
            web.post("/api/jobs/{job_id}/status", self.update_job_status),
            web.get("/api/nodes", self.list_nodes),
        )

    async def list_jobs(self, request: web.Request) -> web.Response:
        status_param = request.query.get("status")
        status = JobStatus(status_param) if status_param else None
        jobs = self._storage.list_jobs(limit=100, status=status)
        payload = [self._job_to_dict(job) for job in jobs]
        return web.json_response({"jobs": payload})

    async def get_job(self, request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        job = self._storage.get_job(job_id)
        if job is None:
            raise web.HTTPNotFound(text="job not found")
        return web.json_response({"job": self._job_to_dict(job)})

    async def create_job(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            raise web.HTTPBadRequest(text="invalid json") from None

        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            raise web.HTTPBadRequest(text="prompt is required")

        repositories = [
            RepositorySpec(url=str(repo.get("url")), branch=repo.get("branch"), subdirectory=repo.get("subdirectory"))
            for repo in data.get("repositories", [])
            if repo.get("url")
        ]
        requested_tags = [tag.strip() for tag in data.get("requested_tags", []) if tag.strip()]
        target_node = str(data.get("target_node_id")) if data.get("target_node_id") else None

        job = Job(
            job_id=str(uuid.uuid4()),
            prompt=prompt,
            created_at=datetime.utcnow(),
            status=JobStatus.QUEUED if target_node else JobStatus.PENDING,
            target_node_id=target_node,
            requested_tags=requested_tags,
            repositories=repositories,
            metadata={"origin": data.get("origin", "api")},
        )
        self._storage.upsert_job(job)
        return web.json_response({"job": self._job_to_dict(job)}, status=201)

    async def update_job_status(self, request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            raise web.HTTPBadRequest(text="invalid json") from None

        status_value = data.get("status")
        if not status_value:
            raise web.HTTPBadRequest(text="status is required")

        try:
            status = JobStatus(status_value)
        except ValueError as exc:
            raise web.HTTPBadRequest(text="invalid status") from exc

        self._storage.update_job_status(
            job_id,
            status,
            log_path=data.get("log_path"),
            result_summary=data.get("result_summary"),
            error_message=data.get("error_message"),
        )
        job = self._storage.get_job(job_id)
        if job is None:
            raise web.HTTPNotFound(text="job not found")
        return web.json_response({"job": self._job_to_dict(job)})

    async def list_nodes(self, _: web.Request) -> web.Response:
        nodes = self._storage.list_nodes()
        payload = [
            {
                "node_id": node.node_id,
                "display_name": node.display_name,
                "tags": node.tags,
                "capabilities": node.capabilities,
                "status": node.status,
                "last_seen": node.last_seen.isoformat(),
            }
            for node in nodes
        ]
        return web.json_response({"nodes": payload})

    def _job_to_dict(self, job: Job) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "prompt": job.prompt,
            "status": job.status.value,
            "target_node_id": job.target_node_id,
            "requested_tags": job.requested_tags,
            "repositories": [repo.__dict__ for repo in job.repositories],
            "metadata": job.metadata,
            "log_path": job.log_path,
            "result_summary": job.result_summary,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
