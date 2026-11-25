"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS

# 18 个对外业务模块；慢查治理的 4 张内部表（慢查历史、指标决策、诊断单、复跑流水）
# 是查询日志的子领域数据，不计入业务模块总数与运营概览。
BUSINESS_MODULE_KEYS: tuple[str, ...] = (
    "metric_def", "dim_query", "experiment", "significance", "cohort",
    "data_service", "anomaly_detect", "analysis_chart", "aggregate_job",
    "drill_down", "data_export", "data_freshness", "query_cache",
    "segment_compare", "metric_calibrate", "query_log", "data_sample",
    "report_schedule",
)


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name in BUSINESS_MODULE_KEYS)

    def business_module_count(self) -> int:
        return len(BUSINESS_MODULE_KEYS)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        """返回该表下一个自增主键（内存仓库的统一发号口）。"""
        return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    def list_all(self, module: str) -> list[dict[str, Any]]:
        """返回整张表的快照列表，供领域服务做全量统计与重跑样本检索。"""
        return list(self.rows(module))

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
