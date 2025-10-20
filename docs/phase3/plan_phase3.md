# Phase 3 구현 우선순위 계획

## 1. Job 로그/상세 뷰어
- 백엔드: `/api/jobs/{job_id}/logs` 엔드포인트(최근 N줄 or 전체), SSE/WebSocket 스트리밍 검토
- 프런트: Job 상세 패널/모달, 실시간 로그 업데이트, 상태 배지 표시
- 노드: `job.log` 이벤트를 기반으로 마스터에 저장/버퍼 전략 결정 (현재는 로그 이벤트만 있음)

## 2. GitHub OAuth & 리포지토리 선택 UX
- 사용자별 OAuth 토큰 저장 구조 설계 (DB 테이블 / encrypted storage)
- `/api/github/repos` 엔드포인트, 프런트 UI에서 검색/선택 지원
- Job 생성 시 OAuth 토큰 -> 노드 전달 방식 정의 (예: 작업 메타데이터에 임시 토큰 포함)

## 3. Slack/Telegram ↔ Job 생성 연동
- 명령 템플릿 정의 (`/deploy staging`, `/run tests repo=...` 등)
- 브릿지에서 수신한 명령을 `/api/jobs` 호출로 매핑 (사용자 컨텍스트, GitHub 토큰 필요)
- 결과/알림: Job 완료 시 브릿지 통해 원래 채널로 메시지 반환

## 우선순위 제안
1. Job 로그 뷰어 (Phase 1/2 결과 확인을 위한 최우선)
2. GitHub OAuth (레포 셀렉션을 자동화, Slack 연동 전 필수)
3. Slack/Telegram 연동 (OAuth 기반 레포 선택 가능해진 뒤 진행)

## 준비 작업
- DB에 사용자 테이블 추가, OAuth 토큰 저장 및 암호화 전략 결정
- Job 로그 저장 모델 확정 (SQLite blob, 파일 경로, 외부 로그 시스템 등)
- 브릿지 명령 파서 스펙 초안 작성
