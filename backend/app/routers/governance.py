"""慢查口径治理路由：影响样本检索、诊断受理、实际复跑与资料补回。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import PageResult
from app.services.query_governance import QueryGovernanceService

router = APIRouter(prefix="/api/governance", tags=["慢查治理"])

service = QueryGovernanceService()


def _history_filters(request: Request) -> dict[str, str]:
    """只保留慢查历史真实存在的筛选字段，按执行记录逐条过滤。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.HISTORY_FIELDS and value.strip()
    }


@router.get("/slow-history", response_model=PageResult[dict])
def search_slow_history(
    request: Request,
    min_duration_ms: int | None = Query(default=None, ge=0),
    max_duration_ms: int | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """慢查历史影响样本：按实际执行时间、采用版本、是否命中筛选。"""
    items, total = service.search_slow_history(
        filters=_history_filters(request),
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/metric-decisions")
def list_metric_decisions(request: Request) -> dict[str, Any]:
    """指标决策数据：口径版本、口径期间与数据源，供影响样本关联。"""
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.DECISION_FIELDS and value.strip()
    }
    items = service.list_decisions(filters)
    return {"items": items, "total": len(items)}


@router.get("/diagnoses")
def list_diagnoses() -> dict[str, Any]:
    """诊断单列表。"""
    items = service.list_diagnoses()
    return {"items": items, "total": len(items)}


@router.get("/diagnoses/{diagnosis_id}")
def get_diagnosis(diagnosis_id: int) -> dict[str, Any]:
    """诊断详情：追溯的原请求执行记录与历次实际复跑流水。"""
    result = service.get_diagnosis(diagnosis_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"诊断单 {diagnosis_id} 不存在")
    return result


@router.post("/diagnoses")
def submit_diagnosis(payload: dict[str, Any]) -> dict[str, Any]:
    """按实际选中的执行记录提交诊断；同一批选中记录只受理一次。"""
    raw_ids = payload.get("log_ids") or payload.get("logIds") or []
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=400, detail="log_ids 必须是执行记录 ID 数组")
    try:
        log_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="执行记录 ID 必须为整数")
    return service.submit_diagnosis(
        log_ids,
        operator=str(payload.get("operator") or "值班员"),
        remark=str(payload.get("remark") or ""),
    )


@router.post("/diagnoses/{diagnosis_id}/rerun")
def rerun_diagnosis(diagnosis_id: int) -> dict[str, Any]:
    """对诊断追溯的每条执行记录实际复跑一次，记录耗时与返回数据。"""
    result = service.rerun_diagnosis(diagnosis_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/diagnoses/{diagnosis_id}/restore/{log_id}")
def restore_material(
    diagnosis_id: int, log_id: int, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """补回诊断追溯执行记录的原资料，补回后可重新复跑并核对实际领取。"""
    if service.get_diagnosis(diagnosis_id) is None:
        raise HTTPException(status_code=404, detail=f"诊断单 {diagnosis_id} 不存在")
    scope = str((payload or {}).get("restored_scope") or "")
    result = service.restore_material(diagnosis_id, log_id, scope)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/diagnoses/{diagnosis_id}/impact-sample")
def governance_impact_sample(diagnosis_id: int) -> dict[str, Any]:
    """可重跑影响样本：关联诊断请求、数据源与每次实际复跑结果。"""
    result = service.governance_impact_sample(diagnosis_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result
