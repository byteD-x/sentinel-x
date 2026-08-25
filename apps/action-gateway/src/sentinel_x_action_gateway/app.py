"""
Action Gateway — 独立最小权限动作执行器。

职责：
- 验证审批凭证（plan_hash、过期时间、幂等键）
- 在白名单目标上执行已登记的 Runbook
- 记录 before/after 状态
- 拒绝 R2/R3 和未经审批的动作

明确不负责：
- 调用 LLM
- 持有模型密钥
- 接受自由文本动作
- 读取 Secrets
- pods/exec
- 跨 namespace 操作
"""

from __future__ import annotations

import hashlib
import hmac
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sentinel_x_contracts import RiskLevel
from sentinel_x_domain.services import compute_plan_hash
from sentinel_x_action_gateway.approval_store import (
    ApprovalRecord,
    ApprovalStore,
    PostgresApprovalStore,
    TargetIdentity,
    build_approval_store,
)
from sentinel_x_action_gateway.executor import (
    ActionExecutionResult,
    ActionExecutor,
    FakeKubernetesApi,
    FakeKubernetesExecutor,
    FixtureActionExecutor,
)

logger = logging.getLogger("sentinel_x_action_gateway")


# ---------------------------------------------------------------------------
# 已登记的 Runbook 定义
# ---------------------------------------------------------------------------


@dataclass
class RunbookDefinition:
    """版本化、参数有界的 Runbook 定义。"""
    ref: str  # e.g. "restart_deployment@1"
    description: str
    risk_level: RiskLevel
    target_selector: str  # deployment 名称模式
    allowed_namespaces: list[str] = field(default_factory=lambda: ["demo-shop"])
    max_replicas: Optional[int] = None  # 仅 scale 类有效
    parameters_schema: dict = field(default_factory=dict)
    reversible: bool = True
    mvp_enabled: bool = True


# MVP 登记的 Runbook
REGISTERED_RUNBOOKS: dict[str, RunbookDefinition] = {
    "restart_deployment@1": RunbookDefinition(
        ref="restart_deployment@1",
        description="对指定 Deployment 执行滚动重启",
        risk_level=RiskLevel.R1,
        target_selector=r"^(order|inventory|payment)-(api|db|worker)$",
        parameters_schema={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "maxLength": 500},
            },
        },
        reversible=True,
        mvp_enabled=True,
    ),
    "scale_deployment@1": RunbookDefinition(
        ref="scale_deployment@1",
        description="在限定范围内调整 Deployment 副本数",
        risk_level=RiskLevel.R1,
        target_selector=r"^(order|inventory|payment)-(api|worker)$",
        max_replicas=10,
        parameters_schema={
            "type": "object",
            "properties": {
                "replicas": {"type": "integer", "minimum": 1, "maximum": 10},
                "reason": {"type": "string", "maxLength": 500},
            },
            "required": ["replicas"],
        },
        reversible=True,
        mvp_enabled=True,
    ),
}


# ---------------------------------------------------------------------------
# API 模型
# ---------------------------------------------------------------------------


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionSubmitRequest(StrictBaseModel):
    """动作提交请求 — 来自 Incident Worker。"""
    runbook_ref: str = Field(..., pattern=r"^[a-z_]+@\d+$")
    target: str = Field(..., min_length=1, max_length=253)
    parameters: dict = Field(default_factory=dict)
    idempotency_key: str = Field(..., min_length=16)
    plan_hash: str = Field(..., min_length=16)
    approval_id: str
    approval_token: str = Field(..., min_length=16)  # 短时审批凭证
    approval_expires_at: datetime
    incident_id: str
    audience: str = "sentinel-action-gateway"
    target_identity: TargetIdentity


class ActionStatusResponse(BaseModel):
    """动作状态响应。"""
    execution_id: str
    status: str  # pending | running | succeeded | failed | unknown | rejected
    runbook_ref: str
    target: str
    idempotency_key: str
    before_state: Optional[str] = None
    after_state: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_mode: str = "fixture"


class HealthResponse(BaseModel):
    status: str = "ok"
    actions_enabled: bool = False
    registered_runbooks: int = 0
    profile: str = "light"


# ---------------------------------------------------------------------------
# 动作执行存储
# ---------------------------------------------------------------------------


@dataclass
class StoredExecution:
    execution_id: str
    approval_id: str = ""
    incident_id: str = ""
    plan_id: str = ""
    status: str = "pending"
    runbook_ref: str = ""
    target: str = ""
    idempotency_key: str = ""
    before_state: Optional[str] = None
    after_state: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_mode: str = "fixture"
    target_identity: TargetIdentity | None = None
    target_resource_version: str = "unknown"


class ExecutionStore:
    """线程安全的执行记录存储。"""

    def __init__(self):
        self._executions: dict[str, StoredExecution] = {}
        self._idempotency_keys: set[str] = set()
        self._consumed_approval_ids: set[str] = set()
        self.claim_lock = asyncio.Lock()

    def check_idempotency(self, key: str) -> Optional[StoredExecution]:
        """检查幂等键是否重复。返回已有执行或 None。"""
        for exec_id, exec_data in self._executions.items():
            if exec_data.idempotency_key == key:
                return exec_data
        return None

    def is_approval_consumed(self, approval_id: str) -> bool:
        """审批只能用于登记一次动作。"""
        return approval_id in self._consumed_approval_ids

    def create(self, execution: StoredExecution) -> None:
        self._executions[execution.execution_id] = execution
        self._idempotency_keys.add(execution.idempotency_key)
        self._consumed_approval_ids.add(execution.approval_id)

    def get(self, execution_id: str) -> Optional[StoredExecution]:
        return self._executions.get(execution_id)

    def update(self, execution_id: str, **kwargs) -> Optional[StoredExecution]:
        execution = self._executions.get(execution_id)
        if execution:
            for key, value in kwargs.items():
                setattr(execution, key, value)
        return execution


class PostgresExecutionStore:
    """full profile 的 ActionExecution 持久化与幂等读取。"""

    def __init__(self, connect):
        if not callable(connect):
            raise TypeError("connect 必须是可调用的连接工厂")
        self._connect = connect
        self.claim_lock = asyncio.Lock()

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _record(row) -> StoredExecution:
        before = row[13] or {}
        after = row[15] or {}
        return StoredExecution(
            execution_id=str(row[0]), approval_id=str(row[3]), incident_id=str(row[1]),
            plan_id=str(row[2]), status=str(row[5]).lower(), runbook_ref=str(row[4]),
            target=str(row[8]), idempotency_key=str(row[7]),
            before_state=before.get("text") if isinstance(before, dict) else None,
            after_state=after.get("text") if isinstance(after, dict) else None,
            error=row[17], started_at=row[19], completed_at=row[20],
            execution_mode="fake-k8s" if row[13] and row[13].get("mode") == "fake-k8s" else "fixture",
            target_identity=TargetIdentity(
                namespace=str(row[9]), kind=str(row[10]), name=str(row[11]),
                uid=str(row[12]), generation=int(row[14]),
            ),
        )

    _SELECT = """
        SELECT id, incident_id, plan_id, approval_id, 'restart_deployment@1', status,
               idempotency_key_hash, idempotency_key_hash, target_name, target_namespace,
               target_kind, target_name, target_uid, before_state_ref,
               target_observed_generation, after_state_ref, after_state_hash,
               error_code, attempt_count, started_at, finished_at
        FROM action_executions
    """

    def _load(self, where: str, params: tuple):
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(self._SELECT + " WHERE " + where, params)
                row = cursor.fetchone()
                return self._record(row) if row else None
        finally:
            connection.close()

    def check_idempotency(self, key: str) -> StoredExecution | None:
        return self._load("idempotency_key_hash = %s", (self._hash(key),))

    def get(self, execution_id: str) -> StoredExecution | None:
        return self._load("id = %s", (execution_id,))

    def create(self, execution: StoredExecution) -> None:
        if not execution.target_identity:
            raise ValueError("PostgreSQL ActionExecution 缺少 target_identity")
        identity = execution.target_identity
        connection = self._connect()
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO action_executions(
                            id, incident_id, plan_id, approval_id, idempotency_key_hash,
                            status, target_namespace, target_kind, target_name, target_uid,
                            target_observed_generation, before_state_ref, started_at
                            , target_resource_version
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        """,
                        (
                            execution.execution_id, execution.incident_id, execution.plan_id,
                            execution.approval_id, self._hash(execution.idempotency_key),
                            execution.status.upper(), identity.namespace, identity.kind,
                            identity.name, identity.uid, identity.generation,
                            json.dumps({"text": execution.before_state, "mode": execution.execution_mode}),
                            execution.started_at, execution.target_resource_version,
                        ),
                    )
        finally:
            connection.close()

    def update(self, execution_id: str, **kwargs) -> StoredExecution | None:
        execution = self.get(execution_id)
        if execution is None:
            return None
        status = kwargs.get("status", execution.status).upper()
        connection = self._connect()
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE action_executions
                        SET status = %s, after_state_ref = %s::jsonb,
                            error_code = %s, finished_at = %s, version = version + 1
                        WHERE id = %s
                        """,
                        (
                            status,
                            json.dumps({"text": kwargs.get("after_state", execution.after_state)}),
                            kwargs.get("error", execution.error),
                            kwargs.get("completed_at", execution.completed_at), execution_id,
                        ),
                    )
        finally:
            connection.close()
        return self.get(execution_id)


# ---------------------------------------------------------------------------
# Gate — 核心校验逻辑
# ---------------------------------------------------------------------------


class ActionGate:
    """
    动作门控 — 提交动作前的全部校验。

    校验顺序（任一失败则拒绝）：
    1. Runbook 是否存在
    2. MVP 是否启用该 Runbook
    3. 风险等级是否合法（R2/R3 拒绝）
    4. 目标是否匹配白名单
    5. 参数是否符合 Schema
    6. Plan hash 是否与审批一致
    7. 审批是否过期
    8. 幂等键是否重复
    """

    def __init__(
        self,
        store: ExecutionStore,
        approval_store: ApprovalStore,
        kill_switch: bool = True,
        approval_ttl_minutes: int = 30,
        approval_token_secret: str | None = None,
        admin_token: str | None = None,
        executor: ActionExecutor | None = None,
    ):
        self.store = store
        self.approval_store = approval_store
        self.kill_switch = kill_switch
        self.approval_ttl_minutes = approval_ttl_minutes
        self.approval_token_secret = approval_token_secret
        self.admin_token = admin_token
        self.executor = executor or FixtureActionExecutor()

    def _expected_approval_token(self, approval: ApprovalRecord) -> str | None:
        if not self.approval_token_secret:
            return None
        canonical = "|".join((
            approval.approval_id,
            approval.incident_id,
            approval.plan_hash,
            approval.audience,
            approval.expires_at.astimezone(timezone.utc).isoformat(),
        ))
        return hmac.new(
            self.approval_token_secret.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _claim_mismatch(approval: ApprovalRecord, req: ActionSubmitRequest) -> str | None:
        claims = {
            "incident_id": (req.incident_id, approval.incident_id),
            "runbook_ref": (req.runbook_ref, approval.runbook_ref),
            "target": (req.target, approval.target),
            "parameters": (req.parameters, dict(approval.parameters)),
            "plan_hash": (req.plan_hash, approval.plan_hash),
            "audience": (req.audience, approval.audience),
            "approval_expires_at": (
                req.approval_expires_at.astimezone(timezone.utc),
                approval.expires_at.astimezone(timezone.utc),
            ),
            "target_identity": (req.target_identity, approval.target_identity),
        }
        for field_name, (received, expected) in claims.items():
            if received != expected:
                return f"审批记录与请求声明不一致: {field_name}"
        return None

    def validate(
        self, req: ActionSubmitRequest
    ) -> tuple[bool, str, Optional[RunbookDefinition], Optional[ApprovalRecord]]:
        """
        执行完整校验链。

        Returns:
            (allowed, reason, runbook_definition, approval_record)
        """
        approval = self.approval_store.get(req.approval_id)
        if approval is None:
            return False, "审批记录不存在", None, None

        claim_mismatch = self._claim_mismatch(approval, req)
        if claim_mismatch:
            return False, claim_mismatch, None, approval

        if approval.status != "approved":
            return False, f"审批状态不可执行: {approval.status}", None, approval

        # 0. Kill Switch
        if self.kill_switch:
            return False, "Kill Switch 已激活，拒绝所有动作", None, approval

        if approval.audience != "sentinel-action-gateway":
            return False, "审批凭证 audience 不匹配", None, approval

        if approval.expires_at.tzinfo is None or approval.expires_at.utcoffset() is None:
            return False, "审批过期时间必须包含时区", None, approval

        expected_token = self._expected_approval_token(approval)
        if not expected_token:
            return False, "Action Gateway 未配置审批凭证密钥", None, approval
        if not hmac.compare_digest(req.approval_token, expected_token):
            return False, "审批凭证无效", None, approval

        # 1. Runbook 存在性
        runbook = REGISTERED_RUNBOOKS.get(approval.runbook_ref)
        if not runbook:
            return False, f"未知 Runbook: {approval.runbook_ref}", None, approval

        # 2. MVP 启用检查
        if not runbook.mvp_enabled:
            return False, f"Runbook {approval.runbook_ref} 在 MVP 中未启用", None, approval

        # 3. 风险等级
        if runbook.risk_level == RiskLevel.R2:
            return False, "R2 操作在 MVP 中禁用，请升级人工处理", None, approval
        if runbook.risk_level == RiskLevel.R3:
            return False, "R3 操作永久禁止", None, approval

        if runbook.risk_level != approval.risk_level:
            return False, "审批记录风险等级与 Runbook 不一致", None, approval

        # 4. 目标白名单
        import re
        if not re.match(runbook.target_selector, approval.target):
            return False, (
                f"目标 '{approval.target}' 不在 Runbook {approval.runbook_ref} "
                f"的白名单范围内"
            ), None, approval

        # 5. 参数校验
        param_errors = self._validate_params(runbook, dict(approval.parameters))
        if param_errors:
            return False, f"参数校验失败: {'; '.join(param_errors)}", None, approval

        # 6. Plan hash 一致性（防止审批后计划被篡改）
        expected_hash = compute_plan_hash(
            approval.runbook_ref,
            approval.target,
            dict(approval.parameters),
            approval.incident_id,
        )
        if approval.plan_hash != expected_hash:
            return False, (
                f"Plan hash 不匹配。审批记录: {approval.plan_hash[:8]}..., "
                f"期望: {expected_hash[:8]}..."
            ), None, approval

        # 7. 审批有效期检查
        now = datetime.now(tz=approval.expires_at.tzinfo)
        if approval.expires_at <= now:
            return False, "审批凭证已过期", None, approval

        # 8. 幂等键重复检查
        existing = self.store.check_idempotency(req.idempotency_key)
        if existing:
            return False, (
                f"幂等键重复。已有执行: {existing.execution_id}, "
                f"状态: {existing.status}"
            ), None, approval

        if not self.approval_store.is_consumable(approval):
            return False, "审批凭证已被消费", None, approval

        return True, "校验通过", runbook, approval

    @staticmethod
    def _validate_params(runbook: RunbookDefinition, params: dict) -> list[str]:
        """验证参数是否符合 Runbook Schema。"""
        errors = []
        schema = runbook.parameters_schema
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for field in required:
            if field not in params:
                errors.append(f"缺少必填参数: {field}")

        for key, value in params.items():
            if key not in properties:
                errors.append(f"未知参数: {key}")
                continue
            prop = properties[key]
            expected_type = prop.get("type")
            if expected_type == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    errors.append(f"参数 {key} 应为整数")
                elif "minimum" in prop and value < prop["minimum"]:
                    errors.append(f"参数 {key} 小于最小值 {prop['minimum']}")
                elif "maximum" in prop and value > prop["maximum"]:
                    errors.append(f"参数 {key} 大于最大值 {prop['maximum']}")
            elif expected_type == "string":
                if not isinstance(value, str):
                    errors.append(f"参数 {key} 应为字符串")
                elif "minLength" in prop and len(value) < prop["minLength"]:
                    errors.append(f"参数 {key} 短于最小长度 {prop['minLength']}")
                elif "maxLength" in prop and len(value) > prop["maxLength"]:
                    errors.append(f"参数 {key} 超过最大长度 {prop['maxLength']}")

        return errors

    async def execute(
        self,
        runbook: RunbookDefinition,
        req: ActionSubmitRequest,
        approval: ApprovalRecord,
    ) -> StoredExecution:
        """
        执行 Runbook。

        执行器负责提供 before/after 状态；默认 light 使用 fixture，隔离
        测试可注入 fake Kubernetes 执行器。
        """
        if not self.approval_store.consume(approval):
            raise RuntimeError("审批凭证在执行前已被消费")

        execution_id = str(uuid4())
        started_at = datetime.now()

        try:
            before_state = self.executor.describe(req.target_identity)
        except Exception as error:  # noqa: BLE001 - 执行器边界需收敛为失败记录
            execution = StoredExecution(
                execution_id=execution_id,
                approval_id=req.approval_id,
                incident_id=req.incident_id,
                plan_id=approval.plan_id,
                status="failed",
                runbook_ref=req.runbook_ref,
                target=req.target,
                idempotency_key=req.idempotency_key,
                error=str(error),
                started_at=started_at,
                completed_at=datetime.now(),
                execution_mode=self.executor.execution_mode,
                target_identity=req.target_identity,
            )
            self.store.create(execution)
            return execution

        execution = StoredExecution(
            execution_id=execution_id,
            approval_id=req.approval_id,
            incident_id=req.incident_id,
            plan_id=approval.plan_id,
            status="running",
            runbook_ref=req.runbook_ref,
            target=req.target,
            idempotency_key=req.idempotency_key,
            before_state=before_state,
            started_at=started_at,
            execution_mode=self.executor.execution_mode,
            target_identity=req.target_identity,
        )
        self.store.create(execution)

        try:
            result: ActionExecutionResult = self.executor.execute(
                req.runbook_ref,
                req.target_identity,
                dict(req.parameters),
            )
        except Exception as error:  # noqa: BLE001 - 执行器边界需收敛为失败记录
            result = ActionExecutionResult(status="failed", error=str(error))

        self.store.update(
            execution_id,
            status=result.status,
            after_state=result.after_state,
            output=result.output,
            error=result.error,
            completed_at=datetime.now(),
        )

        return self.store.get(execution_id)


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------


def _build_runtime_execution_store():
    if os.getenv("SENTINEL_PROFILE", "light") != "full":
        return ExecutionStore()
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise RuntimeError("SENTINEL_PROFILE=full Action Gateway 缺少 PostgreSQL DATABASE_URL")
    try:
        psycopg = __import__("psycopg")
    except ImportError as exc:
        raise RuntimeError("SENTINEL_PROFILE=full Action Gateway 需要 psycopg") from exc
    return PostgresExecutionStore(lambda: psycopg.connect(database_url))


store = _build_runtime_execution_store()


def _build_runtime_approval_store():
    if os.getenv("SENTINEL_PROFILE", "light") != "full":
        return build_approval_store(os.getenv("SENTINEL_APPROVAL_STORE_DB"))
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise RuntimeError("SENTINEL_PROFILE=full Action Gateway 缺少 PostgreSQL DATABASE_URL")
    try:
        psycopg = __import__("psycopg")
    except ImportError as exc:
        raise RuntimeError("SENTINEL_PROFILE=full Action Gateway 需要 psycopg") from exc
    return PostgresApprovalStore(lambda: psycopg.connect(database_url))


approval_store = _build_runtime_approval_store()


def _build_executor() -> ActionExecutor:
    """按 profile 选择执行器；fake-k8s 只允许显式隔离环境开启。"""
    if os.getenv("SENTINEL_EXECUTION_MODE", "fixture") != "fake-k8s":
        return FixtureActionExecutor()
    api = FakeKubernetesApi()
    for name in ("order-api", "inventory-api", "payment-api", "order-worker", "inventory-worker", "payment-worker"):
        api.register_deployment(
            TargetIdentity(
                namespace="demo-shop",
                kind="Deployment",
                name=name,
                uid=f"fake-{name}",
                generation=1,
            )
        )
    return FakeKubernetesExecutor(api)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


gate = ActionGate(
    store=store,
    approval_store=approval_store,
    kill_switch=_env_bool("SENTINEL_KILL_SWITCH", True),
    approval_token_secret=os.getenv("SENTINEL_APPROVAL_TOKEN_SECRET"),
    admin_token=os.getenv("SENTINEL_ADMIN_TOKEN"),
    executor=_build_executor(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("SENTINEL_PROFILE", "light") == "full":
        connection = approval_store._connect
        database = connection()
        try:
            with database.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise RuntimeError("Action Gateway PostgreSQL health check 返回异常")
        finally:
            database.close()
    yield


app = FastAPI(
    title="Sentinel-X Action Gateway",
    version="0.1.0",
    description="独立最小权限动作执行器 — 不持有模型密钥，不调用 LLM",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        actions_enabled=not gate.kill_switch and bool(gate.approval_token_secret),
        registered_runbooks=len(REGISTERED_RUNBOOKS),
    )


@app.post("/api/actions", status_code=status.HTTP_202_ACCEPTED)
async def submit_action(req: ActionSubmitRequest):
    """
    提交已审批的动作。

    所有提交必须经过 Gate 校验链：
    Runbook 存在 → MVP 启用 → R1 合法 → 目标白名单
    → 参数合规 → Plan hash 一致 → 幂等键唯一
    """
    async with store.claim_lock:
        allowed, reason, runbook, approval = gate.validate(req)
        if not allowed:
            logger.warning(f"动作被拒绝: {reason}")
            raise HTTPException(status_code=400, detail=reason)

        assert runbook is not None and approval is not None
        execution = await gate.execute(runbook, req, approval)

    return {
        "execution_id": execution.execution_id,
        "status": execution.status,
        "runbook_ref": execution.runbook_ref,
        "target": execution.target,
        "idempotency_key": execution.idempotency_key,
        "execution_mode": execution.execution_mode,
        "message": f"{execution.execution_mode} 执行器已提交；真实 Kubernetes 写操作仍未开放",
    }


@app.get("/api/actions/{execution_id}")
async def get_action_status(execution_id: str):
    """查询动作执行状态。"""
    execution = store.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail=f"执行 {execution_id} 不存在")
    return ActionStatusResponse(
        execution_id=execution.execution_id,
        status=execution.status,
        runbook_ref=execution.runbook_ref,
        target=execution.target,
        idempotency_key=execution.idempotency_key,
        before_state=execution.before_state,
        after_state=execution.after_state,
        output=execution.output,
        error=execution.error,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        execution_mode=execution.execution_mode,
    )


@app.get("/api/runbooks")
async def list_runbooks():
    """列出所有已登记的 Runbook。"""
    return {
        "items": [
            {
                "ref": rb.ref,
                "description": rb.description,
                "risk_level": rb.risk_level.value,
                "reversible": rb.reversible,
                "mvp_enabled": rb.mvp_enabled,
            }
            for rb in REGISTERED_RUNBOOKS.values()
        ]
    }


@app.post("/api/admin/kill-switch")
async def toggle_kill_switch(
    activate: bool = True,
    admin_token: Optional[str] = Header(default=None, alias="X-Sentinel-Admin-Token"),
):
    """管理端点：切换 Kill Switch。"""
    if not gate.admin_token or not admin_token or not hmac.compare_digest(admin_token, gate.admin_token):
        raise HTTPException(status_code=403, detail="需要有效的运维管理凭证")
    gate.kill_switch = activate
    return {
        "kill_switch": gate.kill_switch,
        "message": f"Kill Switch 已{'激活' if activate else '关闭'}",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8081)
