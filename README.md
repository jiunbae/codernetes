# Codex Super Client (Prototype)

이 프로젝트는 소규모 팀을 위한 Codex 마스터/노드 메시지 허브 프로토타입입니다. 초기 목표는 마스터 프로세스가 여러 노드와 WebSocket으로 연결되어 간단한 텍스트 명령을 주고받을 수 있도록 하는 것입니다.

## 기본 구조

- `master`: 중앙 메시지 허브. 노드 연결을 관리하고 들어온 메시지를 브로드캐스트합니다.
- `node`: 마스터에 연결하는 예제 노드. 텍스트를 전송하고 마스터 및 다른 노드로부터 메시지를 수신합니다.
- `bridge`: Slack/Telegram 등 외부 메신저를 Codex 마스터와 양방향으로 연결하는 브릿지.
- `frontend`: 대시보드를 제공하는 React(Vite) 기반 웹 프런트엔드.

## 기술 선택 (초기 버전)

- 언어: Python 3.11+
- 통신: WebSocket (`websockets` 라이브러리 활용)
- 실행: 단일 호스트 혹은 Docker Compose 기반 실행을 우선 지원

## 개발 계획

1. 마스터 서버 최소 기능 구현
   - 노드 연결/해제 로깅
   - 메시지 브로드캐스트 (송신자 제외)
2. 노드 예제 구현
   - CLI에서 메시지 입력 후 송신
   - 수신 메시지 표준 출력
3. 향후 작업
   - 인증 토큰 추가
   - 작업 큐/상태 저장 통합
   - 노드별 실행 결과 포맷 표준화 및 저장

## 빠른 시작

```bash
uv sync
source .venv/bin/activate  # 선택 사항: uv run 명령으로도 실행 가능

uv run python -m master.server --host 0.0.0.0 --port 8765 --http-port 8080
uv run python -m node.client --host 127.0.0.1 --port 8765
```

- 첫 번째 터미널에서 마스터 서버를 실행한 뒤, 별도 터미널에서 노드 클라이언트를 실행하세요.
- 클라이언트 콘솔에 입력한 텍스트는 연결된 다른 노드(또는 향후 메신저 연동)로 브로드캐스트됩니다.
- 브라우저에서 `http://<호스트>:8080`을 열면 React 기반 대시보드가 노드 상태, 브리지 설정, 원격 노드(목업) 관리 UI를 제공합니다. 마스터는 기본적으로 15초마다 각 노드를 ping 하여 상태(`온라인/응답 없음`)와 최근 활동 시각을 갱신해 UI에 반영합니다. `--http-host`를 생략하면 `--host` 값과 동일한 주소로 바인딩되며, 별도 지정 시 외부 접근 범위를 조절할 수 있습니다.

## 환경 변수 템플릿

리포지토리 루트에는 `.env.sample`이 포함되어 있습니다. 프로젝트를 처음 셋업할 때 아래와 같이 복사한 뒤 값을 채워 넣으면 마스터 서버와 브릿지가 동일한 설정을 참조할 수 있습니다.

```bash
cp .env.sample .env
```

- `MASTER_*` 항목은 마스터 서버 기본 포트/헬스 체크 값을 정의합니다.
- `SLACK_*`, `TELEGRAM_*` 토큰을 미리 입력해두면 `python -m bridge` 실행 시 자동으로 로드됩니다.
- `REMOTE_DEFAULT_TAGS` 는 대시보드 목업에 표시되는 기본 태그 목록을 결정합니다.

## 웹 대시보드 기능

- 홈 화면에는 실시간 WebSocket 노드 목록, 전체 브로드캐스트 입력창, Slack/Telegram 토큰을 포함한 브릿지 설정 폼이 제공됩니다.
- 설정 폼은 입력값을 `/api/config` 엔드포인트에 저장한 뒤 즉시 대시보드에 반영하며, 저장 시각과 메모를 헤더에서 확인할 수 있습니다.
- "원격 노드 관리" 섹션은 실제 연결을 유도하기 위한 목업으로, 서버가 보관 중인 원격 Codex 노드 메타데이터를 추가/삭제/상태 변경하는 UI를 제공합니다. Slack/Telegram 명령과 매핑하기 전에 전체 플로우를 시험해볼 수 있습니다.
- "작업 실행" 섹션에서 프롬프트, 대상 노드, GitHub 레포지토리를 지정해 Codex 작업을 생성하고 상태/결과 로그를 확인할 수 있습니다.
- 선택한 작업의 실시간 실행 로그를 조회할 수 있는 상세 패널과 `/api/jobs/{id}/logs` REST API가 제공됩니다.

## 프런트엔드 개발

- 프로젝트 루트는 모노레포 형태로 구성되어 있으며, `frontend` 디렉터리에는 Vite 기반 React 앱이 포함되어 있습니다.
- 개발 서버 실행

  ```bash
  cd frontend
  npm install          # 최초 1회
  npm run dev
  ```

  기본적으로 `http://localhost:5173`에서 UI를 확인할 수 있으며, Vite 설정에 따라 `/api/*` 요청은 자동으로 `http://127.0.0.1:8765`(파이썬 마스터 서버)로 프록시됩니다.

- 프로덕션 번들 생성

  ```bash
  npm run build
  ```

  빌드 결과는 `frontend/dist` 에 생성되며, 마스터 서버는 해당 디렉터리를 자동으로 서빙합니다. 번들이 존재하지 않을 경우 브라우저에는 빌드 안내용 플레이스홀더가 표시됩니다.

## 메신저 브릿지 실행 가이드

`bridge` 패키지는 Slack 및 Telegram과 Codex 마스터 간의 양방향 메시지 중계를 담당합니다. 토큰이 준비되면 환경 변수를 설정한 뒤 `python -m bridge`로 간단히 실행할 수 있도록 구성했습니다.

### 1. 환경 변수 준비

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `SLACK_BOT_TOKEN` | 선택 | Slack 봇 토큰(`xoxb-` 접두)가 있다면 Slack 브릿지를 활성화합니다. |
| `SLACK_DEFAULT_CHANNEL` | 선택 | Slack 응답을 전달할 기본 채널 ID(`C...`, `D...`). 응답 메시지에 대상 채널 정보가 없을 때 사용됩니다. |
| `TELEGRAM_BOT_TOKEN` | 선택 | Telegram Bot API 토큰을 설정하면 Telegram 브릿지가 활성화됩니다. |
| `TELEGRAM_PARSE_MODE` | 선택 | Telegram 응답에 적용할 `parse_mode` (`MarkdownV2`, `HTML` 등). |
| `TELEGRAM_ALLOWED_CHATS` | 선택 | 숫자 chat_id를 콤마로 나열하면 해당 채팅만 허용합니다. 미설정 시 모든 채팅 허용. |
| `MASTER_HOST` / `MASTER_PORT` | 선택 | 마스터 서버 위치(기본값 `127.0.0.1:8765`). 원격 마스터에 연결할 때만 수정합니다. |

`.env` 파일을 사용하는 경우 위 표의 키 이름을 그대로 추가하면 됩니다. 값이 비어 있으면 브릿지는 해당 플랫폼을 비활성화합니다.

### 2. 실행

```bash
uv run python -m bridge
```

- `--slack-bot-token`, `--telegram-bot-token` 등 CLI 인자를 직접 지정해도 되며, 지정 시 동일한 이름의 환경 변수는 덮어씌워집니다.
- 둘 중 하나라도 토큰이 주어지면 해당 브릿지가 활성화되며, 토큰이 없는 플랫폼은 자동으로 비활성화됩니다.

### 3. 메시지 페이로드 규칙

브릿지는 마스터와 다음과 같은 JSON 스키마로 메시지를 주고받습니다. (마스터는 문자열을 그대로 브로드캐스트하므로, 노드 측에서 JSON 문자열을 직접 생성/파싱해야 합니다.)

**플랫폼 → 마스터 명령 예시**

```json
{
  "type": "command",
  "source": {
    "platform": "slack",
    "channel": "C12345678",
    "thread_ts": "1729331225.123456",
    "user": "U12345678",
    "user_name": "june"
  },
  "text": "deploy staging"
}
```

**노드 → 브릿지 응답 예시**

```json
{
  "type": "response",
  "target": {
    "platform": "telegram",
    "chat_id": 123456789,
    "message_id": 42
  },
  "text": "✅ 스테이징 배포 완료"
}
```

- `target.platform`이 `slack`이면 `channel`과 `thread_ts`(또는 `ts`)를 포함해야 하며, `telegram`이면 `chat_id` 및 필요 시 `message_thread_id`/`message_id` 를 활용합니다.
- 응답 JSON의 `broadcast` 필드를 `true`로 설정하면 Slack 스레드 답장이 채널 전체에 브로드캐스트됩니다.
- Slack/Telegram 원본 이벤트 전문은 각각 `raw_event`, `raw_update` 필드로 전달되므로, 필요하다면 노드에서 추가 정보를 참고할 수 있습니다.

### 4. 에러 및 재연결

- 마스터 연결이 끊길 경우 각 브릿지는 5초 간격으로 자동 재접속을 시도합니다.
- Telegram long polling과 Slack RTM WebSocket 역시 예외 시 백오프 후 재시도하며, 자세한 오류는 로그에서 확인할 수 있습니다.
