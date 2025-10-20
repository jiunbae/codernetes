"""Codex 마스터와 플랫폼 브릿지를 구동하는 진입점."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Sequence

from .base import run_bridges
from .slack import SlackBridge
from .telegram import TelegramBridge

LOGGER = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex 마스터 플랫폼 브릿지")
    parser.add_argument("--master-host", default=os.getenv("MASTER_HOST", "127.0.0.1"), help="마스터 서버 호스트")
    parser.add_argument("--master-port", type=int, default=int(os.getenv("MASTER_PORT", "8765")), help="마스터 서버 포트")
    parser.add_argument("--log-level", default=os.getenv("BRIDGE_LOG_LEVEL", "INFO"), help="로그 레벨")

    parser.add_argument("--slack-bot-token", default=os.getenv("SLACK_BOT_TOKEN"), help="Slack 봇 토큰 (xoxb-)")
    parser.add_argument("--slack-default-channel", default=os.getenv("SLACK_DEFAULT_CHANNEL"), help="Slack 기본 응답 채널")

    parser.add_argument("--telegram-bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN"), help="Telegram 봇 토큰")
    parser.add_argument("--telegram-parse-mode", default=os.getenv("TELEGRAM_PARSE_MODE"), help="Telegram 메시지 parse_mode")
    parser.add_argument(
        "--telegram-allowed-chats",
        default=os.getenv("TELEGRAM_ALLOWED_CHATS"),
        help="허용할 Telegram chat_id 목록(콤마 구분)",
    )
    return parser.parse_args(argv)


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")


def build_bridges(args: argparse.Namespace) -> list:
    bridges = []
    if args.slack_bot_token:
        bridges.append(
            SlackBridge(
                host=args.master_host,
                port=args.master_port,
                bot_token=args.slack_bot_token,
                default_channel=args.slack_default_channel,
            )
        )
    if args.telegram_bot_token:
        allowed_chats = None
        if args.telegram_allowed_chats:
            allowed_chats = {
                int(item)
                for part in args.telegram_allowed_chats.split(",")
                if (item := part.strip())
            }
        bridges.append(
            TelegramBridge(
                host=args.master_host,
                port=args.master_port,
                bot_token=args.telegram_bot_token,
                parse_mode=args.telegram_parse_mode,
                allowed_chats=allowed_chats,
            )
        )
    return bridges


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)
    bridges = build_bridges(args)

    if not bridges:
        LOGGER.error("활성화할 브릿지가 없습니다. Slack/Telegram 토큰을 확인하세요.")
        return 1

    try:
        asyncio.run(run_bridges(*bridges))
    except KeyboardInterrupt:
        LOGGER.info("브릿지가 사용자 요청으로 종료되었습니다.")
        return 0
    except Exception:  # noqa: BLE001
        LOGGER.exception("브릿지 실행 중 치명적 오류")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
