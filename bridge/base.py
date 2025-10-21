"""마스터 서버와 플랫폼 브릿지 간 공통 로직."""

from __future__ import annotations

import abc
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import websockets

LOGGER = logging.getLogger(__name__)


class MasterBridgeError(RuntimeError):
    """브릿지 동작 중 발생한 예외."""


class MasterBridge(abc.ABC):
    """Codernetes 마스터 서버와 플랫폼을 중계하는 추상 베이스."""

    reconnect_delay: float = 5.0

    def __init__(self, host: str, port: int, platform: str) -> None:
        self._host = host
        self._port = port
        self._platform = platform
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._stop_event = asyncio.Event()

    @property
    def platform(self) -> str:
        return self._platform

    async def start(self) -> None:
        """마스터 서버와 지속적으로 연결을 유지한다."""
        LOGGER.info("[%s] 마스터 브릿지를 시작합니다.", self._platform)
        while not self._stop_event.is_set():
            try:
                async with self._connect_master() as websocket:
                    self._ws = websocket
                    await self.on_master_connected()
                    await self._receive_from_master(websocket)
            except asyncio.CancelledError:  # 프로그램 종료 시그널
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("[%s] 마스터 연결 오류: %s", self._platform, exc)
                await asyncio.sleep(self.reconnect_delay)
            finally:
                self._ws = None

    async def stop(self) -> None:
        """루프를 종료한다."""
        LOGGER.info("[%s] 브릿지를 종료합니다.", self._platform)
        self._stop_event.set()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close(code=1000, reason="Bridge stopped")

    @asynccontextmanager
    async def _connect_master(self) -> AsyncIterator[websockets.WebSocketClientProtocol]:
        uri = f"ws://{self._host}:{self._port}"
        LOGGER.info("[%s] 마스터 서버(%s)에 연결 시도", self._platform, uri)
        websocket = await websockets.connect(uri)
        try:
            yield websocket
        finally:
            await websocket.close()

    async def _receive_from_master(self, websocket: websockets.WebSocketClientProtocol) -> None:
        async for raw in websocket:
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                LOGGER.debug("[%s] JSON 파싱 실패, 원문 유지: %s", self._platform, raw)
                await self.on_master_message(raw, None)
                continue

            msg_type = payload.get("type")
            if msg_type != "message":
                LOGGER.debug("[%s] 알 수 없는 메시지 타입: %s", self._platform, payload)
                continue

            body = payload.get("payload")
            bridge_payload: Any
            if isinstance(body, str):
                bridge_payload = self._try_parse(body)
            else:
                bridge_payload = body
            await self.on_master_message(payload, bridge_payload)

    async def send_to_master(self, payload: Any) -> None:
        if self._ws is None or self._ws.closed:
            raise MasterBridgeError("마스터와 연결되지 않았습니다.")
        message = payload
        if not isinstance(payload, str):
            message = json.dumps(payload)
        await self._ws.send(message)

    async def on_master_connected(self) -> None:
        """마스터 서버에 접속한 직후 호출."""

    @abc.abstractmethod
    async def on_master_message(self, envelope: Any, parsed: Any) -> None:
        """마스터 서버에서 브로드캐스트된 메시지를 처리."""

    def _try_parse(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


async def run_bridges(*bridges: MasterBridge) -> None:
    """여러 브릿지를 동시에 실행."""

    async def _runner(bridge: MasterBridge) -> None:
        try:
            await bridge.start()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.exception("[%s] 브릿지 실행 중 오류 발생", bridge.platform)
            raise

    await asyncio.gather(*(_runner(bridge) for bridge in bridges))
