"""多 Agent 协调调度器 — 任务分配、状态管理、消息总线."""

from __future__ import annotations

import uuid
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from src.agents.architect_agent import ArchitectAgent, ExecutionPlan
from src.agents.environment_agent import EnvironmentAgent, EnvironmentContext
from src.agents.executor_agent import ExecutorAgent, ExecutionResult
from src.utils.logger import get_logger, TokenCounter

logger = get_logger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    PLANNING = "planning"
    ENV_SETUP = "env_setup"
    EXECUTING = "executing"
    SELF_HEALING = "self_healing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskContext:
    """跨 Agent 共享的任务上下文."""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_intent: str = ""
    status: TaskStatus = TaskStatus.PENDING
    plan: Optional[ExecutionPlan] = None
    env: Optional[EnvironmentContext] = None
    result: Optional[ExecutionResult] = None
    history: list[dict] = field(default_factory=list)
    token_counter: TokenCounter = field(default_factory=TokenCounter)
    created_at: float = field(default_factory=time.time)

    def record(self, event: str, detail: dict | None = None) -> None:
        self.history.append({
            "ts": time.time(),
            "event": event,
            "detail": detail or {},
        })


class Orchestrator:
    """Geo-OpenClaw 主调度器.

    协调 Architect → Environment → Executor 三 Agent 流水线，
    管理共享上下文，处理异常升级。
    """

    def __init__(
        self,
        llm_client: Any = None,
        max_retries: int = 3,
        on_progress: Callable[[str, TaskStatus], None] | None = None,
    ):
        self.llm_client = llm_client
        self.max_retries = max_retries
        self.on_progress = on_progress

        self.architect = ArchitectAgent(llm_client=llm_client)
        self.environment = EnvironmentAgent()
        self.executor = ExecutorAgent(max_retries=max_retries)

        self._lock = threading.Lock()

    def run(self, user_intent: str) -> ExecutionResult:
        """执行完整的 GIS 自动化流水线.

        Parameters
        ----------
        user_intent : str
            自然语言描述的地理处理任务，例如:
            "将 D:/data/ 下所有 .tif 文件重投影到 EPSG:3857，
             并按 study_area.shp 的范围裁剪"

        Returns
        -------
        ExecutionResult
            包含成功状态、输出路径列表、Token消耗、执行历史的结构化结果
        """
        ctx = TaskContext(user_intent=user_intent)
        logger.info(f"[{ctx.task_id}] 收到任务: {user_intent[:80]}...")

        try:
            # ── Phase 1: 架构师设计 ──
            self._notify_progress(ctx, TaskStatus.PLANNING)
            ctx.record("architect_start")
            ctx.plan = self.architect.design(user_intent)
            ctx.record("architect_done", {
                "nodes": len(ctx.plan.workflow_nodes),
                "tokens": ctx.plan.token_cost,
            })
            ctx.token_counter.add("architect", ctx.plan.token_cost)
            logger.info(
                f"[{ctx.task_id}] 工作流设计完成: "
                f"{len(ctx.plan.workflow_nodes)} 个节点, "
                f"{ctx.plan.token_cost:,} tokens"
            )

            # ── Phase 2: 环境师适配 ──
            self._notify_progress(ctx, TaskStatus.ENV_SETUP)
            ctx.record("environment_start")
            ctx.env = self.environment.prepare(ctx.plan.required_dependencies)
            ctx.record("environment_done", {
                "qgis_found": ctx.env.qgis_available,
                "deps_ok": ctx.env.all_dependencies_met,
                "tokens": ctx.env.token_cost,
            })
            ctx.token_counter.add("environment", ctx.env.token_cost)
            logger.info(
                f"[{ctx.task_id}] 环境准备完成: "
                f"QGIS={'可用' if ctx.env.qgis_available else '不可用'}, "
                f"依赖={'完整' if ctx.env.all_dependencies_met else '缺失'}"
            )

            if ctx.env.critical_missing:
                raise EnvironmentError(
                    f"关键依赖缺失: {ctx.env.critical_missing}"
                )

            # ── Phase 3: 执行者运行 ──
            self._notify_progress(ctx, TaskStatus.EXECUTING)
            ctx.record("executor_start")
            ctx.result = self.executor.execute(ctx.plan, ctx.env)
            ctx.record("executor_done", {
                "success": ctx.result.success,
                "retries": ctx.result.retry_count,
                "outputs": len(ctx.result.output_files),
                "tokens": ctx.result.token_cost,
            })
            ctx.token_counter.add("executor", ctx.result.token_cost)

            if ctx.result.success:
                ctx.status = TaskStatus.COMPLETED
                self._notify_progress(ctx, TaskStatus.COMPLETED)
                logger.info(
                    f"[{ctx.task_id}] 完成: "
                    f"{len(ctx.result.output_files)} 个输出文件, "
                    f"总Token: {ctx.token_counter.total:,}, "
                    f"耗时: {time.time() - ctx.created_at:.1f}s"
                )
            else:
                ctx.status = TaskStatus.FAILED
                self._notify_progress(ctx, TaskStatus.FAILED)
                logger.error(
                    f"[{ctx.task_id}] 失败: {ctx.result.error_summary}"
                )

            # 附加 token 报告
            ctx.result.total_tokens = ctx.token_counter.total
            ctx.result.execution_history = ctx.history

            return ctx.result

        except Exception as exc:
            ctx.status = TaskStatus.FAILED
            ctx.record("fatal_error", {"error": str(exc)})
            logger.error(f"[{ctx.task_id}] 致命异常: {exc}")
            self._notify_progress(ctx, TaskStatus.FAILED)
            return ExecutionResult(
                success=False,
                error_summary=str(exc),
                total_tokens=ctx.token_counter.total,
                execution_history=ctx.history,
            )

    def _notify_progress(self, ctx: TaskContext, status: TaskStatus) -> None:
        ctx.status = status
        if self.on_progress:
            try:
                self.on_progress(ctx.task_id, status)
            except Exception:
                pass


class GeoOpenClaw:
    """Geo-OpenClaw 框架顶层入口.

    使用方式::

        from src.core.orchestrator import GeoOpenClaw

        claw = GeoOpenClaw()
        result = claw.run("将 D:/rasters/ 下所有 TIFF 按行政区裁剪")
        print(result.summary())
    """

    def __init__(self, llm_client: Any = None, max_retries: int = 3):
        self.orchestrator = Orchestrator(
            llm_client=llm_client,
            max_retries=max_retries,
        )

    def run(self, user_intent: str) -> ExecutionResult:
        return self.orchestrator.run(user_intent)
