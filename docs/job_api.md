# Job API 초안

## REST Endpoints

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/api/jobs` | 작업 목록 조회 (`?status=` 필터 지원) |
| `GET` | `/api/jobs/{job_id}` | 개별 작업 상세 조회 |
| `POST` | `/api/jobs` | 새 작업 생성 |
| `POST` | `/api/jobs/{job_id}/status` | 작업 상태 업데이트 (노드/브릿지에서 사용) |
| `GET` | `/api/nodes` | 등록된 노드 메타데이터 조회 |

### Create Job Request

```jsonc
{
  "prompt": "run tests",
  "target_node_id": "node-123", // optional
  "requested_tags": ["staging", "gpu"],
  "repositories": [
    {"url": "https://github.com/org/repo1", "branch": "main"},
    {"url": "https://github.com/org/repo2", "subdirectory": "services/api"}
  ],
  "origin": "dashboard" // optional metadata
}
```

- `target_node_id`가 지정되면 즉시 `QUEUED`, 미지정 시 `PENDING` 상태로 생성됩니다.
- 브릿지/슬랙/텔레그램 요청은 `origin` 필드를 통해 호출 출처를 표기합니다.

### Job Representation

```jsonc
{
  "job_id": "uuid",
  "prompt": "...",
  "status": "pending|queued|running|succeeded|failed|cancelled",
  "target_node_id": "node-123",
  "requested_tags": ["staging"],
  "repositories": [
    {"url": "https://github.com/org/repo", "branch": "main", "subdirectory": null}
  ],
  "metadata": {"origin": "dashboard"},
  "log_path": "/var/logs/job-uuid.log",
  "result_summary": "Summary text",
  "error_message": null,
  "created_at": "2025-10-20T12:34:56Z",
  "finished_at": null
}
```

### Update Job Status Request

```jsonc
{
  "status": "running",
  "log_path": "/var/codex-job-uuid/output.log",
  "result_summary": "optional summary",
  "error_message": null
}
```

상태는 `running`, `succeeded`, `failed`, `cancelled` 등을 지원하며, 완료 상태 업데이트 시 자동으로 `finished_at`가 기록됩니다.

## 마스터 ↔ 노드 메시지 스키마 초안

### 작업 할당 (Master → Node)

```jsonc
{
  "type": "job.assign",
  "job_id": "uuid",
  "prompt": "...",
