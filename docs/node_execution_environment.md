# 노드 실행 환경 요구사항 초안

## 디렉터리 구조
- 기본 루트: `/var/codernetes-jobs/<job-id>/`
- 레포지토리별 경로: `<job-root>/<repo-name>` (Git 클론)
- 산출물/로그: `<job-root>/logs/` (표준 로그 파일), `<job-root>/artifacts/`
- `node/client.py` 실행 시 `--workdir-root`로 기본 경로를 지정하며, `--cleanup-delay` 옵션으로 작업 완료 후 자동 정리(초 단위)를 설정할 수 있습니다. `--preserve-workdir`를 사용하면 디렉터리를 유지합니다.

## 권한/격리
- 각 Job은 전용 OS 사용자(`codernetes-job-<id>`) 또는 컨테이너에서 실행하여 권한 격리
- 네트워크 액세스는 최소화 (필요 시 allow-list)
- GitHub credential은 환경 변수/credential helper로 주입 후 작업 종료 시 파기
- 노드 클라이언트는 `--github-token-file` 또는 `--github-token` 옵션을 통해 토큰을 읽어 HTTPS clone 시 자동으로 주입하며, 로그에는 마스킹된 URL만 출력합니다.

## 실행 순서
1. 작업 디렉터리 생성 (`mkdir -p /var/codernetes-jobs/<job-id>`)
2. 지정된 레포지토리 목록을 HTTPS+토큰으로 클론
3. 필요 시 프롬프트/환경 변수로 초기화 스크립트 실행
4. Codernetes/LLM 실행 (예: `codernetes run --prompt prompt.txt`)
5. 결과/로그를 파일로 저장 후 마스터에 `job.status` 이벤트 전송
6. 지정 TTL 경과 후 작업 디렉터리 삭제 (또는 명시적 정리 명령 지원)

## 환경 변수/비밀 관리
- OpenAI API 키, GitHub 토큰 등은 노드 구성 시 전달/암호화 저장
- Job 요청 시 `metadata.env`에 필요한 키만 명시적으로 전달 (JSON 암호화 고려)
- Secret 값은 작업 종료 후 무효화/삭제

## 모니터링/리소스 제한
- CPU/RAM/GPU 제한: cgroup 혹은 컨테이너 런타임 활용
- Job 실행 시간 타임아웃 (예: 30분 기본) 초과 시 자동 중단 + 실패 처리
- `--cleanup-delay` 옵션으로 디렉터리 정리 시간을 제어할 수 있으며, 기본값 0초는 완료 직후 삭제를 시도합니다.
- 로컬 로그 및 시스템 메트릭은 마스터/관측 도구(Prometheus, Loki 등)에 노출

## 오류 처리
- Git clone 실패, 의존성 설치 실패 등은 즉시 `job.status` with `failed` + `error_message`
- 노드 비정상 종료 시 마스터가 Job을 `failed`로 마킹하고 재큐잉 옵션 고려
