"""慢查口径治理测试：影响样本、诊断受理幂等、实际复跑与过期资料缺失标注。

覆盖两条业务场景：
1. 同一次筛选找到两个查询尝试（v1 缓存命中 / v2 实际取数），值班员选中两条提交诊断，
   重新提交同一选中集合只受理一次，并能比较诊断与其追溯的原请求。
2. 选中一条仍受查记录与一条历史资料已过使用期的记录发起诊断，补回其中一条原资料后
   重试复跑，核对实际领取；过期资料只标缺失范围，不用新口径冒充旧值。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.query_governance import QueryGovernanceService
from app.services.query_log import QueryLogService
from app.store import store

client = TestClient(app)

EXPIRED_SCOPE = "原始返回数据与执行计划已过使用期，仅可重放请求，不能以新口径值冒充旧值"


@pytest.fixture(autouse=True)
def reset_governance_tables():
    """每个用例前清空诊断单与复跑流水，并恢复种子场景的过期记录。"""
    store.rows("query_diagnosis").clear()
    store.rows("diagnosis_rerun").clear()
    expired = store.find("query_log", 6)
    if expired and expired.get("资料状态") != "已过期":
        expired["资料状态"] = "已过期"
        expired["资料保留至"] = "2026-11-05"
        expired["缺失范围"] = EXPIRED_SCOPE
        history = next(
            (row for row in store.rows("slow_query_history")
             if int(row.get("日志ID", -1)) == 6),
            None,
        )
        if history:
            history["资料状态"] = "已过期"
            history["缺失范围"] = EXPIRED_SCOPE
            history["可重跑"] = "受限"
    yield


class TestSlowHistorySearch:
    def test_seed_scenario_rows_present(self):
        rows = store.rows("slow_query_history")
        assert len(rows) == 4
        assert {row["请求标识"] for row in rows} == {"REQ-S100", "REQ-S200", "REQ-S300"}

    def test_filter_by_adopted_version(self):
        resp = client.get("/api/governance/slow-history", params={"采用版本": "v2"})
        data = resp.json()
        assert data["total"] == 3
        assert all(item["采用版本"] == "v2" for item in data["items"])

    def test_filter_by_cache_hit(self):
        resp = client.get("/api/governance/slow-history", params={"缓存命中": "是"})
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["记录标识"] == "QL1125093001"

    def test_filter_by_metric_period(self):
        resp = client.get("/api/governance/slow-history", params={"口径期间": "旧期"})
        data = resp.json()
        assert data["total"] == 2
        assert {item["请求标识"] for item in data["items"]} == {"REQ-S100", "REQ-S200"}

    def test_filter_by_duration_range(self):
        resp = client.get(
            "/api/governance/slow-history",
            params={"min_duration_ms": 4000, "max_duration_ms": 5000},
        )
        data = resp.json()
        assert data["total"] == 2
        assert all(4000 <= item["执行耗时ms"] <= 5000 for item in data["items"])
        # 只给下界：5210ms 的过期记录也进入样本，共 3 条
        resp_all = client.get(
            "/api/governance/slow-history",
            params={"min_duration_ms": 4000},
        )
        assert resp_all.json()["total"] == 3

    def test_same_request_retries_kept_distinct(self):
        """同一请求 REQ-S100 的两次尝试必须是两条独立执行记录，不能混成一条。"""
        resp = client.get("/api/governance/slow-history", params={"请求标识": "REQ-S100"})
        data = resp.json()
        assert data["total"] == 2
        assert sorted(item["尝试序号"] for item in data["items"]) == [1, 2]
        assert {item["采用版本"] for item in data["items"]} == {"v1", "v2"}

    def test_query_log_endpoint_supports_governance_filters(self):
        resp = client.get(
            "/api/query_log",
            params={"采用版本": "v2", "缓存命中": "否", "min_duration_ms": 4000},
        )
        data = resp.json()
        assert data["total"] >= 2
        for item in data["items"]:
            assert item["采用版本"] == "v2"
            assert item["缓存命中"] == "否"


class TestMetricDecisions:
    def test_list_decisions(self):
        resp = client.get("/api/governance/metric-decisions")
        assert resp.json()["total"] == 2

    def test_filter_decisions_by_period(self):
        resp = client.get("/api/governance/metric-decisions", params={"口径期间": "旧期"})
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["决策标识"] == "MD-ACTIVE-20260915"


class TestScenarioOneDiagnosisWithTwoAttempts:
    """场景一：同一筛选命中两个查询尝试，选中两条提交诊断。"""

    def test_submit_two_selected_attempts(self):
        resp = client.post("/api/governance/diagnoses", json={"log_ids": [4, 5]})
        data = resp.json()
        assert data["ok"] is True
        assert data["accepted"] is True
        diagnosis = data["diagnosis"]
        assert diagnosis["选中日志IDs"] == [4, 5]
        assert diagnosis["关联请求标识"] == ["REQ-S100"]
        assert diagnosis["含过期资料"] == "否"

    def test_resubmit_same_selection_accepted_once(self):
        """重新提交这份诊断时按实际选中的执行记录只受理一次。"""
        first = client.post("/api/governance/diagnoses", json={"log_ids": [4, 5]}).json()
        second = client.post("/api/governance/diagnoses", json={"log_ids": [5, 4]}).json()
        assert first["accepted"] is True
        assert second["accepted"] is False
        assert second["duplicated"] is True
        assert second["diagnosis"]["id"] == first["diagnosis"]["id"]
        assert len(store.rows("query_diagnosis")) == 1

    def test_different_selection_creates_separate_diagnosis(self):
        client.post("/api/governance/diagnoses", json={"log_ids": [4, 5]})
        another = client.post("/api/governance/diagnoses", json={"log_ids": [5, 7]}).json()
        assert another["accepted"] is True
        assert len(store.rows("query_diagnosis")) == 2

    def test_diagnosis_compares_with_original_request(self):
        """诊断详情能比较诊断本身与其追溯的原请求执行记录。"""
        diagnosis = client.post(
            "/api/governance/diagnoses", json={"log_ids": [4, 5]}
        ).json()["diagnosis"]
        detail = client.get(f"/api/governance/diagnoses/{diagnosis['id']}").json()
        assert detail["诊断单号"] == diagnosis["诊断单号"]
        assert len(detail["执行记录"]) == 2
        assert {row["请求标识"] for row in detail["执行记录"]} == {"REQ-S100"}
        # 两条执行记录的版本与命中可直接对比
        pairs = [
            (row["采用版本"], row["缓存命中"], row["尝试序号"])
            for row in detail["执行记录"]
        ]
        assert ("v1", "是", 1) in pairs
        assert ("v2", "否", 2) in pairs

    def test_empty_or_nonexistent_selection_rejected(self):
        assert client.post("/api/governance/diagnoses", json={"log_ids": []}).json()["ok"] is False
        assert client.post(
            "/api/governance/diagnoses", json={"log_ids": [99999]}
        ).json()["ok"] is False


class TestScenarioTwoExpiredMaterial:
    """场景二：选中一条受查记录（5）+ 一条过期记录（6）发起诊断。"""

    def test_expired_record_accepted_with_missing_scope_marked(self):
        data = client.post(
            "/api/governance/diagnoses", json={"log_ids": [5, 6]}
        ).json()
        assert data["ok"] is True
        assert data["accepted"] is True
        expired = data["expired_records"]
        assert len(expired) == 1
        assert expired[0]["日志ID"] == 6
        assert "过使用期" in expired[0]["缺失范围"]
        diagnosis = data["diagnosis"]
        assert diagnosis["含过期资料"] == "是"
        assert diagnosis["受理状态"] == "已受理-含资料缺失"

    def test_rerun_marks_expired_data_unavailable_without_faking(self):
        """过期记录复跑只登记缺失范围，不返回伪造的新口径数据。"""
        diagnosis = client.post(
            "/api/governance/diagnoses", json={"log_ids": [5, 6]}
        ).json()["diagnosis"]
        rerun = client.post(
            f"/api/governance/diagnoses/{diagnosis['id']}/rerun"
        ).json()
        assert len(rerun["reruns"]) == 2
        by_log = {run["日志ID"]: run for run in rerun["reruns"]}

        healthy = by_log[5]
        assert healthy["返回数据"]["可用"] is True
        assert healthy["返回数据"]["样例数据"]

        expired_run = by_log[6]
        assert expired_run["资料状态"] == "已过期"
        assert expired_run["返回数据"]["可用"] is False
        assert "缺失范围" in expired_run["返回数据"]
        assert "样例数据" not in expired_run["返回数据"]
        assert "禁止以新口径" in expired_run["返回数据"]["说明"]
        # 诊断单状态保留缺失标记
        assert rerun["diagnosis"]["受理状态"] == "已复跑-含资料缺失"

    def test_restore_material_then_rerun_picks_up_real_data(self):
        """补回过期记录的原资料后重试复跑，核对实际领取到返回数据。"""
        diagnosis = client.post(
            "/api/governance/diagnoses", json={"log_ids": [5, 6]}
        ).json()["diagnosis"]
        diag_id = diagnosis["id"]

        # 第一轮复跑：6 号资料缺失
        first = client.post(f"/api/governance/diagnoses/{diag_id}/rerun").json()
        assert first["reruns"][1]["返回数据"]["可用"] is False

        # 补回 6 号原资料（只能补本诊断单实际选中的记录）
        restore = client.post(
            f"/api/governance/diagnoses/{diag_id}/restore/6",
            json={"restored_scope": "原始返回数据与执行计划快照"},
        )
        assert restore.status_code == 200
        assert store.find("query_log", 6)["资料状态"] == "受查"
        assert store.find("query_log", 6)["缺失范围"] == ""

        # 不能跨诊断单补领未选中的记录
        other = client.post(
            "/api/governance/diagnoses", json={"log_ids": [4, 5]}
        ).json()["diagnosis"]
        cross = client.post(
            f"/api/governance/diagnoses/{other['id']}/restore/6",
            json={"restored_scope": "x"},
        )
        assert cross.status_code == 400

        # 第二轮复跑：6 号领到真实返回数据
        second = client.post(f"/api/governance/diagnoses/{diag_id}/rerun").json()
        assert second["run_no"] == 2
        run6 = next(run for run in second["reruns"] if run["日志ID"] == 6)
        assert run6["资料状态"] == "受查"
        assert run6["返回数据"]["可用"] is True
        assert run6["返回数据"]["样例数据"], "补回资料后复跑必须实际领取返回数据"
        assert second["diagnosis"]["受理状态"] == "已复跑"
        assert second["diagnosis"]["含过期资料"] == "否"

    def test_restore_unknown_diagnosis_returns_404(self):
        resp = client.post("/api/governance/diagnoses/99999/restore/6", json={})
        assert resp.status_code == 404


class TestRerunAndImpactSample:
    def test_rerun_records_real_duration_and_data(self):
        diagnosis = client.post(
            "/api/governance/diagnoses", json={"log_ids": [4, 5]}
        ).json()["diagnosis"]
        data = client.post(
            f"/api/governance/diagnoses/{diagnosis['id']}/rerun"
        ).json()
        assert len(data["reruns"]) == 2
        for run in data["reruns"]:
            assert run["复跑耗时ms"] > 0
            assert run["返回数据"]["可用"] is True
            assert run["采用版本"] in {"v1", "v2"}
        assert store.rows("query_diagnosis")[0]["复跑次数"] == 1

    def test_rerun_accumulates_each_actual_run(self):
        diagnosis = client.post(
            "/api/governance/diagnoses", json={"log_ids": [4, 5]}
        ).json()["diagnosis"]
        diag_id = diagnosis["id"]
        client.post(f"/api/governance/diagnoses/{diag_id}/rerun")
        client.post(f"/api/governance/diagnoses/{diag_id}/rerun")
        detail = client.get(f"/api/governance/diagnoses/{diag_id}").json()
        assert detail["复跑次数"] == 2
        assert len(detail["复跑记录"]) == 4
        assert {run["复跑轮次"] for run in detail["复跑记录"]} == {1, 2}

    def test_impact_sample_links_request_datasource_and_reruns(self):
        diagnosis = client.post(
            "/api/governance/diagnoses", json={"log_ids": [4, 5]}
        ).json()["diagnosis"]
        client.post(f"/api/governance/diagnoses/{diagnosis['id']}/rerun")
        data = client.get(
            f"/api/governance/diagnoses/{diagnosis['id']}/impact-sample"
        ).json()
        assert data["ok"] is True
        assert len(data["影响样本"]) == 1
        assert data["影响样本"][0]["请求标识"] == "REQ-S100"
        assert len(data["影响样本"][0]["尝试记录"]) == 2
        sources = {item["决策标识"] for item in data["关联数据源"]}
        assert "MD-GMV-20261101" in sources
        assert data["复跑统计"]["复跑条数"] == 2
        assert data["复跑统计"]["平均复跑耗时ms"] > 0
        assert "口径声明" in data

    def test_impact_sample_expired_scope_visible(self):
        diagnosis = client.post(
            "/api/governance/diagnoses", json={"log_ids": [5, 6]}
        ).json()["diagnosis"]
        client.post(f"/api/governance/diagnoses/{diagnosis['id']}/rerun")
        data = client.get(
            f"/api/governance/diagnoses/{diagnosis['id']}/impact-sample"
        ).json()
        request_s200 = next(
            sample for sample in data["影响样本"] if sample["请求标识"] == "REQ-S200"
        )
        assert len(request_s200["过期缺失范围"]) == 1
        assert request_s200["过期缺失范围"][0]["日志ID"] == 6
        assert data["复跑统计"]["资料缺失条数"] == 1

    def test_unknown_diagnosis_endpoints_404(self):
        assert client.post("/api/governance/diagnoses/99999/rerun").status_code == 404
        assert client.get("/api/governance/diagnoses/99999").status_code == 404
        assert client.get(
            "/api/governance/diagnoses/99999/impact-sample"
        ).status_code == 404


class TestQueryLoggingIdentity:
    def test_retry_same_request_uses_incrementing_attempt(self):
        svc = QueryLogService()
        first = svc.log_query(request_id="REQ-UT-1")
        second = svc.log_query(request_id="REQ-UT-1")
        assert first["request_id"] == "REQ-UT-1"
        assert second["attempt"] == first["attempt"] + 1
        assert second["log_id"] != first["log_id"]

    def test_new_request_gets_own_identity(self):
        svc = QueryLogService()
        one = svc.log_query()
        two = svc.log_query()
        assert one["request_id"] != two["request_id"]
        assert one["attempt"] == 1 and two["attempt"] == 1

    def test_cache_hit_implies_v1_miss_implies_v2(self):
        svc = QueryLogService()
        for idx in range(10):
            result = svc.log_query(request_id=f"REQ-VERSION-{idx}")
            if result["cache_hit"]:
                assert result["adopted_version"] == "v1"
            else:
                assert result["adopted_version"] == "v2"
