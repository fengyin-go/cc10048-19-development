<template>
  <section class="page governance-page" data-module="query_governance">
    <header class="page-head">
      <div>
        <h2>慢查治理工作台</h2>
        <p class="page-desc">
          按实际执行时间、采用版本、是否命中定位慢查，沉淀可重跑的影响样本；
          同一请求的重试以请求标识+尝试序号区分，过期资料只标缺失范围，不以新口径冒充旧值。
        </p>
      </div>
    </header>

    <!-- 筛选区：实际执行时间 / 采用版本 / 是否命中 / 口径期间 -->
    <form class="analysis-form" @submit.prevent="reloadHistory">
      <label>
        最小执行耗时(ms)
        <input v-model.number="filters.min_duration_ms" data-testid="filter-min-duration" type="number" min="0" placeholder="如 3000" />
      </label>
      <label>
        最大执行耗时(ms)
        <input v-model.number="filters.max_duration_ms" data-testid="filter-max-duration" type="number" min="0" placeholder="如 6000" />
      </label>
      <label>
        采用版本
        <select v-model="filters.采用版本" data-testid="filter-version">
          <option value="">全部</option>
          <option value="v1">v1（缓存口径）</option>
          <option value="v2">v2（实际取数）</option>
        </select>
      </label>
      <label>
        是否命中
        <select v-model="filters.缓存命中" data-testid="filter-cache-hit">
          <option value="">全部</option>
          <option value="是">命中</option>
          <option value="否">未命中</option>
        </select>
      </label>
      <label>
        口径期间
        <select v-model="filters.口径期间" data-testid="filter-period">
          <option value="">全部</option>
          <option value="旧期">旧期</option>
          <option value="指标版本">指标版本</option>
        </select>
      </label>
      <label>
        资料状态
        <select v-model="filters.资料状态" data-testid="filter-material">
          <option value="">全部</option>
          <option value="受查">受查</option>
          <option value="已过期">已过期</option>
        </select>
      </label>
      <button class="btn primary" data-testid="governance-query" type="submit">查询慢查历史</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">筛选命中执行记录</span>
        <strong class="stat-value">{{ historyTotal }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已选中待诊断</span>
        <strong class="stat-value">{{ selectedIds.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">诊断单总数</span>
        <strong class="stat-value">{{ diagnoses.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">含过期资料诊断</span>
        <strong class="stat-value">{{ expiredDiagnosisCount }}</strong>
      </article>
    </div>

    <!-- 慢查历史影响样本表，行内勾选 -->
    <table class="data-table" data-testid="slow-history-table">
      <thead>
        <tr>
          <th>选择</th>
          <th>记录标识</th>
          <th>请求标识</th>
          <th>尝试序号</th>
          <th>执行耗时ms</th>
          <th>采用版本</th>
          <th>缓存命中</th>
          <th>口径期间</th>
          <th>资料状态</th>
          <th>缺失范围</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in historyRows" :key="String(row.id)" :data-testid="`history-row-${row.日志ID}`">
          <td>
            <input
              type="checkbox"
              :data-testid="`select-${row.日志ID}`"
              :value="row.日志ID"
              v-model="selectedIds"
            />
          </td>
          <td>{{ row.记录标识 }}</td>
          <td>{{ row.请求标识 }}</td>
          <td>{{ row.尝试序号 }}</td>
          <td>{{ row.执行耗时ms }}</td>
          <td>{{ row.采用版本 }}</td>
          <td>{{ row.缓存命中 }}</td>
          <td>{{ row.口径期间 }}</td>
          <td>
            <span :class="row.资料状态 === '已过期' ? 'trend-down' : ''">{{ row.资料状态 }}</span>
          </td>
          <td>{{ row.缺失范围 || '—' }}</td>
        </tr>
        <tr v-if="!historyRows.length">
          <td colspan="10" class="empty-state">没有符合条件的慢查执行记录</td>
        </tr>
      </tbody>
    </table>

    <div class="page-actions" style="margin: 12px 0">
      <button
        class="btn primary"
        data-testid="submit-diagnosis"
        type="button"
        :disabled="!selectedIds.length || submitting"
        @click="onSubmitDiagnosis"
      >
        {{ submitting ? '提交中…' : `对选中的 ${selectedIds.length} 条执行记录提交诊断` }}
      </button>
      <span v-if="selectionHint" class="page-desc">{{ selectionHint }}</span>
    </div>

    <!-- 指标决策数据 -->
    <h3 style="margin: 18px 0 8px">指标决策数据（口径版本与数据源）</h3>
    <table class="data-table" data-testid="metric-decision-table">
      <thead>
        <tr>
          <th>决策标识</th>
          <th>关联指标</th>
          <th>口径版本</th>
          <th>口径期间</th>
          <th>生效时间</th>
          <th>数据来源</th>
          <th>影响查询</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in decisions" :key="String(row.id)">
          <td>{{ row.决策标识 }}</td>
          <td>{{ row.关联指标 }}</td>
          <td>{{ row.口径版本 }}</td>
          <td>{{ row.口径期间 }}</td>
          <td>{{ row.生效时间 }}</td>
          <td>{{ row.数据来源 }}</td>
          <td>{{ row.影响查询 }}</td>
        </tr>
      </tbody>
    </table>

    <!-- 诊断单列表 -->
    <h3 style="margin: 18px 0 8px">诊断单（同批选中记录只受理一次）</h3>
    <table class="data-table" data-testid="diagnosis-table">
      <thead>
        <tr>
          <th>诊断单号</th>
          <th>选中执行记录</th>
          <th>关联请求</th>
          <th>受理状态</th>
          <th>含过期资料</th>
          <th>复跑次数</th>
          <th>提交时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="diag in diagnoses" :key="String(diag.id)" :data-testid="`diagnosis-row-${diag.id}`">
          <td>{{ diag.诊断单号 }}</td>
          <td>{{ diag.选中日志IDs.join(', ') }}</td>
          <td>{{ diag.关联请求标识.join(', ') }}</td>
          <td>{{ diag.受理状态 }}</td>
          <td>
            <span :class="diag.含过期资料 === '是' ? 'trend-down' : ''">{{ diag.含过期资料 }}</span>
          </td>
          <td>{{ diag.复跑次数 }}</td>
          <td>{{ diag.提交时间 }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`view-${diag.id}`" @click="openDiagnosis(diag.id)">
              查看复跑
            </button>
            <button class="link" type="button" :data-testid="`rerun-${diag.id}`" @click="onRerun(diag.id)">
              实际复跑
            </button>
          </td>
        </tr>
        <tr v-if="!diagnoses.length">
          <td colspan="8" class="empty-state">尚未提交诊断</td>
        </tr>
      </tbody>
    </table>

    <!-- 诊断详情：复跑流水、缺失标注、资料补回 -->
    <div v-if="activeDiagnosis" class="modal-backdrop" data-testid="diagnosis-modal">
      <div class="modal" style="width: min(900px, 100%)">
        <h3>诊断 {{ activeDiagnosis.诊断单号 }} 的复跑追溯</h3>
        <p class="page-desc">
          选中记录：{{ activeDiagnosis.选中日志IDs.join(', ') }} ｜
          关联请求：{{ activeDiagnosis.关联请求标识.join(', ') }} ｜
          受理状态：{{ activeDiagnosis.受理状态 }}
        </p>
        <ul v-if="activeDiagnosis.过期缺失明细?.length" style="color: #b42318; font-size: 13px">
          <li v-for="item in activeDiagnosis.过期缺失明细" :key="item.日志ID">
            日志 {{ item.日志ID }}（{{ item.记录标识 }}）缺失范围：{{ item.缺失范围 }}
          </li>
        </ul>

        <table class="data-table" style="margin-top: 8px">
          <thead>
            <tr>
              <th>轮次</th>
              <th>日志ID</th>
              <th>请求/尝试</th>
              <th>版本/命中</th>
              <th>原耗时</th>
              <th>复跑耗时</th>
              <th>资料状态</th>
              <th>返回数据</th>
              <th>补回资料</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in activeDiagnosis.复跑记录" :key="String(run.id)">
              <td>{{ run.复跑轮次 }}</td>
              <td>{{ run.日志ID }}</td>
              <td>{{ run.请求标识 }} #{{ run.尝试序号 }}</td>
              <td>{{ run.采用版本 }} / {{ run.缓存命中 }}</td>
              <td>{{ run.原执行耗时ms }}ms</td>
              <td>{{ run.复跑耗时ms }}ms</td>
              <td>
                <span :class="run.资料状态 === '已过期' ? 'trend-down' : ''">{{ run.资料状态 }}</span>
              </td>
              <td style="max-width: 260px">
                <template v-if="run.返回数据.可用">
                  可用，{{ run.返回数据.返回行数 }} 行；样例 {{ run.返回数据.样例数据?.length ?? 0 }} 条
                </template>
                <template v-else>
                  <span class="trend-down">不可用：{{ run.返回数据.缺失范围 }}</span>
                </template>
              </td>
              <td>
                <button
                  v-if="run.资料状态 === '已过期'"
                  class="link"
                  type="button"
                  :data-testid="`restore-${run.日志ID}`"
                  @click="onRestore(run.日志ID)"
                >
                  补回原资料
                </button>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="page-actions" style="margin-top: 14px">
          <button class="btn primary" type="button" data-testid="modal-rerun" @click="onRerun(activeDiagnosis.id)">
            再复跑一轮
          </button>
          <button class="btn" type="button" @click="activeDiagnosis = null">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span v-if="message" :class="messageError ? 'error-text' : ''">{{ message }}</span>
      <span v-else>勾选实际执行记录后提交诊断；重试与不同请求按请求标识区分，不合并计算</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  getDiagnosis,
  listDiagnoses,
  listMetricDecisions,
  restoreMaterial,
  rerunDiagnosis,
  searchSlowHistory,
  submitDiagnosis,
  type DiagnosisRow,
  type MetricDecisionRow,
  type SlowHistoryRow,
} from '@/api/governance'

const filters = ref<{
  min_duration_ms: number | ''
  max_duration_ms: number | ''
  采用版本: string
  缓存命中: string
  口径期间: string
  资料状态: string
}>({
  min_duration_ms: '',
  max_duration_ms: '',
  采用版本: '',
  缓存命中: '',
  口径期间: '',
  资料状态: '',
})
const historyRows = ref<SlowHistoryRow[]>([])
const historyTotal = ref(0)
const decisions = ref<MetricDecisionRow[]>([])
const diagnoses = ref<DiagnosisRow[]>([])
const selectedIds = ref<number[]>([])
const submitting = ref(false)
const activeDiagnosis = ref<DiagnosisRow | null>(null)
const message = ref('')
const messageError = ref(false)

const expiredDiagnosisCount = computed(
  () => diagnoses.value.filter((item) => item.含过期资料 === '是').length,
)
const selectionHint = computed(() => {
  if (!selectedIds.value.length) return ''
  const picked = historyRows.value.filter((row) => selectedIds.value.includes(row.日志ID))
  const requests = new Set(picked.map((row) => row.请求标识))
  const expired = picked.filter((row) => row.资料状态 === '已过期').length
  return `选中 ${picked.length} 条执行记录，涉及 ${requests.size} 个请求${expired ? `，其中 ${expired} 条资料已过期（将标注缺失范围）` : ''}`
})

function flash(text: string, isError = false) {
  message.value = text
  messageError.value = isError
}

function resetFilters() {
  filters.value = {
    min_duration_ms: '',
    max_duration_ms: '',
    采用版本: '',
    缓存命中: '',
    口径期间: '',
    资料状态: '',
  }
  void reloadHistory()
}

async function reloadHistory() {
  try {
    const payload = await searchSlowHistory({
      min_duration_ms: filters.value.min_duration_ms === '' ? undefined : filters.value.min_duration_ms,
      max_duration_ms: filters.value.max_duration_ms === '' ? undefined : filters.value.max_duration_ms,
      采用版本: filters.value.采用版本,
      缓存命中: filters.value.缓存命中,
      口径期间: filters.value.口径期间,
      资料状态: filters.value.资料状态,
    })
    historyRows.value = payload.items
    historyTotal.value = payload.total
    selectedIds.value = selectedIds.value.filter((id) =>
      payload.items.some((row) => row.日志ID === id),
    )
  } catch (error) {
    flash(error instanceof Error ? error.message : '慢查历史读取失败', true)
  }
}

async function reloadDiagnoses() {
  const payload = await listDiagnoses()
  diagnoses.value = payload.items
}

async function onSubmitDiagnosis() {
  submitting.value = true
  try {
    const result = await submitDiagnosis([...selectedIds.value])
    if (!result.ok) {
      flash(result.message, true)
      return
    }
    if (result.duplicated) {
      flash(`该批执行记录已受理过，未重复建单（单号 ${result.diagnosis?.诊断单号 ?? ''}）`)
    } else {
      const expiredNote = result.expired_records?.length
        ? `；${result.expired_records.length} 条过期资料已标缺失范围`
        : ''
      flash(`${result.message}${expiredNote}`)
    }
    selectedIds.value = []
    await reloadDiagnoses()
  } catch (error) {
    flash(error instanceof Error ? error.message : '诊断提交失败', true)
  } finally {
    submitting.value = false
  }
}

async function openDiagnosis(id: number) {
  activeDiagnosis.value = await getDiagnosis(id)
}

async function onRerun(id: number) {
  try {
    const result = await rerunDiagnosis(id)
    flash(result.message)
    await reloadDiagnoses()
    if (activeDiagnosis.value?.id === id) {
      activeDiagnosis.value = await getDiagnosis(id)
    }
  } catch (error) {
    flash(error instanceof Error ? error.message : '复跑失败', true)
  }
}

async function onRestore(logId: number) {
  if (!activeDiagnosis.value) return
  try {
    const result = await restoreMaterial(activeDiagnosis.value.id, logId, '原始返回数据与执行计划快照')
    flash(result.message)
    activeDiagnosis.value = await getDiagnosis(activeDiagnosis.value.id)
    await Promise.all([reloadHistory(), reloadDiagnoses()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '资料补回失败', true)
  }
}

onMounted(async () => {
  await Promise.all([reloadHistory(), reloadDiagnoses(), listMetricDecisions().then((payload) => {
    decisions.value = payload.items
  })])
})
</script>
