"""Codex 마스터 서버에 접속하는 간단한 노드 클라이언트."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import contextlib
from dataclasses import dataclass
from typing import Sequence

import websockets

LOGGER = logging.getLogger(__name__)


@dataclass
class NodeContext:
    display_name: str | None
    tags: list[str]
    client_id: str | None = None
    metadata_sent: bool = False


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

    prompt = payload.get("prompt", "")
    repositories = payload.get("repositories", [])
    print(f"[job {job_id}] 작업을 수신했습니다. 프롬프트: {prompt}")
    if isinstance(repositories, list) and repositories:
        for repo in repositories:
            repo_url = repo.get("url") if isinstance(repo, dict) else repo
            print(f"  - repo: {repo_url}")

    await websocket.send(
        json.dumps(
            {
                "type": "job.status",
                "job_id": job_id,
                "status": "running",
                "result_summary": "demo node acknowledged job",
            }
        )
    )

    await websocket.send(
        json.dumps(
            {
                "type": "job.log",
                "job_id": job_id,
                "level": "info",
                "message": "(demo) 작업을 즉시 완료합니다.",
            }
        )
    )

    await websocket.send(
        json.dumps(
            {
                "type": "job.status",
                "job_id": job_id,
                "status": "succeeded",
                "result_summary": "Demo node completed job",
            }
        )
    )


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


async def _run_client(host: str, port: int, *, display_name: str | None, tags: list[str]) -> None:
    uri = f"ws://{host}:{port}"
    LOGGER.info("Connecting to %s", uri)
    context = NodeContext(display_name=display_name, tags=tags)
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
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s: %(message)s")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    try:
        tag_list = [tag.strip() for tag in str(args.tags).split(",") if tag.strip()]
        asyncio.run(
            _run_client(
                args.host,
                args.port,
                display_name=args.display_name,
                tags=tag_list,
            )
        )
    except KeyboardInterrupt:
        LOGGER.info("클라이언트 종료")


if __name__ == "__main__":
    main(sys.argv[1:])
