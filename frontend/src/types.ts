export interface ClientInfo {
  id: string
  status: string
  last_seen: string
}

export interface StatusResponse {
  status: string
  connected_clients: number
  clients: ClientInfo[]
}

export interface MasterConfig {
  host?: string
  port?: number
  http_host?: string
  http_port?: number
  health_interval?: number
  health_timeout?: number
}

export interface BridgeConfig {
  log_level?: string
  autostart?: boolean
  remote_default_tags?: string[]
  remote_default_tags_csv?: string
}

export interface SlackConfig {
  bot_token?: string
  default_channel?: string
  bot_token_masked?: string
  has_token?: boolean
}

export interface TelegramConfig {
  bot_token?: string
  parse_mode?: string
  allowed_chats?: string
  bot_token_masked?: string
  allowed_chats_list?: string[]
}

export interface ConfigPayload {
  master: MasterConfig
  bridge: BridgeConfig
  slack: SlackConfig
  telegram: TelegramConfig
  notes?: string
  updated_at: string
}

export interface ConfigResponse {
  config: ConfigPayload
}

export interface ConfigUpdateRequest {
  master: Record<string, string | number | boolean | null | undefined>
  bridge: Record<string, string | number | boolean | null | undefined>
  slack: Record<string, string | number | boolean | null | undefined>
  telegram: Record<string, string | number | boolean | null | undefined>
  notes?: string
}

export interface RemoteNode {
  id: string
  name: string
  host: string
  port: number
  address: string
  tags: string[]
  status: string
  last_seen: string | null
  notes: string
}

export interface RemotesResponse {
  remotes: RemoteNode[]
  count: number
  generated_at: string
}

export interface RemoteCreateRequest {
  name: string
  host: string
  port: string | number
  tags?: string
  notes?: string
}

export interface RemoteActionRequest {
  action: string
}

export interface RemoteActionResponse {
  status: string
  remote: RemoteNode
}

export interface BroadcastResponse {
  status: string
  broadcasted: string
  connected_clients: number
}

export type JobStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface JobRepositorySpec {
  url: string
  branch?: string | null
  subdirectory?: string | null
}

export interface Job {
  job_id: string
  prompt: string
  status: JobStatus
  target_node_id?: string | null
  requested_tags: string[]
  repositories: JobRepositorySpec[]
  metadata: Record<string, unknown>
  log_path?: string | null
  result_summary?: string | null
  error_message?: string | null
  created_at: string
  finished_at?: string | null
}

export interface JobsResponse {
  jobs: Job[]
}

export interface JobCreateRequest {
  prompt: string
  target_node_id?: string
  requested_tags?: string[]
  repositories: JobRepositorySpec[]
  origin?: string
}

export interface JobLogEntry {
  job_id: string
  seq: number
  timestamp: string
  level: string
  message: string
}

export interface JobLogsResponse {
  logs: JobLogEntry[]
}

export interface GithubRepo {
  name: string
  full_name: string
  url: string
  default_branch?: string
}

export interface RegisteredNode {
  node_id: string
  display_name?: string | null
  tags: string[]
  capabilities: Record<string, string>
  status: string
  last_seen: string
}

export interface ApiErrorResponse {
  error?: string
}

export interface SendMessageResponse {
  status: string
  client_id: string
  message: string
}

export interface ConfigFormState {
  master_host: string
  master_port: string
  master_http_host: string
  master_http_port: string
  master_health_interval: string
  master_health_timeout: string
  bridge_log_level: string
  bridge_remote_default_tags: string
  bridge_autostart: boolean
  slack_bot_token: string
  slack_default_channel: string
  telegram_bot_token: string
  telegram_parse_mode: string
  telegram_allowed_chats: string
  notes: string
}

export interface RemoteFormState {
  name: string
  host: string
  port: string
  tags: string
  notes: string
}

export interface JobFormState {
  prompt: string
  targetNodeId: string
  requestedTags: string
  repositoryUrls: string
}

export type Feedback = {
  type: 'success' | 'error'
  message: string
}
