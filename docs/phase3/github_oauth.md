# GitHub OAuth 설계 초안

## 목적
- 사용자별 GitHub 액세스 토큰을 저장해 Job 생성 시 레포지토리 목록을 자동 제공
- Slack/Telegram 명령 실행 시 사용자 컨텍스트로 레포 접근 권한을 위임

## 현재 구현 (Placeholder)
- `POST /api/github/token` : user_id와 access_token 등을 받아 SQLite `user_tokens` 테이블에 저장
- `GET /api/github/repos?user_id=` : 현재는 토큰 존재 여부만 확인 후 placeholder 레포 목록 반환
- 토큰은 암호화 없이 저장되므로 추후 KMS/환경변수 기반 암호화 필요

## 추후 계획
1. GitHub OAuth App 등록 → authorization code flow 구현 (redirect URI, state 검증)
2. 토큰 암호화 저장 + refresh token, 만료 처리
3. GitHub REST API(`GET /user/repos`) 호출 → 필요한 필드만 프런트에 반환
4. Job 생성 시 선택된 레포 목록을 작업 메타데이터에 포함하고 노드에 전달
5. Slack/Telegram 명령은 사용자 식별 후 동일 토큰으로 `/api/jobs` 호출

## TODO
- user 테이블/인증 체계 설계 (현재는 user_id 문자열만 사용)
- 암호화 라이브러리/비밀 저장 전략 결정
- 실제 GitHub API 통신 구현 및 에러 처리
