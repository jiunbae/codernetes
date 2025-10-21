import { useEffect, useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import './App.css'
import {
  broadcastMessage,
  createJob,
  createRemote,
  fetchConfig,
  fetchJobs,
  fetchJobLogs,
  fetchRegisteredNodes,
  fetchRemotes,
  fetchStatus,
  saveGithubToken,
  fetchGithubRepos,
  removeRemote,
  sendToClient,
  updateConfig,
  updateRemote,
} from './api'
import type {
  ClientInfo,
  ConfigFormState,
  ConfigPayload,
  Feedback,
  Job,
  JobLogEntry,
  GithubRepo,
  JobFormState,
  RemoteFormState,
  RemoteNode,
  RegisteredNode,
  StatusResponse,
} from './types'

const LOG_LEVEL_OPTIONS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const

const INITIAL_CONFIG_FORM: ConfigFormState = {
  master_host: '',
  master_port: '',
  master_http_host: '',
  master_http_port: '',
  master_health_interval: '',
  master_health_timeout: '',
  bridge_log_level: 'INFO',
  bridge_remote_default_tags: '',
  bridge_autostart: false,
  slack_bot_token: '',
  slack_default_channel: '',
  telegram_bot_token: '',
  telegram_parse_mode: '',
  telegram_allowed_chats: '',
  notes: '',
}

const INITIAL_REMOTE_FORM: RemoteFormState = {
  name: '',
  host: '',
  port: '9000',
  tags: '',
  notes: '',
}

const INITIAL_JOB_FORM: JobFormState = {
  prompt: '',
  targetNodeId: '',
  requestedTags: '',
  repositoryUrls: '',
}

function formatDate(value?: string | null): string {
  if (!value) return '정보 없음'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

function formatLastSeen(value?: string | null): string {
  if (!value) return '최근 활동 정보 없음'
  return formatDate(value)
}

const STATUS_LABELS: Record<string, string> = {
  online: '온라인',
  unresponsive: '응답 없음',
  disconnected: '연결 끊김',
}

const STATUS_CLASSES: Record<string, string> = {
  online: 'status-badge online',
  unresponsive: 'status-badge unresponsive',
  disconnected: 'status-badge disconnected',
}

const REMOTE_STATUS_LABELS: Record<string, string> = {
  online: '온라인',
  offline: '오프라인',
  maintenance: '점검 중',
  busy: '작업 중',
  provisioning: '프로비저닝',
}

const REMOTE_STATUS_CLASSES: Record<string, string> = {
  online: 'badge success',
  offline: 'badge danger',
  maintenance: 'badge warning',
  busy: 'badge info',
  provisioning: 'badge subtle',
}

const JOB_STATUS_LABELS: Record<string, string> = {
  pending: '대기',
  queued: '큐 대기',
  running: '실행 중',
  succeeded: '성공',
  failed: '실패',
  cancelled: '취소',
}

const JOB_STATUS_CLASSES: Record<string, string> = {
  pending: 'badge subtle',
  queued: 'badge info',
  running: 'badge info',
  succeeded: 'badge success',
  failed: 'badge danger',
  cancelled: 'badge warning',
}

function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)

  const [broadcastText, setBroadcastText] = useState('')
  const [broadcastFeedback, setBroadcastFeedback] = useState<Feedback | null>(null)
  const [broadcastLoading, setBroadcastLoading] = useState(false)

  const [configPayload, setConfigPayload] = useState<ConfigPayload | null>(null)
  const [configForm, setConfigForm] = useState<ConfigFormState>(INITIAL_CONFIG_FORM)
  const [configFeedback, setConfigFeedback] = useState<Feedback | null>(null)
  const [configLoading, setConfigLoading] = useState(false)

  const [remotes, setRemotes] = useState<RemoteNode[]>([])
  const [remotesError, setRemotesError] = useState<string | null>(null)

  const [remoteForm, setRemoteForm] = useState<RemoteFormState>(INITIAL_REMOTE_FORM)
  const [remoteFeedback, setRemoteFeedback] = useState<Feedback | null>(null)
  const [remoteLoading, setRemoteLoading] = useState(false)

  const [jobs, setJobs] = useState<Job[]>([])
  const [jobsError, setJobsError] = useState<string | null>(null)
  const [jobFeedback, setJobFeedback] = useState<Feedback | null>(null)
  const [jobLoading, setJobLoading] = useState(false)
  const [jobForm, setJobForm] = useState<JobFormState>(INITIAL_JOB_FORM)

  const [registeredNodes, setRegisteredNodes] = useState<RegisteredNode[]>([])
  const [nodesError, setNodesError] = useState<string | null>(null)

  const [githubRepos, setGithubRepos] = useState<GithubRepo[]>([])
  const [githubUserId, setGithubUserId] = useState('')
  const [githubAccessToken, setGithubAccessToken] = useState('')
  const [githubRefreshToken, setGithubRefreshToken] = useState('')
  const [githubExpiresAt, setGithubExpiresAt] = useState('')
  const [githubFeedback, setGithubFeedback] = useState<Feedback | null>(null)
  const [githubLoading, setGithubLoading] = useState(false)

  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [jobLogs, setJobLogs] = useState<JobLogEntry[]>([])
  const [jobLogsError, setJobLogsError] = useState<string | null>(null)
  const [jobLogsLoading, setJobLogsLoading] = useState(false)
  const [jobLogsAfter, setJobLogsAfter] = useState<number | null>(null)

  const [clientMessages, setClientMessages] = useState<Record<string, string>>({})
  const [clientFeedbacks, setClientFeedbacks] = useState<Record<string, Feedback>>({})
  const [clientLoading, setClientLoading] = useState<Record<string, boolean>>({})

  const connectedCount = status?.connected_clients ?? 0
  const lastUpdated = configPayload?.updated_at ?? null
  const notesPreview = configPayload?.notes?.trim() ?? ''

  const clients = useMemo(() => status?.clients ?? [], [status])
  const sortedJobs = useMemo(
    () =>
      [...jobs].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [jobs],
  )

  const selectedJob = useMemo(() => jobs.find((job) => job.job_id === selectedJobId) ?? null, [jobs, selectedJobId])

  useEffect(() => {
    if (selectedJobId && !jobs.some((job) => job.job_id === selectedJobId)) {
      setSelectedJobId(null)
    }
  }, [jobs, selectedJobId])

  useEffect(() => {
    loadStatus()
    loadConfig()
    loadRemotes()
    loadJobs()
    loadRegisteredNodes()

    const statusTimer = window.setInterval(loadStatus, 5000)
    const remotesTimer = window.setInterval(loadRemotes, 15000)
    const configTimer = window.setInterval(loadConfig, 60000)
    const jobsTimer = window.setInterval(loadJobs, 10000)
    const nodesTimer = window.setInterval(loadRegisteredNodes, 30000)

    return () => {
      window.clearInterval(statusTimer)
      window.clearInterval(remotesTimer)
      window.clearInterval(configTimer)
      window.clearInterval(jobsTimer)
      window.clearInterval(nodesTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!configPayload) return
    setConfigForm({
      master_host: configPayload.master.host ?? '',
      master_port: configPayload.master.port?.toString() ?? '',
      master_http_host: configPayload.master.http_host ?? '',
      master_http_port: configPayload.master.http_port?.toString() ?? '',
      master_health_interval: configPayload.master.health_interval?.toString() ?? '',
      master_health_timeout: configPayload.master.health_timeout?.toString() ?? '',
      bridge_log_level: configPayload.bridge.log_level ?? 'INFO',
      bridge_remote_default_tags:
        configPayload.bridge.remote_default_tags_csv ??
        (configPayload.bridge.remote_default_tags ?? []).join(', '),
      bridge_autostart: Boolean(configPayload.bridge.autostart),
      slack_bot_token: configPayload.slack.bot_token ?? '',
      slack_default_channel: configPayload.slack.default_channel ?? '',
      telegram_bot_token: configPayload.telegram.bot_token ?? '',
      telegram_parse_mode: configPayload.telegram.parse_mode ?? '',
      telegram_allowed_chats: configPayload.telegram.allowed_chats ?? '',
      notes: configPayload.notes ?? '',
    })
  }, [configPayload])

  useEffect(() => {
    const activeIds = new Set(clients.map((client) => client.id))
    setClientMessages((prev) => {
      const next = { ...prev }
      Object.keys(next).forEach((key) => {
        if (!activeIds.has(key)) {
          delete next[key]
        }
      })
      return next
    })
    setClientFeedbacks((prev) => {
      const next = { ...prev }
      Object.keys(next).forEach((key) => {
        if (!activeIds.has(key)) {
          delete next[key]
        }
      })
      return next
    })
    setClientLoading((prev) => {
      const next = { ...prev }
      Object.keys(next).forEach((key) => {
        if (!activeIds.has(key)) {
          delete next[key]
        }
      })
      return next
    })
  }, [clients])

  async function loadStatus() {
    try {
      const data = await fetchStatus()
      setStatus(data)
      setStatusError(null)
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : '상태를 불러오지 못했습니다.')
    }
  }

  async function loadConfig() {
    try {
      const data = await fetchConfig()
      setConfigPayload(data.config)
      setConfigFeedback(null)
    } catch (error) {
      setConfigFeedback({
        type: 'error',
        message: error instanceof Error ? error.message : '설정을 불러오지 못했습니다.',
      })
    }
  }

  async function loadRemotes() {
    try {
      const data = await fetchRemotes()
      setRemotes(data.remotes)
      setRemotesError(null)
    } catch (error) {
      setRemotesError(error instanceof Error ? error.message : '원격 노드 목록을 불러오지 못했습니다.')
    }
  }

  async function loadJobs() {
    try {
      const data = await fetchJobs()
      setJobs(data.jobs)
      setJobsError(null)
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : '작업 목록을 불러오지 못했습니다.')
    }
  }

  async function loadJobLogs(options?: { reset?: boolean }) {
    if (!selectedJobId) return
    const reset = options?.reset ?? false
    const after = reset ? undefined : jobLogsAfter ?? undefined
    setJobLogsLoading(true)
    try {
      const data = await fetchJobLogs(selectedJobId, { after, limit: 200 })
      if (reset) {
        setJobLogs([...data.logs].sort((a, b) => a.seq - b.seq))
      } else {
        setJobLogs((prev) => {
          const merged = [...prev]
          for (const log of data.logs) {
            if (!merged.some((item) => item.seq === log.seq)) {
              merged.push(log)
            }
          }
          return merged.sort((a, b) => a.seq - b.seq)
        })
      }
      if (data.logs.length > 0) {
        const latest = data.logs[data.logs.length - 1]
        setJobLogsAfter(latest.seq)
      }
      setJobLogsError(null)
    } catch (error) {
      setJobLogsError(error instanceof Error ? error.message : '로그를 불러오지 못했습니다.')
      if (reset) {
        setJobLogs([])
        setJobLogsAfter(null)
      }
    } finally {
      setJobLogsLoading(false)
    }
  }

  useEffect(() => {
    if (!selectedJobId) {
      setJobLogs([])
      setJobLogsAfter(null)
      setJobLogsError(null)
      return
    }
    setJobLogs([])
    setJobLogsAfter(null)
    setJobLogsError(null)
    loadJobLogs({ reset: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedJobId])

  useEffect(() => {
    if (!selectedJobId) return
    const status = selectedJob?.status
    if (!status) return
    if (['running', 'queued', 'pending'].includes(status)) {
      const timer = window.setInterval(() => {
        loadJobLogs({ reset: false })
      }, 3000)
      return () => window.clearInterval(timer)
    }
    loadJobLogs({ reset: false })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedJobId, selectedJob?.status])

  async function loadRegisteredNodes() {
    try {
      const data = await fetchRegisteredNodes()
      setRegisteredNodes(data.nodes)
      setNodesError(null)
    } catch (error) {
      setNodesError(error instanceof Error ? error.message : '등록된 노드 정보를 불러오지 못했습니다.')
    }
  }

  function handleBroadcastSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!broadcastText.trim()) {
      setBroadcastFeedback({ type: 'error', message: '메시지를 입력하세요.' })
      return
    }
    setBroadcastLoading(true)
    setBroadcastFeedback(null)

    broadcastMessage(broadcastText.trim())
      .then(async () => {
        setBroadcastFeedback({ type: 'success', message: '모든 노드에 전송했습니다.' })
        setBroadcastText('')
        await loadStatus()
      })
      .catch((error) => {
        setBroadcastFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '전송에 실패했습니다.',
        })
      })
      .finally(() => setBroadcastLoading(false))
  }

  function handleConfigChange(event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    const { name, value } = event.target
    const nextValue =
      event.target instanceof HTMLInputElement && event.target.type === 'checkbox'
        ? event.target.checked
        : value

    setConfigForm((prev) => ({
      ...prev,
      [name]: nextValue,
    }))
  }

  function handleConfigSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setConfigLoading(true)
    setConfigFeedback(null)

    const payload = {
      master: {
        host: configForm.master_host,
        port: configForm.master_port || undefined,
        http_host: configForm.master_http_host,
        http_port: configForm.master_http_port || undefined,
        health_interval: configForm.master_health_interval || undefined,
        health_timeout: configForm.master_health_timeout || undefined,
      },
      bridge: {
        log_level: configForm.bridge_log_level,
        autostart: configForm.bridge_autostart,
        remote_default_tags: configForm.bridge_remote_default_tags,
      },
      slack: {
        bot_token: configForm.slack_bot_token,
        default_channel: configForm.slack_default_channel,
      },
      telegram: {
        bot_token: configForm.telegram_bot_token,
        parse_mode: configForm.telegram_parse_mode,
        allowed_chats: configForm.telegram_allowed_chats,
      },
      notes: configForm.notes,
    }

    updateConfig(payload)
      .then((data) => {
        setConfigPayload(data.config)
        setConfigFeedback({ type: 'success', message: '설정을 저장했습니다.' })
      })
      .catch((error) => {
        setConfigFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '설정 저장에 실패했습니다.',
        })
      })
      .finally(() => setConfigLoading(false))
  }

  function handleRemoteChange(event: ChangeEvent<HTMLInputElement>) {
    const { name, value } = event.target
    setRemoteForm((prev) => ({
      ...prev,
      [name]: value,
    }))
  }

  function handleRemoteSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!remoteForm.name.trim() || !remoteForm.host.trim()) {
      setRemoteFeedback({ type: 'error', message: '이름과 호스트를 입력하세요.' })
      return
    }
    setRemoteLoading(true)
    setRemoteFeedback(null)

    createRemote({
      name: remoteForm.name.trim(),
      host: remoteForm.host.trim(),
      port: remoteForm.port,
      tags: remoteForm.tags,
      notes: remoteForm.notes,
    })
      .then((data) => {
        setRemotes((prev) => [...prev, data.remote])
        setRemoteFeedback({ type: 'success', message: '원격 노드를 추가했습니다.' })
        setRemoteForm(INITIAL_REMOTE_FORM)
      })
      .catch((error) => {
        setRemoteFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '등록에 실패했습니다.',
        })
      })
      .finally(() => setRemoteLoading(false))
  }

  function handleJobFormChange(event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    const { name, value } = event.target
    setJobForm((prev) => ({
      ...prev,
      [name]: value,
    }))
  }

  function handleJobSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedPrompt = jobForm.prompt.trim()
    if (!trimmedPrompt) {
      setJobFeedback({ type: 'error', message: '프롬프트를 입력하세요.' })
      return
    }

    const repositories = jobForm.repositoryUrls
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .map((url) => ({ url }))

    const requestedTags = jobForm.requestedTags
      .split(',')
      .map((tag) => tag.trim())
      .filter((tag) => tag.length > 0)

    const payload = {
      prompt: trimmedPrompt,
      target_node_id: jobForm.targetNodeId || undefined,
      requested_tags: requestedTags,
      repositories,
      origin: 'dashboard',
    }

    setJobLoading(true)
    setJobFeedback(null)

    createJob(payload)
      .then(() => {
        setJobFeedback({ type: 'success', message: '작업을 생성했습니다.' })
        setJobForm(INITIAL_JOB_FORM)
        loadJobs()
      })
      .catch((error) => {
        setJobFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '작업 생성에 실패했습니다.',
        })
      })
      .finally(() => setJobLoading(false))
  }

  function handleGithubSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!githubUserId.trim() || !githubAccessToken.trim()) {
      setGithubFeedback({ type: 'error', message: 'user_id와 access_token을 입력하세요.' })
      return
    }
    setGithubLoading(true)
    setGithubFeedback(null)
    saveGithubToken({
      user_id: githubUserId.trim(),
      access_token: githubAccessToken.trim(),
      refresh_token: githubRefreshToken.trim() || undefined,
      expires_at: githubExpiresAt.trim() || undefined,
    })
      .then(() => {
        setGithubFeedback({ type: 'success', message: 'GitHub 토큰을 저장했습니다.' })
      })
      .catch((error) => {
        setGithubFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '토큰 저장에 실패했습니다.',
        })
      })
      .finally(() => setGithubLoading(false))
  }

  function handleFetchGithubRepos() {
    if (!githubUserId.trim()) {
      setGithubFeedback({ type: 'error', message: 'user_id를 입력하세요.' })
      return
    }
    setGithubLoading(true)
    setGithubFeedback(null)
    fetchGithubRepos(githubUserId.trim())
      .then((data) => {
        setGithubRepos(data.repos)
        setGithubFeedback({ type: 'success', message: `${data.repos.length}개 레포를 불러왔습니다.` })
      })
      .catch((error) => {
        setGithubFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '레포 목록을 불러오지 못했습니다.',
        })
        setGithubRepos([])
      })
      .finally(() => setGithubLoading(false))
  }

  function handleAddRepository(url: string) {
    setJobForm((prev) => {
      const existing = prev.repositoryUrls.trim()
      const entries = existing ? existing.split(/\r?\n/) : []
      if (entries.includes(url)) {
        return prev
      }
      const updated = existing ? `${existing}\n${url}` : url
      return { ...prev, repositoryUrls: updated }
    })
  }

  function handleSelectJob(jobId: string) {
    setSelectedJobId((prev) => (prev === jobId ? prev : jobId))
  }

  function handleRemoteAction(remoteId: string, action: string) {
    setRemoteFeedback(null)
    updateRemote(remoteId, { action })
      .then((data) => {
        setRemotes((prev) => prev.map((remote) => (remote.id === remoteId ? data.remote : remote)))
        setRemoteFeedback({ type: 'success', message: '상태를 업데이트했습니다.' })
      })
      .catch((error) => {
        setRemoteFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '상태 변경에 실패했습니다.',
        })
      })
  }

  function handleRemoteDelete(remoteId: string) {
    setRemoteFeedback(null)
    removeRemote(remoteId)
      .then(() => {
        setRemotes((prev) => prev.filter((remote) => remote.id !== remoteId))
        setRemoteFeedback({ type: 'success', message: '원격 노드를 제거했습니다.' })
      })
      .catch((error) => {
        setRemoteFeedback({
          type: 'error',
          message: error instanceof Error ? error.message : '삭제에 실패했습니다.',
        })
      })
  }

  function handleClientInput(clientId: string, value: string) {
    setClientMessages((prev) => ({ ...prev, [clientId]: value }))
  }

  function handleSendToClient(client: ClientInfo) {
    const message = (clientMessages[client.id] || '').trim()
    if (!message) {
      setClientFeedbacks((prev) => ({
        ...prev,
        [client.id]: { type: 'error', message: '메시지를 입력하세요.' },
      }))
      return
    }

    setClientLoading((prev) => ({ ...prev, [client.id]: true }))
    setClientFeedbacks((prev) => ({ ...prev, [client.id]: { type: 'success', message: '' } }))

    sendToClient(client.id, message)
      .then(() => {
        setClientFeedbacks((prev) => ({
          ...prev,
          [client.id]: { type: 'success', message: '전송되었습니다.' },
        }))
        setClientMessages((prev) => ({ ...prev, [client.id]: '' }))
      })
      .catch((error) => {
        setClientFeedbacks((prev) => ({
          ...prev,
          [client.id]: {
            type: 'error',
            message: error instanceof Error ? error.message : '전송 실패',
          },
        }))
      })
      .finally(() => {
        setClientLoading((prev) => ({ ...prev, [client.id]: false }))
      })
  }

  return (
    <div className="app-root">
      <main className="layout">
        <header className="page-header">
          <div>
            <h1>Codernetes 마스터 제어판</h1>
            <p>Slack/Telegram 브릿지와 원격 Codernetes 노드를 한 곳에서 관리하세요.</p>
          </div>
          <div className="header-meta">
            <div>
              <span className="small-text">설정 갱신</span>
              <span id="config-updated-at" className="meta-value">
                {formatDate(lastUpdated)}
              </span>
            </div>
            <div>
              <span className="small-text">메모</span>
              <span id="config-notes-preview" className="meta-note">
                {notesPreview || '메모 없음'}
              </span>
            </div>
          </div>
        </header>

        <section className="grid two">
          <section className="card">
          <div className="card-heading">
            <h2>연결된 노드</h2>
            <span className="badge info" id="connected-count">
                {connectedCount}
              </span>
            </div>
            <p className="description">현재 WebSocket으로 연결된 노드 목록입니다.</p>
            {statusError && <div className="form-message error">{statusError}</div>}
            <ul id="client-list" className="client-list">
              {clients.length === 0 ? (
                <li className="empty">연결된 노드가 없습니다.</li>
              ) : (
                clients.map((client) => (
                  <li key={client.id} className="client-item" data-client-id={client.id}>
                    <div className="client-meta">
                      <span>노드 ID</span>
                      <code className="client-id">{client.id}</code>
                      <span className={STATUS_CLASSES[client.status] ?? 'status-badge'}>
                        {STATUS_LABELS[client.status] ?? client.status}
                      </span>
                      <span className="last-seen">최근 활동: {formatLastSeen(client.last_seen)}</span>
                    </div>
                    <div className="client-actions">
                      <input
                        type="text"
                        placeholder="이 노드에 전송할 메시지"
                        value={clientMessages[client.id] ?? ''}
                        onChange={(event) => handleClientInput(client.id, event.target.value)}
                      />
                      <button
                        type="button"
                        onClick={() => handleSendToClient(client)}
                        disabled={clientLoading[client.id]}
                      >
                        전송
                      </button>
                    </div>
                    {clientFeedbacks[client.id] && (
                      <div className={`message ${clientFeedbacks[client.id].type}`}>
                        {clientFeedbacks[client.id].message}
                      </div>
                    )}
                  </li>
                ))
              )}
            </ul>
          </section>

          <section className="card">
          <div className="card-heading">
            <h2>메시지 브로드캐스트</h2>
              <span className="badge subtle">전체 노드</span>
            </div>
            <p className="description">전체 노드에 공지나 긴급 명령을 즉시 전송합니다.</p>
            <form id="broadcast-form" className="stacked-form" onSubmit={handleBroadcastSubmit}>
              <label htmlFor="broadcast-message">
                <span>전송할 메시지</span>
              </label>
              <input
                id="broadcast-message"
                type="text"
                placeholder="예: 14시에 모든 세션을 재시작합니다"
                value={broadcastText}
                onChange={(event) => setBroadcastText(event.target.value)}
              />
              <button type="submit" disabled={broadcastLoading}>
                모두에게 전송
              </button>
              {broadcastFeedback && (
                <div className={`form-message ${broadcastFeedback.type}`}>
                  {broadcastFeedback.message}
                </div>
              )}
            </form>
          </section>
        </section>

        <section className="card">
          <div className="card-heading">
            <h2>환경 설정</h2>
            <span className="badge subtle">Slack · Telegram · 브릿지</span>
          </div>
          <p className="description">
            토큰과 기본 채널 정보를 등록하면 <code>python -m bridge</code> 실행 시 바로 적용됩니다.
          </p>
          <form id="config-form" className="stacked-form" onSubmit={handleConfigSubmit}>
            <fieldset>
              <legend>마스터 서버</legend>
              <div className="fieldset-grid">
                <label>
                  <span>호스트</span>
                  <input
                    name="master_host"
                    type="text"
                    autoComplete="off"
                    value={configForm.master_host}
                    onChange={handleConfigChange}
                  />
                </label>
                <label>
                  <span>포트</span>
                  <input
                    name="master_port"
                    type="number"
                    min={1}
                    max={65535}
                    value={configForm.master_port}
                    onChange={handleConfigChange}
                  />
                </label>
                <label>
                  <span>HTTP 호스트</span>
                  <input
                    name="master_http_host"
                    type="text"
                    autoComplete="off"
                    value={configForm.master_http_host}
                    onChange={handleConfigChange}
                  />
                </label>
                <label>
                  <span>HTTP 포트</span>
                  <input
                    name="master_http_port"
                    type="number"
                    min={1}
                    max={65535}
                    value={configForm.master_http_port}
                    onChange={handleConfigChange}
                  />
                </label>
                <label>
                  <span>헬스 체크 주기(초)</span>
                  <input
                    name="master_health_interval"
                    type="number"
                    min={1}
                    step={0.5}
                    value={configForm.master_health_interval}
                    onChange={handleConfigChange}
                  />
                </label>
                <label>
                  <span>헬스 타임아웃(초)</span>
                  <input
                    name="master_health_timeout"
                    type="number"
                    min={1}
                    step={0.5}
                    value={configForm.master_health_timeout}
                    onChange={handleConfigChange}
                  />
                </label>
              </div>
            </fieldset>

            <fieldset>
              <legend>브릿지 공용 설정</legend>
              <div className="fieldset-grid">
                <label>
                  <span>로그 레벨</span>
                  <select
                    name="bridge_log_level"
                    value={configForm.bridge_log_level}
                    onChange={handleConfigChange}
                  >
                    {LOG_LEVEL_OPTIONS.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>원격 기본 태그 (콤마 구분)</span>
                  <input
                    name="bridge_remote_default_tags"
                    type="text"
                    value={configForm.bridge_remote_default_tags}
                    onChange={handleConfigChange}
                    placeholder="staging,linux"
                  />
                </label>
                <label className="checkbox-row">
                  <input
                    name="bridge_autostart"
                    type="checkbox"
                    checked={configForm.bridge_autostart}
                    onChange={handleConfigChange}
                  />
                  <span>마스터 시작 시 브릿지 자동 시작</span>
                </label>
              </div>
            </fieldset>

            <fieldset>
              <legend>Slack</legend>
              <div className="fieldset-grid">
                <label>
                  <span>봇 토큰</span>
                  <input
                    name="slack_bot_token"
                    type="password"
                    autoComplete="off"
                    value={configForm.slack_bot_token}
                    onChange={handleConfigChange}
                  />
                  {configPayload?.slack.bot_token_masked && (
                    <span className="small-text">현재: {configPayload.slack.bot_token_masked}</span>
                  )}
                </label>
                <label>
                  <span>기본 응답 채널 ID</span>
                  <input
                    name="slack_default_channel"
                    type="text"
                    value={configForm.slack_default_channel}
                    onChange={handleConfigChange}
                    placeholder="C123456789"
                  />
                </label>
              </div>
            </fieldset>

            <fieldset>
              <legend>Telegram</legend>
              <div className="fieldset-grid">
                <label>
                  <span>봇 토큰</span>
                  <input
                    name="telegram_bot_token"
                    type="password"
                    autoComplete="off"
                    value={configForm.telegram_bot_token}
                    onChange={handleConfigChange}
                  />
                  {configPayload?.telegram.bot_token_masked && (
                    <span className="small-text">현재: {configPayload.telegram.bot_token_masked}</span>
                  )}
                </label>
                <label>
                  <span>Parse Mode</span>
                  <input
                    name="telegram_parse_mode"
                    type="text"
                    value={configForm.telegram_parse_mode}
                    onChange={handleConfigChange}
                    placeholder="MarkdownV2"
                  />
                </label>
                <label>
                  <span>허용 Chat ID (콤마 구분)</span>
                  <input
                    name="telegram_allowed_chats"
                    type="text"
                    value={configForm.telegram_allowed_chats}
                    onChange={handleConfigChange}
                    placeholder="123456789,987654321"
                  />
                </label>
              </div>
            </fieldset>

            <label>
              <span>관리 메모</span>
              <textarea name="notes" value={configForm.notes} onChange={handleConfigChange} placeholder="브릿지 비고를 자유롭게 기록하세요." />
            </label>

            <button type="submit" disabled={configLoading}>
              설정 저장
            </button>
            {configFeedback && (
              <div id="config-feedback" className={`form-message ${configFeedback.type}`}>
                {configFeedback.message}
              </div>
            )}
          </form>
        </section>

        <section className="card">
          <div className="card-heading">
            <h2>GitHub 연결 (임시)</h2>
            <span className="badge subtle">OAuth 준비</span>
          </div>
          <p className="description">
            정식 OAuth 구현 전까지는 user_id와 access token을 직접 입력해 토큰을 저장합니다. 개발/테스트용으로만 사용하세요.
          </p>
          <form className="stacked-form" onSubmit={handleGithubSubmit}>
            <label>
              <span>사용자 ID</span>
              <input
                type="text"
                value={githubUserId}
                onChange={(event) => setGithubUserId(event.target.value)}
                placeholder="예: slack:T123:U456"
              />
            </label>
            <label>
              <span>Access Token</span>
              <input
                type="password"
                value={githubAccessToken}
                onChange={(event) => setGithubAccessToken(event.target.value)}
                placeholder="ghp_..."
              />
            </label>
            <label>
              <span>Refresh Token (선택)</span>
              <input
                type="text"
                value={githubRefreshToken}
                onChange={(event) => setGithubRefreshToken(event.target.value)}
              />
            </label>
            <label>
              <span>만료 시각 (ISO8601)</span>
              <input
                type="text"
                value={githubExpiresAt}
                onChange={(event) => setGithubExpiresAt(event.target.value)}
                placeholder="2025-10-20T12:34:56Z"
              />
            </label>
            <div className="github-actions">
              <button type="submit" disabled={githubLoading}>
                토큰 저장
              </button>
              <button
                type="button"
                className="ghost"
                onClick={handleFetchGithubRepos}
                disabled={githubLoading || !githubUserId.trim()}
              >
                레포 불러오기
              </button>
            </div>
            {githubFeedback && (
              <div className={`form-message ${githubFeedback.type}`}>{githubFeedback.message}</div>
            )}
          </form>

          <div className="github-repo-list">
            {githubRepos.length === 0 ? (
              <div className="small-text">저장된 토큰으로 가져온 레포가 없습니다.</div>
            ) : (
              githubRepos.map((repo) => (
                <div key={repo.full_name} className="github-repo-item">
                  <div>
                    <div className="remote-name">{repo.full_name}</div>
                    <div className="small-text">기본 브랜치: {repo.default_branch || 'main'}</div>
                  </div>
                  <button type="button" className="ghost" onClick={() => handleAddRepository(repo.url)}>
                    작업에 추가
                  </button>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="card">
          <div className="card-heading">
            <h2>작업 실행</h2>
            <span className="badge info">{jobs.length}</span>
          </div>
          <p className="description">Codernetes 노드에서 실행할 작업을 생성하고, 현재 상태를 모니터링합니다.</p>
          <form className="stacked-form" onSubmit={handleJobSubmit}>
            <label>
              <span>프롬프트</span>
              <textarea
                name="prompt"
                value={jobForm.prompt}
                onChange={handleJobFormChange}
                placeholder="예: run tests --retries=2"
                required
              />
            </label>
            <div className="fieldset-grid">
              <label>
                <span>대상 노드</span>
                <select
                  name="targetNodeId"
                  value={jobForm.targetNodeId}
                  onChange={handleJobFormChange}
                >
                  <option value="">자동 선택</option>
                  {registeredNodes.map((node) => (
                    <option key={node.node_id} value={node.node_id}>
                      {(node.display_name || node.node_id) + ` (${node.status})`}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>요청 태그 (콤마 구분)</span>
                <input
                  name="requestedTags"
                  type="text"
                  value={jobForm.requestedTags}
                  onChange={handleJobFormChange}
                  placeholder="staging,gpu"
                />
              </label>
            </div>
            <label>
              <span>레포지토리 URL (줄 단위)</span>
              <textarea
                name="repositoryUrls"
                value={jobForm.repositoryUrls}
                onChange={handleJobFormChange}
                placeholder={`https://github.com/org/repo1\nhttps://github.com/org/repo2`}
              />
            </label>
            <button type="submit" disabled={jobLoading}>
              작업 생성
            </button>
            {jobFeedback && (
              <div className={`form-message ${jobFeedback.type}`}>{jobFeedback.message}</div>
            )}
            {nodesError && <div className="form-message error">{nodesError}</div>}
          </form>

          <table className="remote-table job-table">
            <thead>
              <tr>
                <th>작업</th>
                <th>상태</th>
                <th>노드</th>
                <th>시간</th>
                <th>결과</th>
              </tr>
            </thead>
            <tbody>
              {sortedJobs.length === 0 ? (
                <tr>
                  <td className="empty" colSpan={5}>
                    등록된 작업이 없습니다.
                  </td>
                </tr>
              ) : (
                sortedJobs.map((job) => (
                  <tr
                    key={job.job_id}
                    className={`job-row${selectedJobId === job.job_id ? ' selected' : ''}`}
                    onClick={() => handleSelectJob(job.job_id)}
                  >
                    <td>
                      <div className="remote-name">{job.prompt}</div>
                      <div className="remote-id">
                        <code>{job.job_id}</code>
                      </div>
                      {job.repositories.length > 0 && (
                        <div className="small-text">레포 {job.repositories.length}개</div>
                      )}
                    </td>
                    <td>
                      <span className={JOB_STATUS_CLASSES[job.status] ?? 'badge subtle'}>
                        {JOB_STATUS_LABELS[job.status] ?? job.status}
                      </span>
                    </td>
                    <td>{job.target_node_id || '자동'}</td>
                    <td>
                      <div className="small-text">생성: {formatDate(job.created_at)}</div>
                      <div className="small-text">완료: {formatDate(job.finished_at)}</div>
                    </td>
                    <td>
                      {job.result_summary ? job.result_summary : '요약 없음'}
                      {job.error_message && (
                        <div className="small-text text-error">오류: {job.error_message}</div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {jobsError && <div className="form-message error">{jobsError}</div>}
        </section>

        <section className="card">
          <div className="card-heading">
            <h2>작업 상세</h2>
            {selectedJob && (
              <span className={JOB_STATUS_CLASSES[selectedJob.status] ?? 'badge subtle'}>
                {JOB_STATUS_LABELS[selectedJob.status] ?? selectedJob.status}
              </span>
            )}
          </div>
          {selectedJob ? (
            <>
              <div className="job-detail-grid">
                <div>
                  <div className="small-text">작업 ID</div>
                  <code>{selectedJob.job_id}</code>
                </div>
                <div>
                  <div className="small-text">대상 노드</div>
                  <span>{selectedJob.target_node_id || '자동'}</span>
                </div>
                <div>
                  <div className="small-text">생성 시각</div>
                  <span>{formatDate(selectedJob.created_at)}</span>
                </div>
                <div>
                  <div className="small-text">완료 시각</div>
                  <span>{formatDate(selectedJob.finished_at)}</span>
                </div>
              </div>
              {selectedJob.result_summary && (
                <div className="job-summary">
                  <div className="small-text">결과 요약</div>
                  <p>{selectedJob.result_summary}</p>
                </div>
              )}
              {selectedJob.error_message && (
                <div className="job-summary error">
                  <div className="small-text">오류</div>
                  <p>{selectedJob.error_message}</p>
                </div>
              )}
              <div className="job-log-header">
                <h3>실행 로그</h3>
                <div className="job-log-actions">
                  <button type="button" className="ghost" onClick={() => loadJobLogs({ reset: true })}>
                    새로고침
                  </button>
                  {jobLogsLoading && <span className="small-text">불러오는 중...</span>}
                </div>
              </div>
              {jobLogsError && <div className="form-message error">{jobLogsError}</div>}
              <div className="job-log-window">
                {jobLogs.length === 0 && !jobLogsLoading ? (
                  <div className="small-text">로그가 없습니다.</div>
                ) : (
                  jobLogs.map((log) => (
                    <div key={log.seq} className={`job-log-line level-${log.level}`}>
                      <span className="timestamp">[{formatDate(log.timestamp)}]</span>
                      <span className="level">[{log.level.toUpperCase()}]</span>
                      <span className="message">{log.message}</span>
                    </div>
                  ))
                )}
              </div>
            </>
          ) : (
            <div className="small-text">왼쪽 목록에서 작업을 선택하세요.</div>
          )}
        </section>

        <section className="card">
          <div className="card-heading">
            <h2>원격 노드 관리</h2>
            <span className="badge info" id="remote-count">
              {remotes.length}
            </span>
          </div>
          <p className="description">Slack/Telegram 명령으로 제어할 Codernetes 실행 노드를 등록하고 상태를 표시합니다.</p>
          {remotesError && <div className="form-message error">{remotesError}</div>}
          <table id="remote-table" className="remote-table">
            <thead>
              <tr>
                <th>노드</th>
                <th>상태</th>
                <th>주소</th>
                <th>태그</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {remotes.length === 0 ? (
                <tr>
                  <td className="empty" colSpan={5}>
                    등록된 원격 노드가 없습니다.
                  </td>
                </tr>
              ) : (
                remotes.map((remote) => (
                  <tr key={remote.id} data-remote-id={remote.id}>
                    <td>
                      <div className="remote-name">{remote.name}</div>
                      <div className="remote-id">
                        <code>{remote.id}</code>
                      </div>
                      {remote.notes && <div className="small-text">{remote.notes}</div>}
                    </td>
                    <td>
                      <span className={REMOTE_STATUS_CLASSES[remote.status] ?? 'badge subtle'}>
                        {REMOTE_STATUS_LABELS[remote.status] ?? remote.status}
                      </span>
                      <div className="small-text">최근: {formatDate(remote.last_seen)}</div>
                    </td>
                    <td>
                      <code>{remote.address || `${remote.host}:${remote.port}`}</code>
                    </td>
                    <td>{remote.tags?.length ? remote.tags.join(', ') : '태그 없음'}</td>
                    <td className="remote-actions">
                      <button type="button" className="ghost" onClick={() => handleRemoteAction(remote.id, 'mark_online')}>
                        온라인
                      </button>
                      <button type="button" className="ghost" onClick={() => handleRemoteAction(remote.id, 'mark_busy')}>
                        작업중
                      </button>
                      <button type="button" className="ghost" onClick={() => handleRemoteAction(remote.id, 'mark_maintenance')}>
                        점검
                      </button>
                      <button type="button" className="ghost danger" onClick={() => handleRemoteAction(remote.id, 'mark_offline')}>
                        오프라인
                      </button>
                      <button type="button" className="ghost danger" onClick={() => handleRemoteDelete(remote.id)}>
                        삭제
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <form id="remote-form" className="stacked-form" onSubmit={handleRemoteSubmit}>
            <fieldset>
              <legend>새 원격 노드 등록 (목업)</legend>
              <div className="fieldset-grid inline">
                <label>
                  <span>이름</span>
                  <input
                    name="name"
                    type="text"
                    required
                    value={remoteForm.name}
                    onChange={handleRemoteChange}
                    placeholder="staging-runner"
                  />
                </label>
                <label>
                  <span>호스트</span>
                  <input
                    name="host"
                    type="text"
                    required
                    value={remoteForm.host}
                    onChange={handleRemoteChange}
                    placeholder="10.0.0.5"
                  />
                </label>
                <label>
                  <span>포트</span>
                  <input
                    name="port"
                    type="number"
                    min={1}
                    max={65535}
                    value={remoteForm.port}
                    onChange={handleRemoteChange}
                  />
                </label>
                <label>
                  <span>태그 (콤마 구분)</span>
                  <input
                    name="tags"
                    type="text"
                    value={remoteForm.tags}
                    onChange={handleRemoteChange}
                    placeholder="staging,linux"
                  />
                </label>
                <label>
                  <span>메모</span>
                  <input
                    name="notes"
                    type="text"
                    value={remoteForm.notes}
                    onChange={handleRemoteChange}
                    placeholder="사용자 정의 설명"
                  />
                </label>
              </div>
            </fieldset>
            <button type="submit" disabled={remoteLoading}>
              원격 노드 추가
            </button>
            {remoteFeedback && (
              <div id="remote-feedback" className={`form-message ${remoteFeedback.type}`}>
                {remoteFeedback.message}
              </div>
            )}
          </form>
        </section>

        <footer>Codernetes 마스터는 프로토타입 대시보드입니다. 실제 Slack/Telegram 연동은 브릿지 프로세스를 실행해야 적용됩니다.</footer>
      </main>
    </div>
  )
}

export default App
