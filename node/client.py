"""Codex 마스터 서버에 접속하는 간단한 노드 클라이언트."""

from __future__ import annotations

import argparse
import asyncio
import asyncio.subprocess
import contextlib
import json
import logging
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import websockets

LOGGER = logging.getLogger(__name__)


@dataclass
class NodeContext:
    display_name: str | None
    tags: list[str]
    workdir_root: Path
    codex_command: list[str]
    client_id: str | None = None
    metadata_sent: bool = False
    active_job_id: str | None = None
    current_log_path: Path | None = None

    def mark_busy(self, job_id: str) -> None:
        self.active_job_id = job_id

    def mark_idle(self) -> None:
        self.active_job_id = None
        self.current_log_path = None


async def _receiver(websocket, context: NodeContext) -> None:
    async for message in websocket:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            LOGGER.warning("수신한 메시지를 JSON으로 파싱할 수 없습니다: %s", message)
            continue

        msg_type = payload.get("type")
        if msg_type == "welcome":
            context.client_id = payload.get("client_id")
            print(f"[master] {payload.get('message')} (client_id={context.client_id})")
            await _send_node_hello(websocket, context)
        elif msg_type == "job.assign":
            await _handle_job_assign(websocket, context, payload)
        elif msg_type == "message":
            sender = payload.get("from", "unknown")
            print(f"[{sender}] {payload.get('payload')}")
        else:
            print(f"[unknown] {payload}")


async def _send_node_hello(websocket, context: NodeContext) -> None:
    if context.metadata_sent or not context.client_id:
        return
    message = {
        "type": "node.hello",
        "node_id": context.client_id,
        "display_name": context.display_name,
        "tags": context.tags,
        "capabilities": {},
    }
    await websocket.send(json.dumps(message))
    context.metadata_sent = True


async def _handle_job_assign(websocket, context: NodeContext, payload: dict[str, object]) -> None:
    job_id = payload.get("job_id")
    if not job_id:
        LOGGER.warning("job.assign payload에 job_id가 없습니다: %s", payload)
        return

    if context.active_job_id is not None:
        LOGGER.warning("이미 작업이 실행 중입니다. 새로운 작업 %s 를 거절합니다.", job_id)
        await websocket.send(
            json.dumps(
                {
                    "type": "job.status",
                    "job_id": job_id,
                    "status": "failed",
                    "error_message": "node is busy",
                }
            )
        )
        return

    prompt = payload.get("prompt", "")
    repositories = payload.get("repositories", [])
    print(f"[job {job_id}] 작업을 수신했습니다. 프롬프트: {prompt}")
    if isinstance(repositories, list) and repositories:
        for repo in repositories:
            repo_url = repo.get("url") if isinstance(repo, dict) else repo
            print(f"  - repo: {repo_url}")
    context.mark_busy(job_id)
    await websocket.send(
        json.dumps(
            {
                "type": "job.status",
                "job_id": job_id,
                "status": "running",
                "result_summary": "job started",
            }
        )
    )

    asyncio.create_task(_execute_job(websocket, context, payload))


async def _execute_job(websocket, context: NodeContext, payload: dict[str, object]) -> None:
    job_id = str(payload.get("job_id"))
    workdir = context.workdir_root / job_id
    prompt = str(payload.get("prompt", ""))
    repositories = payload.get("repositories", []) if isinstance(payload.get("repositories"), list) else []

    try:
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        context.current_log_path = workdir / "job.log"
        await _send_job_log(websocket, job_id, f"작업 디렉터리 생성: {workdir}", context=context)

        prompt_path = workdir / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        await _send_job_log(websocket, job_id, "프롬프트 파일 저장 완료", context=context)

        if repositories:
            for repo_spec in repositories:
                if not isinstance(repo_spec, dict):
                    continue
                url = str(repo_spec.get("url", "")).strip()
                if not url:
                    continue
                branch = repo_spec.get("branch")
                subdirectory = repo_spec.get("subdirectory")
                await _send_job_log(websocket, job_id, f"레포지토리 클론: {url}", context=context)
                ok = await _clone_repository(websocket, job_id, url, branch, workdir, context)
                if not ok:
                    raise RuntimeError(f"failed to clone {url}")
                if subdirectory:
                    await _send_job_log(websocket, job_id, f"서브디렉터리 지정: {subdirectory}", context=context)

        if context.codex_command:
            await _send_job_log(websocket, job_id, "Codex 명령 실행 시작", context=context)
            env = os.environ.copy()
            env["CODEX_PROMPT"] = prompt
            env["CODEX_PROMPT_FILE"] = str(prompt_path)
            success = await _run_command(websocket, job_id, context.codex_command, cwd=workdir, env=env, context=context)
            if not success:
                raise RuntimeError("codex command failed")
        else:
            await _send_job_log(websocket, job_id, "Codex 명령이 정의되지 않아 실행을 건너뜁니다.", context=context)

        await websocket.send(
            json.dumps(
                {
                    "type": "job.status",
                    "job_id": job_id,
                    "status": "succeeded",
                    "result_summary": "job completed successfully",
                    "log_path": str(context.current_log_path),
                }
            )
        )
        await _send_job_log(websocket, job_id, "작업 완료", level="info", context=context)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Job %s 실행 중 오류", job_id)
        await websocket.send(
            json.dumps(
                {
                    "type": "job.status",
                    "job_id": job_id,
                    "status": "failed",
                    "error_message": str(exc),
                }
            )
        )
        await _send_job_log(websocket, job_id, f"오류: {exc}", level="error", context=context)
    finally:
        context.mark_idle()


async def _send_job_log(
    websocket,
    job_id: str,
    message: str,
    *,
    level: str = "info",
    context: NodeContext | None = None,
) -> None:
    if context and context.current_log_path is not None:
        with context.current_log_path.open("a", encoding="utf-8") as fp:
            fp.write(f"[{level}] {message}\n")
    await websocket.send(
        json.dumps(
            {
                "type": "job.log",
                "job_id": job_id,
                "level": level,
                "message": message,
            }
        )
    )


async def _clone_repository(
    websocket,
    job_id: str,
    url: str,
    branch: str | None,
    workdir: Path,
    context: NodeContext,
) -> bool:
    repo_name = _derive_repo_name(url)
    target = workdir / repo_name
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", str(branch)]
    cmd += [url, str(target)]
    return await _run_command(websocket, job_id, cmd, cwd=workdir, context=context)


def _derive_repo_name(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or url
    name = Path(path.rstrip("/")).name
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repository"


async def _run_command(
    websocket,
    job_id: str,
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    context: NodeContext | None = None,
) -> bool:
    await _send_job_log(websocket, job_id, f"명령 실행: {' '.join(cmd)}", context=context)
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env=env,
    )

    async def _pipe(stream: asyncio.StreamReader, level: str) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            await _send_job_log(
                websocket,
                job_id,
                line.decode(errors="replace").rstrip(),
                level=level,
                context=context,
            )

    await asyncio.gather(_pipe(process.stdout, "info"), _pipe(process.stderr, "error"))
    return_code = await process.wait()
    await _send_job_log(websocket, job_id, f"명령 종료 코드: {return_code}", context=context)
    return return_code == 0


async def _sender(websocket) -> None:
    loop = asyncio.get_running_loop()
    while True:
        try:
            user_input = await loop.run_in_executor(None, input, "> ")
        except (EOFError, KeyboardInterrupt):
            print("입력을 종료합니다.")
            await websocket.close(code=1000, reason="Client exit")
            break

        trimmed = user_input.strip()
        if not trimmed:
            continue

        await websocket.send(trimmed)


async def _run_client(
    host: str,
    port: int,
    *,
    display_name: str | None,
    tags: list[str],
    workdir_root: Path,
    codex_command: list[str],
) -> None:
    uri = f"ws://{host}:{port}"
    LOGGER.info("Connecting to %s", uri)
    workdir_root.mkdir(parents=True, exist_ok=True)
    context = NodeContext(display_name=display_name, tags=tags, workdir_root=workdir_root, codex_command=codex_command)
    async with websockets.connect(uri) as websocket:
        receiver = asyncio.create_task(_receiver(websocket, context))
        sender = asyncio.create_task(_sender(websocket))
        done, pending = await asyncio.wait(
            {receiver, sender}, return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        for task in done:
            exc = task.exception()
            if exc:
                raise exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex 노드 클라이언트")
    parser.add_argument("--host", default="127.0.0.1", help="마스터 호스트")
    parser.add_argument("--port", type=int, default=8765, help="마스터 포트")
    parser.add_argument("--verbose", action="store_true", help="디버그 로그 출력")
    parser.add_argument("--display-name", default=None, help="노드 표시 이름")
    parser.add_argument(
        "--tags",
        default="",
        help="노드 태그 목록(콤마 구분)",
    )
    parser.add_argument(
        "--workdir-root",
        default="/tmp/codex-jobs",
        help="작업 디렉터리 루트 경로",
    )
    parser.add_argument(
        "--codex-command",
        default="",
        help="Codex 실행 명령 (예: 'python -m codex run')",
    )
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s: %(message)s")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    try:
        tag_list = [tag.strip() for tag in str(args.tags).split(",") if tag.strip()]
        codex_command = shlex.split(args.codex_command) if args.codex_command else []
        asyncio.run(
            _run_client(
                args.host,
                args.port,
                display_name=args.display_name,
                tags=tag_list,
                workdir_root=Path(args.workdir_root).expanduser(),
                codex_command=codex_command,
            )
        )
    except KeyboardInterrupt:
        LOGGER.info("클라이언트 종료")


if __name__ == "__main__":
    main(sys.argv[1:])
