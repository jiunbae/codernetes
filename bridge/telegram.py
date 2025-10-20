"""Telegram <-> Codex 마스터 중계."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .base import MasterBridge, MasterBridgeError

LOGGER = logging.getLogger(__name__)


class TelegramBridge(MasterBridge):
    """Telegram Bot API 기반 중계."""

    api_base = "https://api.telegram.org"

    def __init__(
        self,
        host: str,
        port: int,
        bot_token: str,
        *,
        parse_mode: str | None = None,
        allowed_chats: set[int] | None = None,
    ) -> None:
        super().__init__(host, port, platform="telegram")
        self._bot_token = bot_token
        self._parse_mode = parse_mode
        self._allowed_chats = allowed_chats
        self._session: aiohttp.ClientSession | None = None
        self._stop_poll = asyncio.Event()
        self._update_offset: int | None = None
        self._bot_username: str | None = None

    async def start(self) -> None:  # type: ignore[override]
        timeout = aiohttp.ClientTimeout(total=40)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            self._session = session
            await self._hydrate_bot()
            await asyncio.gather(
                super().start(),
                self._poll_updates(),
            )

    async def stop(self) -> None:  # type: ignore[override]
        self._stop_poll.set()
        await super().stop()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def on_master_connected(self) -> None:  # type: ignore[override]
        LOGGER.info("[%s] 마스터 서버와 연결되었습니다.", self.platform)

    async def on_master_message(self, envelope: Any, parsed: Any) -> None:  # type: ignore[override]
        if not isinstance(parsed, dict):
            return

        target = parsed.get("target")
        if not isinstance(target, dict):
            return

        if target.get("platform") != "telegram":
            return

        chat_id = target.get("chat_id") or target.get("chat")
        if chat_id is None:
            LOGGER.warning("Telegram 전송 대상 chat_id가 없어 무시합니다: %s", parsed)
            return

        text = parsed.get("text") or parsed.get("message")
        if not text:
            LOGGER.debug("Telegram으로 전송할 텍스트 없음: %s", parsed)
            return

        reply_to = target.get("message_id") or target.get("reply_to")
        thread_id = target.get("thread_id") or target.get("message_thread_id")
        await self._send_message(int(chat_id), text, reply_to=reply_to, thread_id=thread_id)

    async def _hydrate_bot(self) -> None:
        result = await self._telegram_request("getMe")
        if not isinstance(result, dict):
            raise MasterBridgeError(f"Telegram getMe 응답 오류: {result}")
        self._bot_username = result.get("username")
        LOGGER.info("Telegram 봇 사용자: @%s", self._bot_username)

    async def _poll_updates(self) -> None:
        while not self._stop_poll.is_set():
            try:
                updates = await self._get_updates()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Telegram 업데이트 수신 실패: %s", exc)
                await asyncio.sleep(3)
                continue

            for update in updates:
                update_id = update.get("update_id")
                if update_id is not None:
                    self._update_offset = update_id + 1
                await self._handle_update(update)

    async def _get_updates(self) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": 30, "allowed_updates": ["message"]}
        if self._update_offset is not None:
            payload["offset"] = self._update_offset
        resp = await self._telegram_request("getUpdates", json=payload)
        if not isinstance(resp, list):
            raise MasterBridgeError(f"getUpdates 응답 오류: {resp}")
        return resp

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return

        if self._allowed_chats is not None and int(chat_id) not in self._allowed_chats:
            LOGGER.debug("허용되지 않은 채팅 %s, 무시", chat_id)
            return

        from_user = message.get("from") or {}
        payload = {
            "type": "command",
            "source": {
                "platform": "telegram",
                "chat_id": chat_id,
                "chat_type": chat.get("type"),
                "user_id": from_user.get("id"),
                "username": from_user.get("username"),
                "first_name": from_user.get("first_name"),
                "last_name": from_user.get("last_name"),
                "message_id": message.get("message_id"),
                "message_thread_id": message.get("message_thread_id"),
            },
            "text": text,
            "raw_update": update,
        }
        try:
            await self._forward_to_master(payload)
        except MasterBridgeError as exc:
            LOGGER.warning("Telegram 명령 전달 실패(마스터 연결 문제): %s", exc)

    async def _forward_to_master(self, payload: dict[str, Any]) -> None:
        LOGGER.debug("Telegram -> Master 전송: %s", payload)
        await self.send_to_master(payload)

    async def _send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to: int | None,
        thread_id: int | None,
    ) -> None:
        data: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if self._parse_mode:
            data["parse_mode"] = self._parse_mode
        if reply_to is not None:
            data["reply_to_message_id"] = reply_to
        if thread_id is not None:
            data["message_thread_id"] = thread_id
        await self._telegram_request("sendMessage", json=data)

    async def _telegram_request(self, method: str, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> Any:
        if self._session is None:
            raise MasterBridgeError("세션이 초기화되지 않았습니다.")
        url = f"{self.api_base}/bot{self._bot_token}/{method}"
        async with self._session.post(url, params=params, json=json) as resp:
            body = await resp.json()
            if not body.get("ok"):
                raise MasterBridgeError(f"Telegram API 오류({method}): {body}")
            return body.get("result")
