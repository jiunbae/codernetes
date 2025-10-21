# Slack/Telegram 명령 → Job 생성 설계

## 목표
- 메신저 명령을 Codernetes Job 생성 흐름에 연결해 원격 명령 실행 자동화
- 사용자 컨텍스트 기반으로 GitHub 토큰/레포 권한을 활용

## 1. 명령 포맷 초안
| 플랫폼 | 예시 명령 | 설명 |
| --- | --- | --- |
| Slack | `/codernetes run repo=https://github.com/org/app prompt="run tests" tags=staging` | Slash command 또는 봇 멘션 기반 |
| Telegram | `run tests repo https://github.com/org/app tags staging` | 봇 DM/그룹 명령 |

- 공통 파라미터: `prompt`, `repos`, `tags`, `target`(노드)
- 선택 파라미터: `branch`, `subdir`, `timeout`

## 2. 브릿지 → 마스터 API 흐름
1. 브릿지가 명령을 파싱해 `bridge/platform_command` 이벤트를 생성
2. 마스터의 `/api/jobs` 호출 (origin: `slack`/`telegram`, metadata에 채널/사용자 정보 포함)
3. 응답을 브릿지가 사용자에게 전달 (job_id 및 초기상태 알림)
4. Job 완료 시 브릿지가 `job.status` 이벤트를 감지해 완료 메시지/로그 링크 전송

## 3. 사용자 식별/권한
- Slack: `team_id + user_id` 를 user_id로 매핑 (ex. `slack:T123:U456`)
- Telegram: 사용자 ID 사용 (ex. `telegram:123456789`)
- 마스터는 `user_tokens`에서 GitHub 토큰을 조회하고, 존재하지 않으면 "토큰 등록 필요" 답변

## 4. 구현 단계
1. 브릿지에 명령 파서 추가 (Slack slash command, Telegram DM)
2. 마스터에 `/api/commands/preview` (optional) 및 `/api/jobs` 호출 래퍼 작성
3. Job 생성 후 즉시 Slack/Telegram으로 job_id, 상태 대기 안내 메시지 전송
4. `job.status` 알림 처리: 성공/실패 메시지 + 로그 링크 (프런트 `/jobs/:id` 페이지 또는 `/api/jobs/{id}/logs` 링크)

## 5. 보안/검증
- 명령은 인증된 채널(등록된 workspace/chat)에서만 허용
- 사용자별 권한(Role) 모델 추가 고려 (Phase 5 예정)
- 민감 정보(토큰, 로그) 공유 시 개인 DM으로 제한

## TODO
- 브릿지에서 Slack/Telegram API 키 저장 방식 확정
- Slash command vs. 앱 멘션 결정 및 이벤트 구독 구성 파일 정리
- 마스터에 완료 알림을 위해 WebSocket 또는 webhook 기반 알림 채널 구현
