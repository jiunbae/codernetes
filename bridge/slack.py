"""Slack <-> Codernetes 마스터 중계."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from typing import Any

import aiohttp
import websockets

from .base import MasterBridge, MasterBridgeError

LOGGER = logging.getLogger(__name__)

_SLACK_RTM_CONNECT = "https://slack.com/api/rtm.connect"
_SLACK_CHAT_POST_MESSAGE = "https://slack.com/api/chat.postMessage"
_SLACK_AUTH_TEST = "https://slack.com/api/auth.test"


class SlackBridge(MasterBridge):
    """Slack Bot 토큰을 사용해 메시지를 중계한다."""

    def __init__(self, host: str, port: int, bot_token: str, *, default_channel: str | None = None) -> None:
        super().__init__(host, port, platform="slack")
        self._bot_token = bot_token
        self._default_channel = default_channel
        self._session: aiohttp.ClientSession | None = None
        self._bot_user_id: str | None = None
        self._bot_team_id: str | None = None
        self._slack_stop = asyncio.Event()
        self._ping_id = 0

    async def start(self) -> None:  # type: ignore[override]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            self._session = session
            await self._hydrate_identity()
            await asyncio.gather(
                super().start(),
                self._slack_loop(),
            )

    async def stop(self) -> None:  # type: ignore[override]
        self._slack_stop.set()
        await super().stop()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def on_master_message(self, envelope: Any, parsed: Any) -> None:  # type: ignore[override]
        if not isinstance(parsed, dict):
            LOGGER.debug("[%s] Slack 대상 아님 (parsed=%s)", self.platform, parsed)
            return

        target = parsed.get("target")
        if not isinstance(target, dict):
            return

        if target.get("platform") != "slack":
            return

        channel = target.get("channel") or self._default_channel
        if not channel:
            LOGGER.warning("Slack 전송 대상 채널이 없어 무시합니다: %s", parsed)
            return

        text = parsed.get("text") or parsed.get("message")
        if not text:
            LOGGER.debug("Slack으로 전송할 텍스트가 없어 무시합니다: %s", parsed)
            return

        thread_ts = target.get("thread_ts") or target.get("ts")
        reply_broadcast = bool(parsed.get("broadcast", False))
        await self._post_message(channel, text, thread_ts=thread_ts, broadcast=reply_broadcast)

    async def on_master_connected(self) -> None:  # type: ignore[override]
        LOGGER.info("[%s] 마스터 서버와 연결되었습니다.", self.platform)

    async def _hydrate_identity(self) -> None:
        if self._session is None:
            raise MasterBridgeError("세션이 초기화되지 않았습니다.")
        headers = {"Authorization": f"Bearer {self._bot_token}"}
        async with self._session.post(_SLACK_AUTH_TEST, headers=headers) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise MasterBridgeError(f"Slack auth.test 실패: {data}")
            self._bot_user_id = data.get("user_id")
            self._bot_team_id = data.get("team_id")
            LOGGER.info("Slack 봇 사용자: %s (team=%s)", self._bot_user_id, self._bot_team_id)

    async def _slack_loop(self) -> None:
        assert self._session is not None
        headers = {"Authorization": f"Bearer {self._bot_token}"}
        while not self._slack_stop.is_set():
            try:
                url = await self._rtm_connect(headers)
                await self._consume_rtm(url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Slack RTM 연결 오류: %s", exc)
                await asyncio.sleep(5)

    async def _rtm_connect(self, headers: dict[str, str]) -> str:
        assert self._session is not None
        async with self._session.get(_SLACK_RTM_CONNECT, headers=headers) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise MasterBridgeError(f"rtm.connect 실패: {data}")
            return data["url"]

    async def _consume_rtm(self, ws_url: str) -> None:
        LOGGER.info("Slack RTM WebSocket 접속: %s", ws_url)
        async with websockets.connect(ws_url, ping_interval=None) as slack_ws:
            ping_task = asyncio.create_task(self._ping_loop(slack_ws))
            try:
                async for raw in slack_ws:
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        LOGGER.debug("Slack 이벤트 파싱 실패: %s", raw)
                        continue

                    etype = event.get("type")
                    if etype == "hello":
                        LOGGER.info("Slack RTM 연결 완료")
                        continue
                    if etype == "ping":
                        reply_to = event.get("id")
                        payload = {"type": "pong"}
                        if reply_to is not None:
                            payload["reply_to"] = reply_to
                        await slack_ws.send(json.dumps(payload))
                        continue
                    if etype == "message":
                        await self._handle_slack_message(event)
                        continue
                    if etype == "disconnect":
                        LOGGER.warning("Slack RTM disconnect 수신: %s", event)
                        break
                    if etype == "error":
                        LOGGER.error("Slack RTM error: %s", event)
                        continue
            finally:
                ping_task.cancel()
                with suppress(asyncio.CancelledError):
                    await ping_task

    async def _ping_loop(self, slack_ws: Any) -> None:
        while not slack_ws.closed:
            await asyncio.sleep(30)
            self._ping_id += 1
            payload = {"id": self._ping_id, "type": "ping", "time": time.time()}
            try:
                await slack_ws.send(json.dumps(payload))
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Slack ping 전송 실패: %s", exc)
                return

    async def _handle_slack_message(self, event: dict[str, Any]) -> None:
        subtype = event.get("subtype")
        if subtype and subtype != "thread_broadcast":
            return

        user = event.get("user")
        if not user or user == self._bot_user_id:
            return

        text = (event.get("text") or "").strip()
        if not text:
            return

        channel = event.get("channel")
        if not channel:
            return

        channel_type = event.get("channel_type")
        if not channel_type:
            channel_type = self._guess_channel_type(channel)

        if channel_type in {"channel", "group"}:
            if not self._bot_user_id:
                return
            mention = f"<@{self._bot_user_id}>"
            if mention in text:
                text = text.replace(mention, "", 1).strip()
            else:
                return

        thread_ts = event.get("thread_ts") or event.get("ts")
        user_profile = event.get("user_profile") or {}
        command = self._parse_command(text)
        payload = {
            "type": "command",
            "source": {
                "platform": "slack",
                "channel": channel,
                "thread_ts": thread_ts,
                "user": user,
                "team": event.get("team") or self._bot_team_id,
                "user_name": user_profile.get("display_name")
                or user_profile.get("real_name"),
            },
            "text": text,
            "command": command,
            "raw_event": event,
        }
        await self._forward_to_master(payload)

    async def _forward_to_master(self, payload: dict[str, Any]) -> None:
        LOGGER.debug("Slack -> Master 전송: %s", payload)
        await self.send_to_master(payload)

    async def _post_message(self, channel: str, text: str, *, thread_ts: str | None, broadcast: bool) -> None:
        assert self._session is not None
        body: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
            if broadcast:
                body["reply_broadcast"] = True
        headers = {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        async with self._session.post(_SLACK_CHAT_POST_MESSAGE, headers=headers, json=body) as resp:
            data = await resp.json()
            if not data.get("ok"):
                LOGGER.error("Slack 메시지 전송 실패: %s", data)

    def _guess_channel_type(self, channel_id: str) -> str:
        if channel_id.startswith("D"):
            return "im"
        if channel_id.startswith("G"):
            return "group"
        if channel_id.startswith("C"):
            return "channel"
        return "unknown"

    def _parse_command(self, text: str) -> dict[str, Any]:
        tokens = text.split()
        repos = []
        tags = []
        target = None
        prompt_tokens: list[str] = []
        for token in tokens:
            lower = token.lower()
            if lower.startswith("repo=") or lower.startswith("repos="):
                _, value = token.split("=", 1)
                if value:
                    repos.append({"url": value})
                continue
            if lower.startswith("repo:"):
                _, value = token.split(":", 1)
                if value:
                    repos.append({"url": value})
                continue
            if lower.startswith("tags="):
                _, value = token.split("=", 1)
                tags.extend([tag.strip() for tag in value.split(",") if tag.strip()])
                continue
            if lower.startswith("target="):
                _, value = token.split("=", 1)
                target = value.strip()
                continue
            prompt_tokens.append(token)

        prompt = " ".join(prompt_tokens).strip() or text
        return {
            "prompt": prompt,
            "repositories": repos,
            "requested_tags": tags,
            "target_node_id": target,
        }
