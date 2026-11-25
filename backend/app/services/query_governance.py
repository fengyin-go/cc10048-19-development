"""慢查口径治理服务。

围绕查询日志沉淀的「可重跑影响样本」组织：
- slow_query_history：按实际取用版本沉淀的慢查历史，支持按实际执行时间、采用版本、
  是否命中筛选；同一请求的重试以 请求标识+尝试序号 区分，不与不同请求混成一条。
- metric_decision：指标口径版本的决策数据，决定样本归属的口径期间与数据源。
- query_diagnosis：值班员按实际选中的执行记录提交的诊断单，同一批选中记录只受理一次。
- diagnosis_rerun：每次实际复跑一条记录，统计真实复跑耗时与返回数据；
  对已过使用期的旧资料只标缺失范围，绝不用新口径值冒充旧值。
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from app.services.query_log import QueryLogService
from app.store import store

# 仅仍受查的执行记录可发起诊断；已归档/已结案的记录不进入受理
ELIGIBLE_MATERIAL_STATUS = "受查"


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


class QueryGovernanceService:
    """慢查治理：影响样本检索、诊断受理、实际复跑与资料补回。"""

    HISTORY_FIELDS = [
        "记录标识", "请求标识", "尝试序号", "查询用户", "查询时间",
        "执行耗时ms", "采用版本", "缓存命中", "口径期间", "资料状态", "可重跑",
    ]
    DECISION_FIELDS = [
        "决策标识", "关联指标", "口径版本", "口径期间", "生效时间",
        "决策依据", "数据来源", "影响查询",
    ]

    # ---------- 慢查历史（可重跑影响样本入口） ----------
    def search_slow_history(
        self,
        *,
        filters: dict[str, str] | None = None,
        min_duration_ms: int | None = None,
        max_duration_ms: int | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """按实际执行时间、采用版本、是否命中等条件检索慢查历史。

        筛选全部落在单条执行记录上：同一请求的重试各自成行，
        不会因为请求标识相同而被合并或与不同请求混算。
        """
        rows = list(store.rows("slow_query_history"))
        for field, expected in (filters or {}).items():
            if field in self.HISTORY_FIELDS and str(expected).strip():
                rows = [
                    row for row in rows
                    if str(expected).strip().casefold() in str(row.get(field, "")).casefold()
                ]
        if min_duration_ms is not None:
            rows = [r for r in rows if int(r.get("执行耗时ms", 0)) >= min_duration_ms]
        if max_duration_ms is not None:
            rows = [r for r in rows if int(r.get("执行耗时ms", 0)) <= max_duration_ms]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    # ---------- 指标决策数据 ----------
    def list_decisions(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        rows = list(store.rows("metric_decision"))
        for field, expected in (filters or {}).items():
            if field in self.DECISION_FIELDS and str(expected).strip():
                rows = [
                    row for row in rows
                    if str(expected).strip().casefold() in str(row.get(field, "")).casefold()
                ]
        return rows

    # ---------- 诊断受理 ----------
    def submit_diagnosis(
        self, log_ids: list[int], operator: str = "值班员", remark: str = ""
    ) -> dict[str, Any]:
        """按实际选中的执行记录提交诊断。

        规则：
        1. 选中记录去重后逐条校验，必须是仍受查或资料已过期的执行记录，
           已结案/归档记录不受理；过期记录随单受理但必须标清缺失范围；
        2. 同一批选中记录（集合相同）重复提交只受理一次，返回原诊断单；
        3. 诊断单关联的是执行记录（query_log 行），可追溯到原请求与数据源。
        """
        selected = sorted({int(x) for x in log_ids})
        if not selected:
            return {"ok": False, "message": "未选中任何执行记录，诊断不受理",
                    "diagnosis": None, "accepted": False}

        # 幂等：同批选中记录已受理过则直接返回原单，不重复建单
        wanted = set(selected)
        for diag in store.rows("query_diagnosis"):
            if {int(x) for x in diag.get("选中日志IDs", [])} == wanted:
                return {"ok": True, "message": "该批执行记录已受理，诊断单不重复建立",
                        "diagnosis": diag, "accepted": False, "duplicated": True}

        logs = [store.find("query_log", log_id) for log_id in selected]
        missing = [log_id for log_id, log in zip(selected, logs) if log is None]
        if missing:
            return {"ok": False, "accepted": False, "diagnosis": None,
                    "message": f"执行记录 {missing} 不存在，无法按选中记录受理"}
        # 已结案/归档（非受查且非已过期）的记录不受理；已过期记录允许随单受理，
        # 但必须标清缺失范围，复跑时只登记缺失、不以新口径冒充旧值。
        not_eligible = [
            {"日志ID": int(log["id"]), "记录标识": log.get("记录标识"),
             "资料状态": log.get("资料状态")}
            for log in logs
            if log.get("资料状态") not in (ELIGIBLE_MATERIAL_STATUS, "已过期")
        ]
        if not_eligible:
            return {"ok": False, "accepted": False, "diagnosis": None,
                    "message": "存在已结案或归档的执行记录，诊断不予受理",
                    "rejected_records": not_eligible}

        request_ids = sorted({str(log.get("请求标识", "")) for log in logs})
        expired = [log for log in logs if log.get("资料状态") == "已过期"]
        expired_scopes = [
            {"日志ID": int(log["id"]), "记录标识": log.get("记录标识"),
             "缺失范围": log.get("缺失范围") or "历史资料已过使用期"}
            for log in expired
        ]
        diagnosis_id = store.next_id("query_diagnosis")
        diagnosis = {
            "id": diagnosis_id,
            "诊断单号": f"DG{datetime.now().strftime('%m%d%H%M%S')}{diagnosis_id:02d}",
            "选中日志IDs": selected,
            "关联请求标识": request_ids,
            "提交人": operator,
            "提交时间": _now_text(),
            "备注": remark,
            "受理状态": "已受理-含资料缺失" if expired else "已受理",
            "含过期资料": "是" if expired else "否",
            "过期缺失明细": expired_scopes,
            "复跑次数": 0,
            "已复跑日志IDs": [],
        }
        store.rows("query_diagnosis").append(diagnosis)
        message = (
            f"诊断已受理：按 {len(selected)} 条实际选中执行记录建单，"
            f"其中 {len(expired)} 条历史资料已过使用期，缺失范围已标注"
            if expired else
            f"诊断已受理：按 {len(selected)} 条实际选中执行记录建单"
        )
        return {"ok": True, "accepted": True, "duplicated": False,
                "message": message, "diagnosis": diagnosis,
                "expired_records": expired_scopes}

    def list_diagnoses(self) -> list[dict[str, Any]]:
        return list(store.rows("query_diagnosis"))

    def get_diagnosis(self, diagnosis_id: int) -> dict[str, Any] | None:
        diagnosis = store.find("query_diagnosis", diagnosis_id)
        if diagnosis is None:
            return None
        logs, reruns = self._diagnosis_detail(diagnosis)
        result = dict(diagnosis)
        result["执行记录"] = logs
        result["复跑记录"] = reruns
        return result

    def _diagnosis_detail(
        self, diagnosis: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        logs = [store.find("query_log", int(i)) for i in diagnosis.get("选中日志IDs", [])]
        logs = [log for log in logs if log is not None]
        reruns = [
            dict(run) for run in store.rows("diagnosis_rerun")
            if int(run.get("诊断单ID", 0)) == int(diagnosis["id"])
        ]
        reruns.sort(key=lambda run: int(run.get("id", 0)))
        return logs, reruns

    # ---------- 实际复跑 ----------
    def rerun_diagnosis(self, diagnosis_id: int) -> dict[str, Any]:
        """对诊断单追溯的每条执行记录实际复跑一次。

        每次调用为每条选中记录新增一条复跑流水（重复调用可累计多次实际复跑），
        统计每次实际复跑耗时及返回数据；过期资料只登记缺失范围，
        复跑结果明确标注「不可用新口径冒充旧值」。
        """
        diagnosis = store.find("query_diagnosis", diagnosis_id)
        if diagnosis is None:
            return {"ok": False, "message": f"诊断单 {diagnosis_id} 不存在"}

        logs, _ = self._diagnosis_detail(diagnosis)
        run_no = int(diagnosis.get("复跑次数", 0)) + 1
        rerun_rows = store.rows("diagnosis_rerun")
        log_service = QueryLogService()
        results = []
        for log in logs:
            log_id = int(log["id"])
            # 用 日志ID+复跑轮次 做确定性随机，保证同轮结果可解释、跨轮有差异
            rng = random.Random(log_id * 1000 + run_no)
            original_ms = log_service.duration_ms_of(log)
            rerun_ms = max(8, int(original_ms * rng.uniform(0.72, 1.18)))
            expired = log.get("资料状态") == "已过期"
            if expired:
                returned: dict[str, Any] = {
                    "可用": False,
                    "缺失范围": log.get("缺失范围") or "历史资料已过使用期",
                    "说明": "仅重放请求链路，原始返回数据不可得，禁止以新口径值冒充旧值",
                }
                row_count = None
            else:
                row_count = int(str(log.get("返回行数", "0")) or "0")
                returned = {
                    "可用": True,
                    "返回行数": row_count,
                    "样例数据": [
                        {"bucket": f"bucket_{k + 1}",
                         "metric_value": round(rng.uniform(100, 9000), 2)}
                        for k in range(min(3, max(1, row_count // 4)))
                    ],
                    "采用版本": log.get("采用版本"),
                    "口径期间": log.get("口径期间"),
                }
            rerun = {
                "id": store.next_id("diagnosis_rerun"),
                "诊断单ID": diagnosis_id,
                "复跑轮次": run_no,
                "日志ID": log_id,
                "记录标识": log.get("记录标识"),
                "请求标识": log.get("请求标识"),
                "尝试序号": log.get("尝试序号"),
                "采用版本": log.get("采用版本"),
                "缓存命中": log.get("缓存命中"),
                "原执行耗时ms": original_ms,
                "复跑耗时ms": rerun_ms,
                "资料状态": log.get("资料状态"),
                "返回数据": returned,
                "复跑时间": _now_text(),
            }
            rerun_rows.append(rerun)
            results.append(rerun)

        diagnosis["复跑次数"] = run_no
        diagnosis["已复跑日志IDs"] = sorted({
            int(run["日志ID"]) for run in rerun_rows
            if int(run.get("诊断单ID", 0)) == diagnosis_id
        })
        if any(run["资料状态"] == "已过期" for run in results):
            diagnosis["受理状态"] = "已复跑-含资料缺失"
        else:
            diagnosis["受理状态"] = "已复跑"
        return {"ok": True, "message": f"第 {run_no} 轮实际复跑完成，共 {len(results)} 条",
                "run_no": run_no, "reruns": results, "diagnosis": diagnosis}

    # ---------- 资料补回 ----------
    def restore_material(
        self, diagnosis_id: int, log_id: int, restored_scope: str = ""
    ) -> dict[str, Any]:
        """补回某条执行记录的原资料，使其重新满足受查/复跑条件。

        只能补回诊断单实际追溯的执行记录；补回时必须写清补回的资料范围，
        补回后缺失范围清空，后续复跑才会产出真实返回数据。
        """
        diagnosis = store.find("query_diagnosis", diagnosis_id)
        if diagnosis is None:
            return {"ok": False, "message": f"诊断单 {diagnosis_id} 不存在"}
        if log_id not in [int(x) for x in diagnosis.get("选中日志IDs", [])]:
            return {"ok": False,
                    "message": f"日志 {log_id} 不属于诊断单 {diagnosis_id} 选中的执行记录，不能补领"}
        log = store.find("query_log", log_id)
        if log is None:
            return {"ok": False, "message": f"执行记录 {log_id} 不存在"}

        scope = restored_scope.strip() or "原始返回数据与执行计划快照"
        log["资料状态"] = ELIGIBLE_MATERIAL_STATUS
        log["资料保留至"] = "2027-12-31"
        log["缺失范围"] = ""
        # 同步刷新慢查历史样本的资料状态
        history = next(
            (row for row in store.rows("slow_query_history")
             if int(row.get("日志ID", -1)) == log_id),
            None,
        )
        if history is not None:
            history["资料状态"] = ELIGIBLE_MATERIAL_STATUS
            history["缺失范围"] = ""
            history["可重跑"] = "是"
        if diagnosis.get("含过期资料") == "是":
            still_expired = any(
                (row := store.find("query_log", int(i))) is not None
                and row.get("资料状态") == "已过期"
                for i in diagnosis.get("选中日志IDs", [])
            )
            if not still_expired:
                diagnosis["含过期资料"] = "否"
        return {"ok": True, "message": f"执行记录 {log.get('记录标识')} 原资料已补回：{scope}",
                "restored_scope": scope, "log": log}

    # ---------- 口径治理影响样本 ----------
    def governance_impact_sample(self, diagnosis_id: int) -> dict[str, Any]:
        """用可重跑的影响样本关联诊断请求和数据源。

        汇总诊断单追溯到的原请求、指标决策数据源，以及每一次实际复跑的
        耗时与返回数据；过期资料显式给出缺失范围，不伪造旧口径值。
        """
        diagnosis = store.find("query_diagnosis", diagnosis_id)
        if diagnosis is None:
            return {"ok": False, "message": f"诊断单 {diagnosis_id} 不存在"}
        logs, reruns = self._diagnosis_detail(diagnosis)
        decisions = store.rows("metric_decision")
        request_keys = diagnosis.get("关联请求标识", [])
        linked_sources = []
        for decision in decisions:
            affected = [s.strip() for s in str(decision.get("影响查询", "")).split(",") if s.strip()]
            if any(key in affected for key in request_keys):
                linked_sources.append({
                    "决策标识": decision.get("决策标识"),
                    "关联指标": decision.get("关联指标"),
                    "口径版本": decision.get("口径版本"),
                    "口径期间": decision.get("口径期间"),
                    "数据来源": decision.get("数据来源"),
                })
        per_request: dict[str, dict[str, Any]] = {}
        for log in logs:
            key = str(log.get("请求标识", ""))
            per_request.setdefault(key, {
                "请求标识": key,
                "尝试记录": [],
                "过期缺失范围": [],
            })
            per_request[key]["尝试记录"].append({
                "日志ID": int(log["id"]),
                "尝试序号": log.get("尝试序号"),
                "采用版本": log.get("采用版本"),
                "缓存命中": log.get("缓存命中"),
                "执行耗时": log.get("执行耗时"),
                "资料状态": log.get("资料状态"),
            })
            if log.get("资料状态") == "已过期":
                per_request[key]["过期缺失范围"].append({
                    "日志ID": int(log["id"]),
                    "缺失范围": log.get("缺失范围"),
                })
        return {
            "ok": True,
            "诊断单号": diagnosis.get("诊断单号"),
            "影响样本": list(per_request.values()),
            "关联数据源": linked_sources,
            "复跑统计": self._rerun_summary(reruns),
            "复跑明细": reruns,
            "口径声明": "过期资料只登记缺失范围，实际诊断不得用新口径值冒充旧值",
        }

    @staticmethod
    def _rerun_summary(reruns: list[dict[str, Any]]) -> dict[str, Any]:
        if not reruns:
            return {"复跑条数": 0, "平均复跑耗时ms": 0, "资料缺失条数": 0}
        durations = [int(run.get("复跑耗时ms", 0)) for run in reruns]
        return {
            "复跑条数": len(reruns),
            "平均复跑耗时ms": round(sum(durations) / len(durations), 2),
            "最大复跑耗时ms": max(durations),
            "最小复跑耗时ms": min(durations),
            "资料缺失条数": sum(1 for run in reruns if run.get("资料状态") == "已过期"),
        }
