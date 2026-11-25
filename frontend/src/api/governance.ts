import { request } from './client'

/** 慢查历史影响样本行：按实际取用版本沉淀的单条执行记录。 */
export type SlowHistoryRow = {
  id: number
  记录标识: string
  日志ID: number
  请求标识: string
  尝试序号: number
  查询内容: string
  查询用户: string
  查询时间: string
  执行耗时ms: number
  采用版本: string
  缓存命中: string
  口径期间: string
  资料状态: string
  缺失范围: string
  可重跑: string
}

export type MetricDecisionRow = {
  id: number
  决策标识: string
  关联指标: string
  口径版本: string
  口径期间: string
  生效时间: string
  决策依据: string
  数据来源: string
  影响查询: string
}

export type RerunRow = {
  id: number
  诊断单ID: number
  复跑轮次: number
  日志ID: number
  记录标识: string
  请求标识: string
  尝试序号: number
  采用版本: string
  缓存命中: string
  原执行耗时ms: number
  复跑耗时ms: number
  资料状态: string
  返回数据: {
    可用: boolean
    缺失范围?: string
    说明?: string
    返回行数?: number
    样例数据?: { bucket: string; metric_value: number }[]
    采用版本?: string
    口径期间?: string
  }
  复跑时间: string
}

export type DiagnosisRow = {
  id: number
  诊断单号: string
  选中日志IDs: number[]
  关联请求标识: string[]
  提交人: string
  提交时间: string
  备注: string
  受理状态: string
  含过期资料: string
  过期缺失明细?: { 日志ID: number; 记录标识: string; 缺失范围: string }[]
  复跑次数: number
  已复跑日志IDs: number[]
  执行记录?: SlowHistoryRow[] | Record<string, unknown>[]
  复跑记录?: RerunRow[]
}

type PagePayload<T> = { items: T[]; total: number; page: number; size: number }

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `接口返回 ${response.status}`)
  }
  return (await response.json()) as T
}

/** 慢查历史：按实际执行时间、采用版本、是否命中、口径期间检索可重跑影响样本。 */
export async function searchSlowHistory(filters: {
  采用版本?: string
  缓存命中?: string
  口径期间?: string
  请求标识?: string
  资料状态?: string
  min_duration_ms?: number
  max_duration_ms?: number
}): Promise<PagePayload<SlowHistoryRow>> {
  const query = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== '' && value !== undefined && value !== null) {
      query.set(key, String(value))
    }
  })
  const response = await request(`/api/governance/slow-history?${query.toString()}`)
  return readJson(response)
}

export async function listMetricDecisions(
  filters: Record<string, string> = {},
): Promise<{ items: MetricDecisionRow[]; total: number }> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/governance/metric-decisions?${query}`)
  return readJson(response)
}

export async function listDiagnoses(): Promise<{ items: DiagnosisRow[]; total: number }> {
  const response = await request('/api/governance/diagnoses')
  return readJson(response)
}

export async function getDiagnosis(id: number): Promise<DiagnosisRow> {
  const response = await request(`/api/governance/diagnoses/${id}`)
  return readJson(response)
}

/** 按实际选中的执行记录提交诊断；同一批选中记录后端只受理一次。 */
export async function submitDiagnosis(
  logIds: number[],
  remark = '',
): Promise<{ ok: boolean; accepted: boolean; duplicated?: boolean; message: string; diagnosis: DiagnosisRow | null; expired_records?: { 日志ID: number; 缺失范围: string }[] }> {
  const response = await request('/api/governance/diagnoses', {
    method: 'POST',
    body: JSON.stringify({ log_ids: logIds, operator: '值班员', remark }),
  })
  return readJson(response)
}

export async function rerunDiagnosis(
  id: number,
): Promise<{ ok: boolean; message: string; run_no: number; reruns: RerunRow[]; diagnosis: DiagnosisRow }> {
  const response = await request(`/api/governance/diagnoses/${id}/rerun`, { method: 'POST' })
  return readJson(response)
}

export async function restoreMaterial(
  diagnosisId: number,
  logId: number,
  restoredScope: string,
): Promise<{ ok: boolean; message: string }> {
  const response = await request(
    `/api/governance/diagnoses/${diagnosisId}/restore/${logId}`,
    { method: 'POST', body: JSON.stringify({ restored_scope: restoredScope }) },
  )
  return readJson(response)
}

export async function getImpactSample(id: number): Promise<Record<string, unknown>> {
  const response = await request(`/api/governance/diagnoses/${id}/impact-sample`)
  return readJson(response)
}
