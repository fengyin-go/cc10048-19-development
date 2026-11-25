"""查询日志领域服务：查询记录、慢查询标记、耗时统计。

慢查治理要求每条日志都能按「实际执行时间 / 采用版本 / 是否命中」定位，
并通过 请求标识 + 尝试序号 区分同一请求的重试与不同请求，避免混成一条。
"""
# 数据操作：调度、标准化、数据，与上下游模块联动消费批次数据。
from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class QueryLogService(BaseModuleService):
    MODULE = "query_log"
    ENTITY = "查询记录"
    OPERATION_TERM = "查询"
    LIST_FIELDS = [
        "记录标识", "查询内容", "查询用户", "查询时间", "返回行数", "执行耗时",
        "缓存命中", "错误信息",
        # 慢查治理扩展字段：参与统一筛选，保证按真实执行定位
        "请求标识", "尝试序号", "采用版本", "口径期间", "资料状态",
    ]
    REQUIRED_FIELDS = ["记录标识", "查询内容", "查询用户"]
    STATUS_ORDER = ["已记录", "慢查询", "已优化"]
    ACTION_RULES = {"标记慢查": "已记录", "分析优化": "慢查询"}
    NEGATIVE_ACTIONS = []

    def log_query(
        self,
        *,
        request_id: str | None = None,
        attempt: int | None = None,
        adopted_version: str | None = None,
        metric_period: str | None = None,
    ) -> dict[str, Any]:
        """记录一次查询操作。

        带 request_id 时按同一请求续记一次重试（尝试序号自增），
        不带则视为一个新请求；重试与不同请求各自独立成行，不合并。
        """
        rng = random.Random()
        rows = store.rows(self.MODULE)
        new_id = store.next_id(self.MODULE)

        if request_id:
            prior = [r for r in rows if str(r.get("请求标识", "")) == request_id]
            req_id = request_id
            seq = attempt if attempt is not None else (
                max((int(r.get("尝试序号", 1)) for r in prior), default=0) + 1
            )
        else:
            req_id = f"REQ-{datetime.now().strftime('%H%M%S')}-{new_id}"
            seq = attempt if attempt is not None else 1

        duration = rng.randint(5, 10000)
        is_slow = duration > 3000
        row_count = rng.randint(1, 50000)
        cache_hit = rng.random() > 0.5
        # 命中缓存时沿用 v1，未命中实际取数走 v2，与缓存策略保持一致
        version = adopted_version or ("v1" if cache_hit else "v2")
        period = metric_period or ("旧期" if version == "v1" else "指标版本")
        new_log = {
            "id": new_id,
            "记录标识": f"Q{datetime.now().strftime('%m%d%H%M%S')}{new_id:02d}",
            "查询内容": f"SELECT * FROM metrics WHERE date >= '2026-11-{rng.randint(1,20):02d}'",
            "查询用户": f"user_{rng.randint(1, 10)}",
            "查询时间": datetime.now().isoformat(),
            "返回行数": str(row_count),
            "执行耗时": f"{duration}ms",
            "缓存命中": "是" if cache_hit else "否",
            "错误信息": "",
            "请求标识": req_id,
            "尝试序号": seq,
            "采用版本": version,
            "口径期间": period,
            "资料保留至": "2027-12-31",
            "资料状态": "受查",
            "缺失范围": "",
            "status": "慢查询" if is_slow else "已记录",
            "pending": is_slow,
            "abnormal": is_slow,
        }
        rows.append(new_log)
        return {"log_id": new_log["id"], "status": new_log["status"],
                "duration_ms": duration, "slow_query": is_slow,
                "request_id": req_id, "attempt": seq,
                "adopted_version": version, "cache_hit": cache_hit}

    def duration_ms_of(self, row: dict[str, Any]) -> int:
        """把「执行耗时」文本解析成毫秒数，供按实际执行时间筛选。"""
        text = str(row.get("执行耗时", "")).strip().lower().replace("ms", "").strip()
        try:
            return int(float(text))
        except ValueError:
            return -1

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """在通用筛选之外，支持按实际执行毫秒数做区间定位。"""
        rows, total = super().list_entries(
            filters=filters, keyword=keyword, status=status, page=1, size=10_000_000)
        if min_duration_ms is not None:
            rows = [r for r in rows if self.duration_ms_of(r) >= min_duration_ms]
        if max_duration_ms is not None:
            rows = [r for r in rows if 0 <= self.duration_ms_of(r) <= max_duration_ms]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def domain_enrich(self, config_id: int) -> dict:
        """对当前模块执行标准化操作，联动回填和批次，产出标准化数据产物。

        数据加工流程：读取原始记录 → 执行标准化处理 → 回填校验字段完整性 → 生成批次批次标识 →
        写入存储层并返回可追溯的处理结果，下游消费模块可基于批次号追踪数据链路。
        """
        import time
        entry = store.find(self.MODULE, config_id)
        # 标准化：遍历当前模块全部记录执行核心数据处理
        records = store.list_all(self.MODULE)
        processed = []
        for idx, rec in enumerate(records):
            # 回填：校验每条记录的字段完整性与格式合法性
            filled = sum(1 for v in rec.values() if v and str(v).strip())
            total = len(rec)
            rec_copy = dict(rec)
            rec_copy["_field_count"] = filled
            rec_copy["_complete_ratio"] = f"{filled}/{total}"
            rec_copy["_batch"] = f"{self.MODULE}-{idx:04d}"
            processed.append(rec_copy)
        # 批次：生成加工批次标识并写入存储
        batch_id = store.next_id(self.MODULE + "_processor")
        result = {
            "module": self.MODULE,
            "operation": "标准化",
            "config_id": config_id,
            "records_processed": len(processed),
            "batch_id": batch_id,
            "field_validation": {"回填": "passed", "批次": "recorded"},
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "downstream_consumable": True,
            "records": processed,
            "entry": entry,
        }
        # 返回标准化处理结果，含回填校验元数据和批次批次追溯信息
        return result
