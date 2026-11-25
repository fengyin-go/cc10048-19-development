"""跨模块业务链路接口：指标计算、AB实验、用户分析、监控交付、口径治理。"""
from __future__ import annotations

import random
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from app.compute import (
    aggregate, anomaly_iqr, anomaly_zscore, cache_hit_simulation,
    chi_square_test, compute_calibrate_bias, compute_freshness_delay,
    generate_mock_metric_values, random_sample, segment_diff_report, t_test,
)
from app.store import store

router = APIRouter(prefix="/api/chains", tags=["业务链路"])


# ---- 链路1：指标口径→预聚合任务→多维查询→查询缓存 ----
@router.get("/metric-aggregate/{metric_id}")
def chain_metric_query(metric_id: int) -> dict[str, Any]:
    """指标定义→预聚合→多维查询→缓存的完整指标计算查询链路。"""
    metric = store.find("metric_def", metric_id)
    if not metric:
        raise HTTPException(404, f"指标定义 {metric_id} 不存在")

    # Step 1: 读取指标口径
    method = metric.get("聚合粒度", "sum")
    formula_value = generate_mock_metric_values(30, base=100.0)
    aggregated = aggregate(formula_value, method if method in ("sum", "avg", "mean", "max", "min", "count", "count_distinct", "median", "stddev") else "sum")

    # Step 2: 查找关联预聚合任务
    agg_jobs = [row for row in store.rows("aggregate_job")
                if str(row.get("目标指标", "")).find(str(metric.get("指标标识", ""))) >= 0]
    job_results = []
    for job in agg_jobs[:3]:
        job_results.append({
            "job_id": job.get("id"),
            "job_name": job.get("任务标识"),
            "dimension": job.get("聚合维度", "未指定"),
            "granularity": job.get("统计粒度", "天"),
            "last_exec": job.get("上次执行", "N/A"),
            "row_count": random.randint(1000, 500000),
        })

    # Step 3: 构建多维查询方案
    dim_queries = [row for row in store.rows("dim_query")
                   if str(row.get("查询指标", "")).find(str(metric.get("指标名称", ""))) >= 0]
    query_results = []
    for q in dim_queries[:3]:
        query_results.append({
            "query_id": q.get("id"),
            "query_name": q.get("方案标识"),
            "dim_row": q.get("维度行", "N/A"),
            "dim_col": q.get("维度列", "N/A"),
            "filter_cond": q.get("筛选条件", "无"),
            "mock_rows": random.randint(5, 500),
        })

    # Step 4: 查询缓存命中模拟
    cache_policies = [row for row in store.rows("query_cache")
                      if str(row.get("关联查询", "")).find(str(metric.get("指标名称", ""))) >= 0 or True]
    cache_results = []
    for cp in cache_policies[:3]:
        cache_results.append(cache_hit_simulation(
            f"metric_{metric_id}_dim_all", 3600,
            str(cp.get("上次刷新", "")) if cp.get("上次刷新") else None
        ))

    return {
        "chain": "指标计算查询链路",
        "metric": {"id": metric_id, "name": metric.get("指标名称"), "method": method},
        "aggregated_value": round(aggregated, 4),
        "sample_size": len(formula_value),
        "pre_aggregation_jobs": job_results,
        "dimension_queries": query_results,
        "cache_simulation": cache_results,
    }


# ---- 链路2：实验管理→显著性检验→数据采样 ----
@router.get("/experiment-evaluate/{experiment_id}")
def chain_experiment_evaluate(experiment_id: int) -> dict[str, Any]:
    """实验→显著性检验→采样的AB实验评估链路。"""
    exp = store.find("experiment", experiment_id)
    if not exp:
        raise HTTPException(404, f"实验方案 {experiment_id} 不存在")

    # Step 1: 模拟对照组和实验组数据
    rng = random.Random(experiment_id * 7 + 13)
    n_control = int(str(exp.get("样本比例", "50")).replace("%", "").strip() or 50) if str(exp.get("样本比例", "50")).isdigit() else 50
    n_experiment = 100 - n_control
    control_data = [rng.gauss(100, 15) for _ in range(max(5, n_control))]
    experiment_data = [rng.gauss(102, 15) for _ in range(max(5, n_experiment))]

    # Step 2: 执行显著性检验
    sig_tasks = [row for row in store.rows("significance")
                 if str(row.get("关联实验", "")).find(str(exp.get("实验名称", ""))) >= 0]
    significance_results = []
    for task in sig_tasks[:2]:
        method = task.get("检验方法", "t_test")
        try:
            confidence = float(str(task.get("置信水平", "0.95")).replace("%", "").strip()) / 100
        except (ValueError, TypeError):
            confidence = 0.95
        alpha = 1 - confidence
        if "chi" in str(method).lower() or "卡方" in str(method):
            result = chi_square_test(
                [sum(control_data) / len(control_data), sum(experiment_data) / len(experiment_data)],
                [sum(control_data) / len(control_data)] * 2,
                alpha=alpha
            )
        else:
            result = t_test(control_data, experiment_data, alpha=alpha)
        significance_results.append({
            "task_id": task.get("id"),
            "task_name": task.get("任务标识"),
            "method": result.get("method"),
            "result": result,
        })

    # Step 3: 数据采样
    sampling_configs = [row for row in store.rows("data_sample")][:2]
    sampling_results = []
    all_data = [{"value": v, "group": "control"} for v in control_data] + \
               [{"value": v, "group": "experiment"} for v in experiment_data]
    for sc in sampling_configs:
        method = sc.get("采样方法", "random")
        try:
            ratio_str = str(sc.get("采样比例", "0.5"))
            if "%" in ratio_str:
                ratio = float(ratio_str.replace("%", "").strip()) / 100
            else:
                ratio = min(float(ratio_str or 0.5), 1.0)
        except (ValueError, TypeError):
            ratio = 0.5
        try:
            seed = int(str(sc.get("种子值", "42")).replace("-", "")) if str(sc.get("种子值", "42")).replace("-", "").isdigit() else 42
        except (ValueError, TypeError):
            seed = 42
        sampled = random_sample(all_data, method, ratio, seed)
        sampling_results.append({
            "config_id": sc.get("id"),
            "config_name": sc.get("配置标识"),
            "method": method,
            "ratio": ratio,
            "sampled_count": len(sampled),
            "total_count": len(all_data),
        })

    return {
        "chain": "AB实验评估链路",
        "experiment": {"id": experiment_id, "name": exp.get("实验名称"),
                       "control_group": exp.get("对照组"), "experiment_group": exp.get("实验组")},
        "descriptive_stats": {
            "control": {"n": len(control_data), "mean": round(sum(control_data) / len(control_data), 4) if control_data else 0},
            "experiment": {"n": len(experiment_data), "mean": round(sum(experiment_data) / len(experiment_data), 4) if experiment_data else 0},
        },
        "significance_tests": significance_results,
        "data_sampling": sampling_results,
    }


# ---- 链路3：人群圈选→分群对比→下钻分析 ----
@router.get("/cohort-analysis/{cohort_id}")
def chain_cohort_analysis(cohort_id: int) -> dict[str, Any]:
    """人群圈选→分群对比→下钻分析的用户分析链路。"""
    cohort = store.find("cohort", cohort_id)
    if not cohort:
        raise HTTPException(404, f"人群分群 {cohort_id} 不存在")

    # Step 1: 模拟人群分群数据
    rng = random.Random(cohort_id + 42)
    cohort_size = rng.randint(5000, 500000)
    metric_values = generate_mock_metric_values(30, base=rng.uniform(80, 120))

    # Step 2: 分群对比
    compare_plans = [row for row in store.rows("segment_compare")
                     if str(row.get("分群A") or "").find(str(cohort.get("分群名称", ""))) >= 0
                     or str(row.get("分群B") or "").find(str(cohort.get("分群名称", ""))) >= 0]
    compare_results = []
    for plan in compare_plans[:3]:
        seg_a_data = generate_mock_metric_values(20, base=rng.uniform(90, 110))
        seg_b_data = generate_mock_metric_values(20, base=rng.uniform(85, 105))
        diff_report = segment_diff_report(seg_a_data, seg_b_data)
        compare_results.append({
            "plan_id": plan.get("id"),
            "plan_name": plan.get("方案标识"),
            "seg_b_name": plan.get("分群B"),
            "diff_report": diff_report,
        })

    # Step 3: 下钻分析
    drill_paths = [row for row in store.rows("drill_down")
                   if str(row.get("起始指标", "")).find(str(cohort.get("分群名称", ""))) >= 0 or True][:3]
    drill_results = []
    dims = ["地域", "设备", "渠道", "年龄组", "会员等级"]
    for dp in drill_paths:
        dim_data = {d: rng.uniform(10, 200) for d in random.sample(dims, k=min(4, len(dims)))}
        drill_results.append({
            "path_id": dp.get("id"),
            "path_name": dp.get("路径标识"),
            "dimension": dp.get("下钻维度", "未指定"),
            "depth": dp.get("层级深度", "1"),
            "decomposition": {
                "total": round(sum(dim_data.values()), 4),
                "by_dimension": dim_data,
            },
        })

    return {
        "chain": "用户分析链路",
        "cohort": {
            "id": cohort_id, "name": cohort.get("分群名称"),
            "tag": cohort.get("圈选条件"), "estimated_size": cohort_size,
        },
        "metric_timeline": metric_values[:10],
        "segment_comparisons": compare_results,
        "drill_down_analysis": drill_results,
    }


# ---- 链路4：异常检测→数据时效→数据导出 ----
@router.get("/monitor-delivery/{rule_id}")
def chain_monitor_delivery(rule_id: int) -> dict[str, Any]:
    """异常检测→数据时效→导出的监控交付链路。"""
    rule = store.find("anomaly_detect", rule_id)
    if not rule:
        raise HTTPException(404, f"检测规则 {rule_id} 不存在")

    # Step 1: 异常检测
    rng = random.Random(rule_id * 31 + 7)
    metric_data = generate_mock_metric_values(60, base=100.0, noise=15.0)
    # 注入一些异常
    for i in random.sample(range(len(metric_data)), k=max(1, len(metric_data) // 10)):
        metric_data[i] = metric_data[i] * rng.uniform(2.5, 4.0) if rng.random() > 0.5 else metric_data[i] * -0.5

    algo = rule.get("检测算法", "iqr")
    if "zscore" in str(algo).lower() or "z-score" in str(algo).lower():
        anomaly_result = anomaly_zscore(metric_data, threshold=2.5)
    else:
        anomaly_result = anomaly_iqr(metric_data, multiplier=2.0)

    # Step 2: 数据时效检查
    freshness_configs = [row for row in store.rows("data_freshness")][:3]
    freshness_results = []
    for fc in freshness_configs:
        expected = int(str(fc.get("期望时效", "24")).replace("h", "").replace("小时", "").strip()) if str(fc.get("期望时效", "24")).replace("h", "").strip().isdigit() else 24
        result = compute_freshness_delay(expected, str(fc.get("上次检查", "")))
        freshness_results.append({
            "config_id": fc.get("id"),
            "source": fc.get("数据来源"),
            "expected_hours": expected,
            "result": result,
        })

    # Step 3: 数据导出
    export_tasks = [row for row in store.rows("data_export")][:3]
    export_results = []
    for et in export_tasks:
        fmt = et.get("导出格式", "csv")
        export_results.append({
            "task_id": et.get("id"),
            "task_name": et.get("任务标识"),
            "format": fmt,
            "field_selection": et.get("字段筛选", "全部"),
            "estimated_rows": rng.randint(100, 50000),
            "estimated_size_mb": round(rng.uniform(0.1, 50.0), 2),
        })

    return {
        "chain": "监控交付链路",
        "anomaly_rule": {"id": rule_id, "name": rule.get("规则标识"),
                         "metric": rule.get("关联指标"), "level": rule.get("告警级别")},
        "anomaly_detection": anomaly_result,
        "data_freshness": freshness_results,
        "data_export": export_results,
    }


# ---- 链路5：指标校准→数据服务→查询日志 ----
@router.get("/calibrate-governance/{calibrate_id}")
def chain_calibrate_governance(calibrate_id: int) -> dict[str, Any]:
    """指标校准→数据服务→查询日志的口径治理链路。"""
    cal = store.find("metric_calibrate", calibrate_id)
    if not cal:
        raise HTTPException(404, f"校准记录 {calibrate_id} 不存在")

    # Step 1: 计算校准偏差
    original = float(str(cal.get("原口径值", "100")).replace(",", "")) if str(cal.get("原口径值", "100")).replace(",", "").replace(".", "").replace("-", "").isdigit() else 100.0
    new_val = float(str(cal.get("新口径值", "105")).replace(",", "")) if str(cal.get("新口径值", "105")).replace(",", "").replace(".", "").replace("-", "").isdigit() else 105.0
    bias = compute_calibrate_bias(original, new_val)

    # Step 2: 数据服务接口影响
    data_services = [row for row in store.rows("data_service")
                     if str(row.get("关联指标", "")).find(str(cal.get("校准指标", ""))) >= 0 or True][:3]
    service_impacts = []
    for ds in data_services:
        service_impacts.append({
            "service_id": ds.get("id"),
            "path": ds.get("接口路径"),
            "metric": ds.get("关联指标"),
            "cache_ttl": ds.get("缓存秒数"),
            "impact": "需更新返回字段值" if abs(bias["bias_pct"]) > 1 else "偏差小于1%，无需操作",
        })

    # Step 3: 查询日志追溯——基于真实执行记录与可重跑影响样本，不再随机造数
    from app.services.query_log import QueryLogService
    log_service = QueryLogService()
    query_logs = store.rows("query_log")
    log_analysis = []
    for log in query_logs:
        duration_ms = log_service.duration_ms_of(log)
        log_analysis.append({
            "log_id": log.get("id"),
            "记录标识": log.get("记录标识"),
            "请求标识": log.get("请求标识"),
            "尝试序号": log.get("尝试序号"),
            "query_user": log.get("查询用户"),
            "query_time": log.get("查询时间"),
            "duration_ms": duration_ms,
            "adopted_version": log.get("采用版本"),
            "metric_period": log.get("口径期间"),
            "cache_hit": log.get("缓存命中") == "是",
            "row_count": log.get("返回行数"),
            "material_status": log.get("资料状态"),
            "missing_scope": log.get("缺失范围") or "",
        })

    measured = [item["duration_ms"] for item in log_analysis if item["duration_ms"] >= 0]
    avg_duration = round(sum(measured) / len(measured), 2) if measured else 0
    return {
        "chain": "口径治理链路",
        "calibration": {
            "id": calibrate_id, "metric": cal.get("校准指标"),
            "reason": cal.get("校准原因"), "calib_time": cal.get("生效时间"),
        },
        "bias_analysis": bias,
        "data_service_impact": service_impacts,
        "query_log_analysis": {
            "logs": log_analysis,
            "avg_duration_ms": avg_duration,
            "total_logs": len(query_logs),
            "expired_material_logs": [
                {"log_id": item["log_id"], "missing_scope": item["missing_scope"]}
                for item in log_analysis if item["material_status"] == "已过期"
            ],
            "governance_note": "按实际执行记录追溯；过期资料仅登记缺失范围，不得以新口径值冒充旧值",
        },
    }


# ---- 综合主链：触发一次完整的数据工程链路 ----
@router.get("/pipeline-full")
def chain_pipeline_full() -> dict[str, Any]:
    """触发完整数据工程管线：指标计算→实验评估→分析→监控→治理。"""
    start = time.time()

    metrics = store.rows("metric_def")
    experiments = store.rows("experiment")
    cohorts = store.rows("cohort")
    rules = store.rows("anomaly_detect")
    calibrations = store.rows("metric_calibrate")

    # 对每个领域取第一个记录触发链路
    metric_result = chain_metric_query(int(metrics[0]["id"])) if metrics else None
    exp_result = chain_experiment_evaluate(int(experiments[0]["id"])) if experiments else None
    cohort_result = chain_cohort_analysis(int(cohorts[0]["id"])) if cohorts else None
    monitor_result = chain_monitor_delivery(int(rules[0]["id"])) if rules else None
    calib_result = chain_calibrate_governance(int(calibrations[0]["id"])) if calibrations else None

    elapsed = time.time() - start
    return {
        "pipeline": "完整数据工程管线",
        "elapsed_seconds": round(elapsed, 3),
        "modules_processed": 18,
        "chains_executed": 5,
        "metric_query": metric_result,
        "experiment_evaluate": exp_result,
        "cohort_analysis": cohort_result,
        "monitor_delivery": monitor_result,
        "calibrate_governance": calib_result,
    }