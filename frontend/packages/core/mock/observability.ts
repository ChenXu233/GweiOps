import type { MetricSample } from '../types/observability'

/**
 * 演示用的指标快照。
 *
 * 前半段(gwei_*)是引擎自己在写的:LLM 计量、议题处理、投票、活跃会话、错误计数。
 * 后半段是插件上报的形状:HTTP 入口与观测 agent。
 * 真实环境只会比这里多,不会比这里少——真接上引擎后这就是 GET /api/metrics 的原样返回。
 */
export const mockMetrics: MetricSample[] = [
  // LLM 计量:按模型分序列
  { name: 'gwei_llm_calls_total', labels: { model: 'claude-sonnet-4' }, value: 184 },
  { name: 'gwei_llm_calls_total', labels: { model: 'gpt-4o' }, value: 96 },
  { name: 'gwei_llm_calls_total', labels: { model: 'qwen-max' }, value: 42 },
  { name: 'gwei_llm_tokens_total', labels: { model: 'claude-sonnet-4' }, value: 1284600 },
  { name: 'gwei_llm_tokens_total', labels: { model: 'gpt-4o' }, value: 742300 },
  { name: 'gwei_llm_tokens_total', labels: { model: 'qwen-max' }, value: 218900 },
  { name: 'gwei_llm_call_duration_seconds', labels: { model: 'claude-sonnet-4' }, value: 2.84 },
  { name: 'gwei_llm_call_duration_seconds', labels: { model: 'gpt-4o' }, value: 1.37 },
  { name: 'gwei_llm_call_duration_seconds', labels: { model: 'qwen-max' }, value: 0.92 },

  // 议题与变更
  { name: 'gwei_issues_processed_total', labels: { status: 'fixed' }, value: 37 },
  { name: 'gwei_issues_processed_total', labels: { status: 'escalated' }, value: 6 },
  { name: 'gwei_issues_processed_total', labels: { status: 'ignored' }, value: 11 },
  { name: 'gwei_prs_created_total', labels: {}, value: 24 },
  { name: 'gwei_votes_total', labels: { pr_id: '#42', vote: 'keep' }, value: 3 },
  { name: 'gwei_votes_total', labels: { pr_id: '#42', vote: 'revert' }, value: 1 },
  { name: 'gwei_active_sessions', labels: {}, value: 5 },
  { name: 'gwei_errors_total', labels: { type: 'plugin_timeout' }, value: 2 },
  { name: 'gwei_errors_total', labels: { type: 'llm_timeout' }, value: 1 },

  // 插件上报:HTTP 入口
  { name: 'http_requests_total', labels: { code: '200', service: 'api-gateway' }, value: 18240 },
  { name: 'http_requests_total', labels: { code: '500', service: 'api-gateway' }, value: 7 },
  { name: 'http_request_duration_seconds', labels: { service: 'api-gateway' }, value: 0.084 },

  // 插件上报:观测 agent
  { name: 'observer_scrape_duration_seconds', labels: { agent: 'observer-agent' }, value: 1.204 },
  { name: 'observer_findings_total', labels: { severity: 'warning' }, value: 12 },
]
