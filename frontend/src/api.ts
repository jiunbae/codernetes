import type {
  BroadcastResponse,
  ConfigResponse,
  ConfigUpdateRequest,
  Job,
  JobCreateRequest,
  JobsResponse,
  RegisteredNode,
  JobLogsResponse,
  GithubRepo,
  RemoteActionRequest,
  RemoteActionResponse,
  RemoteCreateRequest,
  RemotesResponse,
  SendMessageResponse,
  StatusResponse,
} from './types'

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...init.headers,
  }

  const response = await fetch(url, {
    credentials: 'same-origin',
    ...init,
    headers,
  })

  const text = await response.text()
  const hasBody = text.length > 0
  const data = hasBody ? (JSON.parse(text) as unknown) : null

  if (!response.ok) {
    const message =
      typeof data === 'object' && data !== null && 'error' in data
        ? String((data as { error?: unknown }).error ?? response.statusText)
        : response.statusText
    throw new Error(message || '요청에 실패했습니다.')
  }

  return (data as T) ?? ({} as T)
}

export function fetchStatus(): Promise<StatusResponse> {
  return request<StatusResponse>('/api/status', { method: 'GET' })
}

export function broadcastMessage(message: string): Promise<BroadcastResponse> {
  return request<BroadcastResponse>('/api/broadcast', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export function fetchConfig(): Promise<ConfigResponse> {
  return request<ConfigResponse>('/api/config', { method: 'GET' })
}

export function updateConfig(payload: ConfigUpdateRequest): Promise<ConfigResponse> {
  return request<ConfigResponse>('/api/config', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchRemotes(): Promise<RemotesResponse> {
  return request<RemotesResponse>('/api/remotes', { method: 'GET' })
}

export function createRemote(payload: RemoteCreateRequest): Promise<{ status: string; remote: RemotesResponse['remotes'][number] }> {
  return request<{ status: string; remote: RemotesResponse['remotes'][number] }>('/api/remotes', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateRemote(remoteId: string, payload: RemoteActionRequest): Promise<RemoteActionResponse> {
  return request<RemoteActionResponse>(`/api/remotes/${remoteId}/action`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function removeRemote(remoteId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/remotes/${remoteId}`, {
    method: 'DELETE',
  })
}

export function sendToClient(clientId: string, message: string): Promise<SendMessageResponse> {
  return request<SendMessageResponse>('/api/send', {
    method: 'POST',
    body: JSON.stringify({ client_id: clientId, message }),
  })
}

export function fetchJobs(status?: string): Promise<JobsResponse> {
  const search = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<JobsResponse>(`/api/jobs${search}`, { method: 'GET' })
}

export function createJob(payload: JobCreateRequest): Promise<{ job: Job }> {
  return request<{ job: Job }>('/api/jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchRegisteredNodes(): Promise<{ nodes: RegisteredNode[] }> {
  return request<{ nodes: RegisteredNode[] }>('/api/nodes', { method: 'GET' })
}

export function fetchJobLogs(jobId: string, params?: { limit?: number; after?: number }): Promise<JobLogsResponse> {
  const searchParams = new URLSearchParams()
  if (params?.limit) searchParams.set('limit', String(params.limit))
  if (params?.after !== undefined) searchParams.set('after', String(params.after))
  const query = searchParams.toString()
  const url = query ? `/api/jobs/${jobId}/logs?${query}` : `/api/jobs/${jobId}/logs`
  return request<JobLogsResponse>(url, { method: 'GET' })
}

export function saveGithubToken(payload: {
  user_id: string
  access_token: string
  refresh_token?: string
  expires_at?: string
  scope?: string
  token_type?: string
}): Promise<{ status: string }> {
  return request<{ status: string }>('/api/github/token', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchGithubRepos(userId: string): Promise<{ repos: GithubRepo[] }> {
  const search = new URLSearchParams({ user_id: userId })
  return request<{ repos: GithubRepo[] }>(`/api/github/repos?${search.toString()}`, { method: 'GET' })
}
