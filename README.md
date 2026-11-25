# 多维指标分析与实验评估平台

面向业务指标口径管理、多维分析查询、AB实验评估、分群圈选和数据服务发布的分析应用平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/views/GovernanceView.vue     慢查治理工作台（影响样本/诊断/复跑）
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py    通用查询/导出/登记/动作接口
│   ├── app/routers/governance.py  慢查治理：影响样本、诊断受理、实际复跑
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/query_governance.py  慢查口径治理领域服务
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 慢查口径治理

查询日志的每条执行记录都带 `请求标识 + 尝试序号`，同一请求的重试与不同请求各自独立成行，
并补充 `采用版本`（v1 缓存口径 / v2 实际取数）、`缓存命中`、`口径期间`、`资料状态` 与 `缺失范围`，
支持按实际执行毫秒数区间、采用版本、是否命中筛选定位慢查。

独立的「慢查治理」工作台（路由 `/query_governance`，接口前缀 `/api/governance`）：

- `GET /slow-history`：慢查历史影响样本，按实际执行时间、采用版本、是否命中、口径期间检索；
- `GET /metric-decisions`：指标决策数据（口径版本、口径期间、数据来源）；
- `POST /diagnoses`：按实际选中的执行记录提交诊断，同一批选中记录只受理一次（幂等）；
- `POST /diagnoses/{id}/rerun`：对诊断追溯的每条执行记录实际复跑，逐次统计真实复跑耗时与返回数据；
- `POST /diagnoses/{id}/restore/{log_id}`：补回原资料后重新复跑并核对实际领取；
- `GET /diagnoses/{id}/impact-sample`：可重跑影响样本，关联诊断请求、数据源与历次复跑结果。

已过使用期的旧资料随单受理时必须标清缺失范围，复跑只登记缺失、不产出伪造返回，
实际诊断不得以新口径值冒充旧值；补回原资料后下一轮复跑才会领取真实返回数据。

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8012/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5176/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8012`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标口径 | `metric_def` | 指标定义 | 指标标识、指标名称、计算公式 |
| 多维查询 | `dim_query` | 查询方案 | 方案标识、查询指标、维度行 |
| 实验管理 | `experiment` | 实验方案 | 方案标识、实验名称、对照组 |
| 显著性检验 | `significance` | 检验任务 | 任务标识、关联实验、检验方法 |
| 人群圈选 | `cohort` | 人群分群 | 分群标识、分群名称、圈选条件 |
| 数据服务 | `data_service` | 服务接口 | 接口标识、关联指标、接口路径 |
| 异常检测 | `anomaly_detect` | 检测规则 | 规则标识、关联指标、检测算法 |
| 分析图表 | `analysis_chart` | 图表配置 | 图表标识、数据来源、图表类型 |
| 预聚合任务 | `aggregate_job` | 聚合任务 | 任务标识、目标指标、聚合维度 |
| 下钻分析 | `drill_down` | 下钻路径 | 路径标识、起始指标、下钻维度 |
| 数据导出 | `data_export` | 导出任务 | 任务标识、查询方案、导出格式 |
| 数据时效 | `data_freshness` | 时效检查 | 检查标识、数据来源、期望时效 |
| 查询缓存 | `query_cache` | 缓存策略 | 策略标识、关联查询、缓存键 |
| 分群对比 | `segment_compare` | 对比方案 | 方案标识、分群A、分群B |
| 指标校准 | `metric_calibrate` | 校准记录 | 记录标识、校准指标、原口径值 |
| 查询日志 | `query_log` | 查询记录 | 记录标识、查询内容、查询用户、请求标识、尝试序号、采用版本、缓存命中、资料状态 |
| 数据采样 | `data_sample` | 采样配置 | 配置标识、数据来源、采样方法 |
| 报告调度 | `report_schedule` | 报告任务 | 任务标识、报告内容、接收人 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据分析与数据应用
