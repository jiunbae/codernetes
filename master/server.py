"""간단한 Codex 마스터 서버 구현."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from aiohttp import web
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .api import ApiHandler
from .models import Job, JobStatus, NodeMetadata
from .storage import Storage, init_storage

LOGGER = logging.getLogger(__name__)


@dataclass
class Client:
    """마스터에 연결된 클라이언트 메타데이터."""

    uid: str
    connection: ServerConnection
    last_seen: float
    status: str = "online"
    metadata: NodeMetadata | None = None


@dataclass
class RemoteNode:
    """원격 Codex 노드 메타데이터(목업)."""

    uid: str
    name: str
    host: str
    port: int
    tags: list[str]
    status: str
    last_seen: float | None = None
    notes: str = ""


class MasterServer:
    """노드 간 간단한 텍스트 메시지를 중계하는 마스터 서버."""

    def __init__(
        self,
        host: str,
        port: int,
        http_host: Optional[str],
        http_port: int,
        health_interval: float,
        health_timeout: float,
        storage: Storage,
    ) -> None:
        self._host = host
        self._port = port
        self._http_host = http_host or host
        self._http_port = http_port
        self._clients: Dict[ServerConnection, Client] = {}
        self._server: Server | None = None
        self._health_interval = max(health_interval, 1.0)
        self._health_timeout = max(health_timeout, 1.0)
        self._health_task: asyncio.Task | None = None
        self._dispatch_task: asyncio.Task | None = None
        self._dispatch_interval = 2.0
        self._storage = storage
        self._config = self._load_initial_config()
        self._config_updated_at = datetime.utcnow()
        self._remote_nodes: list[RemoteNode] = self._init_mock_remotes()
        self._frontend_dist = (
            Path(__file__).resolve().parent.parent / "frontend" / "dist"
        )
        self._web_app = web.Application()
        self._api_handler = ApiHandler(self._storage)
        self._web_app.add_routes(
            [
                web.get("/", self._handle_index),
                web.get("/api/status", self._handle_status),
                web.post("/api/broadcast", self._handle_broadcast),
                web.post("/api/send", self._handle_send),
                web.get("/api/config", self._handle_config_get),
                web.post("/api/config", self._handle_config_update),
                web.get("/api/remotes", self._handle_remotes_get),
                web.post("/api/remotes", self._handle_remotes_create),
                web.delete("/api/remotes/{remote_id}", self._handle_remote_delete),
                web.post("/api/remotes/{remote_id}/action", self._handle_remote_action),
            ]
        )
        self._web_app.add_routes(self._api_handler.routes())
        assets_dir = self._frontend_dist / "assets"
        if assets_dir.exists():
            self._web_app.router.add_static("/assets", assets_dir, show_index=False)
        # SPA fallback 라우트
        self._web_app.router.add_get("/{tail:.*}", self._handle_index)
        self._web_runner: web.AppRunner | None = None
        self._web_site: web.TCPSite | None = None

    async def start(self) -> None:
        """WebSocket 서버를 시작한다."""
        LOGGER.info("Starting master server on %s:%s", self._host, self._port)
        self._server = await serve(
            self._handler,
            self._host,
            self._port,
            process_request=self._process_ws_request,
        )
        await self._start_http()
        self._start_health_monitor()
        self._start_dispatcher()

    async def stop(self) -> None:
        """서버를 안전하게 종료한다."""
        LOGGER.info("Stopping master server")
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        await self._cleanup_clients()
        await self._stop_http()
        await self._stop_health_monitor()
        await self._stop_dispatcher()

    async def _cleanup_clients(self) -> None:
        """모든 클라이언트 연결을 닫는다."""
        if not self._clients:
            return
        LOGGER.info("Closing %d client connection(s)", len(self._clients))
        await asyncio.gather(
            *(client.connection.close(code=1001, reason="Server shutdown") for client in self._clients.values()),
            return_exceptions=True,
        )
        self._clients.clear()

    async def _start_http(self) -> None:
        if self._web_runner is not None:
            return

        self._web_runner = web.AppRunner(self._web_app)
        await self._web_runner.setup()
        self._web_site = web.TCPSite(self._web_runner, self._http_host, self._http_port)
        await self._web_site.start()
        LOGGER.info("HTTP UI available on http://%s:%s", self._http_host, self._http_port)

    async def _stop_http(self) -> None:
        if self._web_site is not None:
            await self._web_site.stop()
            self._web_site = None
        if self._web_runner is not None:
            await self._web_runner.cleanup()
            self._web_runner = None

    def _start_health_monitor(self) -> None:
        if self._health_task is None:
            self._health_task = asyncio.create_task(self._health_loop())

    async def _stop_health_monitor(self) -> None:
        if self._health_task is None:
            return
        self._health_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._health_task
        self._health_task = None

    def _start_dispatcher(self) -> None:
        if self._dispatch_task is None:
            self._dispatch_task = asyncio.create_task(self._dispatch_loop())

    async def _stop_dispatcher(self) -> None:
        if self._dispatch_task is None:
            return
        self._dispatch_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._dispatch_task
        self._dispatch_task = None

    async def _health_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._health_interval)
                await self._perform_health_checks()
        except asyncio.CancelledError:
            LOGGER.debug("Health monitor stopped")

    async def _dispatch_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._dispatch_interval)
                await self._dispatch_jobs_once()
        except asyncio.CancelledError:
            LOGGER.debug("Job dispatcher stopped")

    async def _perform_health_checks(self) -> None:
        if not self._clients:
            return

        await asyncio.gather(
            *(self._check_client_health(client) for client in list(self._clients.values())),
            return_exceptions=True,
        )

    async def _dispatch_jobs_once(self) -> None:
        if not self._clients:
            return

        candidates = [client for client in self._clients.values() if self._is_client_available(client)]
        if not candidates:
            return

        jobs = self._storage.list_jobs_by_status([JobStatus.QUEUED, JobStatus.PENDING], limit=200)
        if not jobs:
            return

        for client in candidates:
            job = self._select_job_for_client(client, jobs)
            if job is None:
                continue
            if job.status in {JobStatus.PENDING, JobStatus.QUEUED}:
                assigned = self._storage.assign_job(job.job_id, client.uid)
                if not assigned:
                    continue
                job.status = JobStatus.RUNNING
                job.target_node_id = client.uid

            await self._send_job_assignment(client, job)
            jobs = [j for j in jobs if j.job_id != job.job_id]
            if not jobs:
                break

    def _is_client_available(self, client: Client) -> bool:
        closed_attr = getattr(client.connection, "closed", None)
        if isinstance(closed_attr, bool) and closed_attr:
            return False
        if client.status not in {"online"}:
            return False
        metadata = client.metadata
        if metadata is None:
            return True
        return metadata.status in {"online", "idle"}

    def _select_job_for_client(self, client: Client, jobs: list[Job]) -> Job | None:
        # 우선 순위: 특정 노드에 할당된 QUEUED 작업
        for job in jobs:
            if job.status == JobStatus.QUEUED and job.target_node_id == client.uid:
                return job

        metadata = client.metadata
        node_tags = set(metadata.tags) if metadata else set()

        for job in jobs:
            if job.status != JobStatus.PENDING:
                continue
            if job.target_node_id not in (None, ""):
                continue
            requested_tags = set(job.requested_tags)
            if requested_tags and not requested_tags.issubset(node_tags):
                continue
            return job
        return None

    async def _send_job_assignment(self, client: Client, job: Job) -> None:
        workdir = f"{self._config.get('job', {}).get('workdir_root', '/tmp/codex-jobs')}/{job.job_id}"
        message = {
            "type": "job.assign",
            "job_id": job.job_id,
            "prompt": job.prompt,
            "repositories": [repo.__dict__ for repo in job.repositories],
            "workdir": workdir,
            "metadata": job.metadata,
            "requested_tags": job.requested_tags,
            "target_node_id": client.uid,
        }
        LOGGER.info("Dispatching job %s to node %s", job.job_id, client.uid)
        client.status = "busy"
        await client.connection.send(json.dumps(message))
        self._update_node_record(client, status="busy")

    async def _check_client_health(self, client: Client) -> None:
        if client.connection.closed:
            client.status = "disconnected"
            self._update_node_record(client, status="offline")
            return

        ping_waiter = client.connection.ping()
        try:
            await asyncio.wait_for(ping_waiter, timeout=self._health_timeout)
            client.last_seen = time.time()
            if client.status != "online":
                client.status = "online"
            self._update_node_record(client, status="online")
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            LOGGER.warning("Health check failed for %s: %s", client.uid, exc)
            client.status = "unresponsive"
            self._update_node_record(client, status="unresponsive")

    async def _handler(self, connection: ServerConnection) -> None:
        client = Client(uid=str(uuid.uuid4()), connection=connection, last_seen=time.time())
        self._clients[connection] = client
        LOGGER.info("Client %s connected", client.uid)
        self._register_node(client)

        # 연결된 클라이언트에게 인사말을 전송
        await connection.send(
            json.dumps(
                {
                    "type": "welcome",
                    "client_id": client.uid,
                    "message": "Connected to Codex master",
                }
            )
        )

        try:
            async for raw_message in connection:
                LOGGER.debug("Received message from %s: %s", client.uid, raw_message)
                client.last_seen = time.time()
                client.status = "online"
                self._update_node_record(client, status="online")
                if self._process_incoming_message(client, raw_message):
                    continue
                await self._broadcast(raw_message, sender=client)
        except ConnectionClosed as exc:
            LOGGER.info("Client %s disconnected (%s)", client.uid, exc.code)
        finally:
            client.status = "disconnected"
            self._update_node_record(client, status="offline")
            self._clients.pop(connection, None)

    async def _broadcast(self, raw_message: str, sender: Optional[Client]) -> None:
        """송신자를 제외한 모든 클라이언트에 메시지를 전달."""
        if not self._clients:
            LOGGER.debug("No clients to broadcast message")
            return

        payload = self._build_message_payload(raw_message, sender)
        payload_json = json.dumps(payload)
        recipient_count = len(self._clients) if sender is None else len(self._clients) - 1
        LOGGER.debug(
            "Broadcasting message from %s to %d client(s)",
            payload["from"],
            max(recipient_count, 0),
        )
        if sender is None:
            now = time.time()
            for client in self._clients.values():
                client.last_seen = now
                client.status = "online"
        await asyncio.gather(
            *(
                client.connection.send(payload_json)
                for conn, client in self._clients.items()
                if sender is None or conn is not sender.connection
            ),
            return_exceptions=True,
        )

    def _build_message_payload(self, raw_message: str, sender: Optional[Client]) -> dict:
        return {
            "type": "message",
            "from": sender.uid if sender is not None else "master",
            "payload": raw_message,
        }

    def _find_client(self, client_id: str) -> Optional[Client]:
        for client in self._clients.values():
            if client.uid == client_id:
                return client
        return None

    async def _send_to_client(self, client_id: str, raw_message: str) -> bool:
        client = self._find_client(client_id)
        if client is None:
            return False
        payload_json = json.dumps(self._build_message_payload(raw_message, sender=None))
        await client.connection.send(payload_json)
        client.last_seen = time.time()
        if client.status != "online":
            client.status = "online"
            self._update_node_record(client, status="online")
        LOGGER.debug("Sent direct message to %s", client_id)
        return True

    def _register_node(self, client: Client) -> None:
        metadata = NodeMetadata(
            node_id=client.uid,
            display_name=None,
            tags=[],
            capabilities={},
            last_seen=datetime.utcnow(),
            status="online",
        )
        client.metadata = metadata
        self._storage.upsert_node(metadata)

    def _update_node_record(
        self,
        client: Client,
        *,
        status: str | None = None,
        display_name: str | None = None,
        tags: list[str] | None = None,
        capabilities: dict[str, str] | None = None,
    ) -> None:
        metadata = client.metadata
        now = datetime.utcnow()
        if metadata is None:
            metadata = NodeMetadata(
                node_id=client.uid,
                display_name=display_name,
                tags=tags or [],
                capabilities=capabilities or {},
                last_seen=now,
                status=status or "online",
            )
        else:
            updates: dict[str, Any] = {"last_seen": now}
            if status is not None:
                updates["status"] = status
            if display_name is not None:
                updates["display_name"] = display_name
            if tags is not None:
                updates["tags"] = tags
            if capabilities is not None:
                updates["capabilities"] = capabilities
            metadata = replace(metadata, **updates)

        client.metadata = metadata
        self._storage.upsert_node(metadata)

    def _process_incoming_message(self, client: Client, raw_message: str) -> bool:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            return False

        if not isinstance(payload, dict):
            return False

        message_type = payload.get("type")
        if message_type == "job.status":
            self._handle_job_status_message(client, payload)
            return True
        if message_type == "job.log":
            self._handle_job_log_message(client, payload)
            return True
        if message_type == "node.hello":
            self._handle_node_hello_message(client, payload)
            return True
        return False

    def _handle_job_status_message(self, client: Client, payload: dict[str, Any]) -> None:
        job_id = payload.get("job_id")
        status_value = payload.get("status")
        if not job_id or not status_value:
            LOGGER.warning("Invalid job.status payload from %s: %s", client.uid, payload)
            return

        try:
            status = JobStatus(status_value)
        except ValueError:
            LOGGER.warning("Unknown job status '%s' from %s", status_value, client.uid)
            return

        self._storage.update_job_status(
            job_id,
            status,
            log_path=payload.get("log_path"),
            result_summary=payload.get("result_summary"),
            error_message=payload.get("error_message"),
        )

        if status == JobStatus.RUNNING:
            node_status = "busy"
        elif status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
            node_status = "online"
        else:
            node_status = client.status
        if node_status:
            client.status = node_status
            self._update_node_record(client, status=node_status)

    def _handle_job_log_message(self, client: Client, payload: dict[str, Any]) -> None:
        job_id = payload.get("job_id", "unknown")
        level = str(payload.get("level", "info")).lower()
        message = payload.get("message", "")
        log_message = "[job %s] %s", job_id, message
        if level == "error":
            LOGGER.error(*log_message)
        elif level == "warning":
            LOGGER.warning(*log_message)
        else:
            LOGGER.info(*log_message)

    def _handle_node_hello_message(self, client: Client, payload: dict[str, Any]) -> None:
        display_name = payload.get("display_name")
        tags = payload.get("tags") or []
        capabilities = payload.get("capabilities") or {}
        if not isinstance(tags, list):
            tags = []
        if not isinstance(capabilities, dict):
            capabilities = {}
        self._update_node_record(
            client,
            status="online",
            display_name=display_name,
            tags=[str(tag) for tag in tags],
            capabilities={str(k): str(v) for k, v in capabilities.items()},
        )

    def _load_initial_config(self) -> dict[str, Any]:
        master_host = os.getenv("MASTER_HOST", self._host)
        http_host = os.getenv("MASTER_HTTP_HOST", self._http_host)
        bridge_tags_raw = os.getenv("REMOTE_DEFAULT_TAGS", "staging,linux")
        autostart_raw = os.getenv("BRIDGE_AUTOSTART", "false")
        config = {
            "master": {
                "host": master_host,
                "port": int(os.getenv("MASTER_PORT", str(self._port))),
                "http_host": http_host,
                "http_port": int(os.getenv("MASTER_HTTP_PORT", str(self._http_port))),
                "health_interval": self._health_interval,
                "health_timeout": self._health_timeout,
            },
            "bridge": {
                "log_level": os.getenv("BRIDGE_LOG_LEVEL", "INFO"),
                "autostart": autostart_raw.lower() in {"1", "true", "yes"},
                "remote_default_tags": [tag.strip() for tag in bridge_tags_raw.split(",") if tag.strip()],
            },
            "slack": {
                "bot_token": os.getenv("SLACK_BOT_TOKEN", ""),
                "default_channel": os.getenv("SLACK_DEFAULT_CHANNEL", ""),
            },
            "telegram": {
                "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
                "parse_mode": os.getenv("TELEGRAM_PARSE_MODE", ""),
                "allowed_chats": os.getenv("TELEGRAM_ALLOWED_CHATS", ""),
            },
            "job": {
                "workdir_root": os.getenv("JOB_WORKDIR_ROOT", "/tmp/codex-jobs"),
            },
            "notes": os.getenv("MASTER_NOTES", ""),
        }
        return config

    def _init_mock_remotes(self) -> list[RemoteNode]:
        tags = self._config.get("bridge", {}).get("remote_default_tags", [])
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        now = time.time()
        return [
            RemoteNode(
                uid=str(uuid.uuid4()),
                name="staging-codex",
                host="10.0.10.4",
                port=9000,
                tags=list(tags) or ["staging"],
                status="online",
                last_seen=now - 120,
                notes="최근 빌드 이후 정상",
            ),
            RemoteNode(
                uid=str(uuid.uuid4()),
                name="prod-runner-1",
                host="10.0.10.21",
                port=9000,
                tags=["production", "a100"],
                status="maintenance",
                last_seen=None,
                notes="GPU 점검 예정",
            ),
        ]

    def _mask_secret(self, value: str) -> str:
        value = value or ""
        if not value:
            return ""
        if len(value) <= 4:
            return "*" * len(value)
        return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"

    def _split_csv(self, value: str | None) -> list[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    def _normalize_tags(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return self._split_csv(value)
        return []

    def _config_payload(self) -> dict[str, Any]:
        master_cfg = dict(self._config.get("master", {}))
        bridge_cfg = dict(self._config.get("bridge", {}))
        slack_cfg = dict(self._config.get("slack", {}))
        telegram_cfg = dict(self._config.get("telegram", {}))

        bridge_tags = bridge_cfg.get("remote_default_tags", [])
        if isinstance(bridge_tags, str):
            bridge_tags_list = self._split_csv(bridge_tags)
        else:
            bridge_tags_list = list(bridge_tags)
        bridge_cfg["remote_default_tags"] = bridge_tags_list
        bridge_cfg["remote_default_tags_csv"] = ", ".join(bridge_tags_list)

        slack_cfg.setdefault("bot_token", "")
        slack_cfg.setdefault("default_channel", "")
        slack_cfg["bot_token_masked"] = self._mask_secret(slack_cfg["bot_token"])
        slack_cfg["has_token"] = bool(slack_cfg["bot_token"])

        telegram_cfg.setdefault("bot_token", "")
        telegram_cfg.setdefault("parse_mode", "")
        telegram_cfg.setdefault("allowed_chats", "")
        telegram_cfg["bot_token_masked"] = self._mask_secret(telegram_cfg["bot_token"])
        telegram_cfg["allowed_chats_list"] = self._split_csv(telegram_cfg["allowed_chats"])

        job_cfg = dict(self._config.get("job", {}))
        job_cfg.setdefault("workdir_root", "/tmp/codex-jobs")

        payload = {
            "master": master_cfg,
            "bridge": bridge_cfg,
            "slack": slack_cfg,
            "telegram": telegram_cfg,
            "job": job_cfg,
            "notes": self._config.get("notes", ""),
            "updated_at": self._config_updated_at.isoformat(timespec="seconds"),
        }
        return payload

    def _remote_to_payload(self, remote: RemoteNode) -> dict[str, Any]:
        return {
            "id": remote.uid,
            "name": remote.name,
            "host": remote.host,
            "port": remote.port,
            "address": f"{remote.host}:{remote.port}",
            "tags": remote.tags,
            "status": remote.status,
            "last_seen": (
                datetime.fromtimestamp(remote.last_seen).isoformat(timespec="seconds")
                if remote.last_seen
                else None
            ),
            "notes": remote.notes,
        }

    def _find_remote(self, remote_id: str) -> Optional[RemoteNode]:
        for remote in self._remote_nodes:
            if remote.uid == remote_id:
                return remote
        return None


    async def _handle_index(self, request: web.Request) -> web.Response:
        if request.path.startswith("/api/"):
            raise web.HTTPNotFound()

        index_path = self._frontend_dist / "index.html"
        if index_path.exists():
            return web.FileResponse(index_path)

        placeholder = """
<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <title>Codex Master Control</title>
    <style>
      body {
        margin: 0;
        padding: 3rem;
        font-family: 'Noto Sans KR', 'Segoe UI', sans-serif;
        background: #0f172a;
        color: #e2e8f0;
      }
      main {
        max-width: 640px;
        margin: 0 auto;
        background: #111c32;
        padding: 2rem 2.5rem;
        border-radius: 20px;
        box-shadow: 0 30px 60px rgba(15, 23, 42, 0.35);
      }
      h1 {
        margin-top: 0;
        font-size: 1.75rem;
      }
      p {
        line-height: 1.6;
      }
      code {
        background: rgba(148, 163, 184, 0.15);
        padding: 0.15rem 0.4rem;
        border-radius: 6px;
      }
      a {
        color: #93c5fd;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>프런트엔드 번들이 준비되지 않았습니다</h1>
      <p>
        React 대시보드를 사용하려면 <code>frontend</code> 디렉터리에서
        <code>npm install</code>, <code>npm run build</code> 명령을 실행한 뒤
        마스터 서버를 다시 시작하세요.
      </p>
      <p>
        개발 중이라면 <code>npm run dev</code> 를 실행하고 Vite 개발 서버
        (기본 포트 5173)에 접속해 UI를 확인할 수 있습니다. 이때 API 요청은
        프록시를 통해 현재 마스터(포트 8765)로 전달됩니다.
      </p>
    </main>
  </body>
</html>
"""
        return web.Response(text=placeholder, content_type="text/html")

    async def _handle_status(self, _: web.Request) -> web.Response:
        payload = {
            "status": "ok",
            "connected_clients": len(self._clients),
            "clients": [
                {
                    "id": client.uid,
                    "status": client.status,
                    "last_seen": datetime.fromtimestamp(client.last_seen).isoformat(timespec="seconds"),
                }
                for client in self._clients.values()
            ],
        }
        return web.json_response(payload)

    async def _handle_config_get(self, _: web.Request) -> web.Response:
        return web.json_response({"config": self._config_payload()})

    async def _handle_config_update(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "JSON body required"}, status=400)

        if not isinstance(data, dict):
            return web.json_response({"error": "JSON object expected"}, status=400)

        self._apply_config_update(data)
        self._config_updated_at = datetime.utcnow()
        return web.json_response({"config": self._config_payload(), "status": "ok"})

    def _apply_config_update(self, data: dict[str, Any]) -> None:
        master_cfg = data.get("master")
        if isinstance(master_cfg, dict):
            target = self._config.setdefault("master", {})
            if "host" in master_cfg:
                target["host"] = str(master_cfg["host"]).strip()
            if "http_host" in master_cfg:
                target["http_host"] = str(master_cfg["http_host"]).strip()
            for key in ("port", "http_port"):
                if key in master_cfg:
                    with suppress(ValueError, TypeError):
                        target[key] = int(master_cfg[key])
            for key in ("health_interval", "health_timeout"):
                if key in master_cfg:
                    with suppress(ValueError, TypeError):
                        target[key] = float(master_cfg[key])

        bridge_cfg = data.get("bridge")
        if isinstance(bridge_cfg, dict):
            target = self._config.setdefault("bridge", {})
            if "log_level" in bridge_cfg:
                target["log_level"] = str(bridge_cfg["log_level"]).strip() or "INFO"
            if "autostart" in bridge_cfg:
                target["autostart"] = bool(bridge_cfg["autostart"])
            if "remote_default_tags" in bridge_cfg:
                target["remote_default_tags"] = self._normalize_tags(bridge_cfg["remote_default_tags"])

        slack_cfg = data.get("slack")
        if isinstance(slack_cfg, dict):
            target = self._config.setdefault("slack", {})
            for key in ("bot_token", "default_channel"):
                if key in slack_cfg:
                    target[key] = str(slack_cfg[key]).strip()

        telegram_cfg = data.get("telegram")
        if isinstance(telegram_cfg, dict):
            target = self._config.setdefault("telegram", {})
            for key in ("bot_token", "parse_mode", "allowed_chats"):
                if key in telegram_cfg:
                    target[key] = str(telegram_cfg[key]).strip()

        job_cfg = data.get("job")
        if isinstance(job_cfg, dict):
            target = self._config.setdefault("job", {})
            if "workdir_root" in job_cfg:
                target["workdir_root"] = str(job_cfg["workdir_root"]).strip() or "/tmp/codex-jobs"

        if "notes" in data:
            self._config["notes"] = str(data["notes"]).strip()

    async def _handle_remotes_get(self, _: web.Request) -> web.Response:
        remotes_payload = [self._remote_to_payload(remote) for remote in self._remote_nodes]
        return web.json_response(
            {
                "remotes": remotes_payload,
                "count": len(remotes_payload),
                "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
            }
        )

    async def _handle_remotes_create(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "JSON body required"}, status=400)
        if not isinstance(data, dict):
            return web.json_response({"error": "JSON object expected"}, status=400)

        name = str(data.get("name", "")).strip()
        host = str(data.get("host", "")).strip()
        port_value = data.get("port", 0)
        notes = str(data.get("notes", "")).strip()
        tags = self._normalize_tags(data.get("tags"))

        if not name or not host:
            return web.json_response({"error": "'name'와 'host'를 입력하세요."}, status=400)
        try:
            port = int(port_value) if port_value else 0
        except (TypeError, ValueError):
            return web.json_response({"error": "유효한 'port' 값을 입력하세요."}, status=400)
        if port <= 0 or port > 65535:
            port = 9000

        remote = RemoteNode(
            uid=str(uuid.uuid4()),
            name=name,
            host=host,
            port=port,
            tags=tags,
            status="provisioning",
            last_seen=time.time(),
            notes=notes,
        )
        self._remote_nodes.append(remote)
        payload = self._remote_to_payload(remote)
        return web.json_response({"remote": payload, "status": "ok"}, status=201)

    async def _handle_remote_delete(self, request: web.Request) -> web.Response:
        remote_id = request.match_info.get("remote_id", "")
        remote = self._find_remote(remote_id)
        if remote is None:
            return web.json_response({"error": "존재하지 않는 원격 노드입니다."}, status=404)
        self._remote_nodes = [node for node in self._remote_nodes if node.uid != remote_id]
        return web.json_response({"status": "ok"})

    async def _handle_remote_action(self, request: web.Request) -> web.Response:
        remote_id = request.match_info.get("remote_id", "")
        remote = self._find_remote(remote_id)
        if remote is None:
            return web.json_response({"error": "존재하지 않는 원격 노드입니다."}, status=404)
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "JSON body required"}, status=400)
        action = str(data.get("action", "")).strip().lower()

        now = time.time()
        if action == "mark_online":
            remote.status = "online"
            remote.last_seen = now
        elif action == "mark_offline":
            remote.status = "offline"
        elif action == "mark_maintenance":
            remote.status = "maintenance"
        elif action == "mark_busy":
            remote.status = "busy"
            remote.last_seen = now
        elif action == "touch":
            remote.last_seen = now
        else:
            return web.json_response({"error": "지원하지 않는 action입니다."}, status=400)

        return web.json_response({"remote": self._remote_to_payload(remote), "status": "ok"})

    async def _handle_broadcast(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:  # JSONDecodeError 포함
            return web.json_response({"error": "JSON body required"}, status=400)

        message = str(data.get("message", "")).strip()
        if not message:
            return web.json_response({"error": "'message' 필드를 입력하세요."}, status=400)

        await self._broadcast(message, sender=None)
        return web.json_response(
            {
                "status": "ok",
                "broadcasted": message,
                "connected_clients": len(self._clients),
            }
        )

    async def _handle_send(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "JSON body required"}, status=400)

        target_id = str(data.get("client_id", "")).strip()
        message = str(data.get("message", "")).strip()

        if not target_id:
            return web.json_response({"error": "'client_id' 필드를 입력하세요."}, status=400)
        if not message:
            return web.json_response({"error": "'message' 필드를 입력하세요."}, status=400)

        success = await self._send_to_client(target_id, message)
        if not success:
            return web.json_response({"error": "존재하지 않는 클라이언트입니다."}, status=404)

        return web.json_response(
            {
                "status": "ok",
                "client_id": target_id,
                "message": message,
            }
        )

    async def _process_ws_request(
        self,
        path: str,
        request_headers: Any,
    ) -> Optional[Tuple[HTTPStatus, list[tuple[str, str]], bytes]]:
        """일반 HTTP 요청이 WebSocket 엔드포인트로 들어오면 안내 메시지 반환."""
        headers_obj = getattr(request_headers, "headers", request_headers)
        upgrade_header = ""
        if hasattr(headers_obj, "get"):
            upgrade_header = headers_obj.get("Upgrade", "").lower()
        if upgrade_header != "websocket":
            body = b"This endpoint expects a WebSocket upgrade.\n"
            return (
                HTTPStatus.UPGRADE_REQUIRED,
                [("Content-Type", "text/plain; charset=utf-8"), ("Connection", "close")],
                body,
            )
        return None


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s: %(message)s")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex master server")
    parser.add_argument("--host", default="0.0.0.0", help="바인딩할 호스트 주소")
    parser.add_argument("--port", type=int, default=8765, help="바인딩할 포트")
    parser.add_argument("--verbose", action="store_true", help="디버그 로그 활성화")
    parser.add_argument("--http-host", default=None, help="웹 UI 바인딩 호스트 (기본: --host와 동일)")
    parser.add_argument("--http-port", type=int, default=8080, help="웹 UI 포트")
    parser.add_argument("--health-interval", type=float, default=15.0, help="헬스 체크 주기(초)")
    parser.add_argument("--health-timeout", type=float, default=5.0, help="헬스 체크 타임아웃(초)")
    parser.add_argument("--db-path", default="var/codex-master.db", help="작업/노드 상태를 저장할 SQLite 경로")
    return parser.parse_args(argv)


async def _run_server(args: argparse.Namespace) -> None:
    storage = init_storage(args.db_path)
    server = MasterServer(
        args.host,
        args.port,
        args.http_host,
        args.http_port,
        args.health_interval,
        args.health_timeout,
        storage,
    )
    await server.start()

    stop_event = asyncio.Event()

    def _handle_signal(*_: signal.Signals) -> None:
        LOGGER.info("Received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handle_signal)

    try:
        await stop_event.wait()
    finally:
        await server.stop()
        storage.close()


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    try:
        asyncio.run(_run_server(args))
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received")


if __name__ == "__main__":
    main(sys.argv[1:])
