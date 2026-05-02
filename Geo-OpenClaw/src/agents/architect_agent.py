"""Architect Agent — 自然语言指令解析与地理处理工作流 DAG 拆解."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WorkflowNode:
    """DAG 工作流中的一个处理节点."""

    id: str
    skill: str                     # 技能名称，如 "buffer_analysis"
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    validation: Optional[str] = None   # 验证规则表达式
    estimated_cost: int = 0            # 估算 token 消耗

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "skill": self.skill,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "params": self.params,
            "depends_on": self.depends_on,
            "validation": self.validation,
            "estimated_cost": self.estimated_cost,
        }


@dataclass
class ExecutionPlan:
    """Architect Agent 生成的完整执行计划."""

    user_intent: str
    workflow_nodes: list[WorkflowNode]
    required_dependencies: list[str] = field(default_factory=list)
    estimated_total_cost: int = 0
    token_cost: int = 0
    reasoning_trace: str = ""

    def to_yaml_str(self) -> str:
        """将执行计划序列化为可读的 YAML 形式字符串."""
        lines = [
            f"# Execution Plan: {self.user_intent[:60]}...",
            f"# Nodes: {len(self.workflow_nodes)}",
            f"# Est. Cost: {self.estimated_total_cost:,} tokens",
            f"# Dependencies: {self.required_dependencies}",
            "",
        ]
        for node in self.workflow_nodes:
            lines.append(f"- id: {node.id}")
            lines.append(f"  skill: {node.skill}")
            lines.append(f"  description: {node.description}")
            lines.append(f"  depends_on: {node.depends_on}")
            lines.append(f"  params: {node.params}")
            if node.validation:
                lines.append(f"  validation: {node.validation}")
            lines.append("")
        return "\n".join(lines)

    def topological_order(self) -> list[WorkflowNode]:
        """返回拓扑排序后的节点列表."""
        visited = set()
        order = []

        def visit(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            node = self._find_node(node_id)
            if node:
                for dep in node.depends_on:
                    visit(dep)
                order.append(node)

        for node in self.workflow_nodes:
            visit(node.id)
        return order

    def _find_node(self, node_id: str) -> Optional[WorkflowNode]:
        for node in self.workflow_nodes:
            if node.id == node_id:
                return node
        return None


class ArchitectAgent:
    """架构师 Agent — 自然语言 → DAG 工作流.

    LLM-driven 的 GIS 任务编排器。接收用户的自然语言指令，
    通过 Chain-of-Thought 推理将其分解为有序的地理处理步骤 DAG。

    核心能力:
    - 意图解析：识别操作类型、目标数据、空间约束、输出格式
    - 工作流拆解：生成拓扑有序的处理节点图
    - 参数推断：从模糊输入中补全 EPSG/编码/缓冲区距离等参数
    - 成本估算：预测每个节点的 Token 消耗
    """

    # 已知的技能注册表（用于匹配）
    KNOWN_SKILLS = [
        "buffer_analysis",
        "reprojection",
        "raster_clip",
        "vector_clip",
        "spatial_join",
        "zonal_statistics",
        "raster_calculator",
        "dissolve",
        "intersection",
        "union",
        "distance_matrix",
        "heatmap",
        "slope_analysis",
        "watershed",
        "ndvi",
    ]

    # Chain-of-Thought Prompt 模板
    COT_PROMPT_TEMPLATE = """你是一个 GIS 地理处理专家。请将以下自然语言指令分解为一个有序的地理处理工作流 DAG。

## 指令
{user_intent}

## 可用技能
{skills}

## 要求
1. 将任务分解为原子操作节点
2. 确定节点间的依赖关系 (depends_on)
3. 为每个节点指定:
   - 需要的输入数据 (inputs)
   - 参数 (params)
   - 验证规则 (validation)
4. 估算每个节点的计算成本 (1-100 尺度)
5. 输出 JSON 格式的 DAG 定义

## 输出格式
{{
  "workflow_nodes": [
    {{
      "id": "step_1",
      "skill": "reprojection",
      "description": "将输入数据重投影到统一CRS",
      "inputs": {{"source": "input.tif"}},
      "outputs": {{"reprojected": "step1_output.tif"}},
      "params": {{"target_crs": "EPSG:3857", "resampling": "bilinear"}},
      "depends_on": [],
      "validation": "layer.crs().authid() == 'EPSG:3857'",
      "estimated_cost": 10
    }}
  ],
  "required_dependencies": ["qgis.core", "osgeo.gdal", "geopandas"],
  "reasoning_trace": "首先需要统一CRS，然后..."
}}

请严格输出 JSON，不要包含其他文字。"""

    def __init__(self, llm_client: Any = None):
        self.llm = llm_client

    def design(self, user_intent: str) -> ExecutionPlan:
        """将自然语言指令转换为执行计划.

        Parameters
        ----------
        user_intent : str
            例如: "将 D:/data/ 下所有 TIFF 按武汉行政区裁剪，输出 Web 墨卡托"

        Returns
        -------
        ExecutionPlan
        """
        logger.info(f"Architect Agent 开始解析: {user_intent[:60]}...")

        # 如果配置了 LLM 客户端，使用它
        if self.llm is not None:
            return self._design_with_llm(user_intent)
        # 否则使用基于规则的启发式拆解（适合无 API key 的场景）
        return self._design_heuristic(user_intent)

    def _design_with_llm(self, user_intent: str) -> ExecutionPlan:
        """使用 LLM 进行工作流设计."""
        prompt = self.COT_PROMPT_TEMPLATE.format(
            user_intent=user_intent,
            skills="\n".join(f"- {s}" for s in self.KNOWN_SKILLS),
        )

        response = self.llm.complete(prompt, max_tokens=4096)
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"LLM 返回无法解析: {response[:200]}")

        nodes = [
            WorkflowNode(**node_data) for node_data in data["workflow_nodes"]
        ]
        return ExecutionPlan(
            user_intent=user_intent,
            workflow_nodes=nodes,
            required_dependencies=data.get("required_dependencies", []),
            estimated_total_cost=sum(n.estimated_cost for n in nodes),
            token_cost=len(prompt) + len(response),
            reasoning_trace=data.get("reasoning_trace", ""),
        )

    def _design_heuristic(self, user_intent: str) -> ExecutionPlan:
        """基于关键词语义的启发式工作流拆解.

        不依赖外部 LLM —— 通过正则匹配识别用户的 GIS 操作意图，
        然后匹配预定义的 workflow template 生成 DAG。
        """
        text = user_intent.lower()
        nodes: list[WorkflowNode] = []
        counter = [0]

        def _next_id() -> str:
            counter[0] += 1
            return f"step_{counter[0]}"

        deps: list[str] = []
        estimated_cost = 0

        # 检测操作类型并插入对应节点

        # 1. 数据加载
        if any(w in text for w in ["tiff", "tif", "栅格", "raster", ".tif"]):
            nid = _next_id()
            nodes.append(WorkflowNode(
                id=nid, skill="raster_load",
                description="加载栅格数据",
                inputs={"pattern": self._extract_path_pattern(user_intent)},
                outputs={"raster": f"{nid}_raster"},
                estimated_cost=5,
            ))
            deps.append(nid)

        if any(w in text for w in ["shp", "shapefile", "矢量", "vector", ".shp"]):
            nid = _next_id()
            nodes.append(WorkflowNode(
                id=nid, skill="vector_load",
                description="加载矢量数据",
                inputs={"path": self._extract_vector_path(user_intent)},
                outputs={"vector": f"{nid}_vector"},
                estimated_cost=5,
            ))
            deps.append(nid)

        # 2. CRS 重投影
        if any(w in text for w in ["投影", "epsg", "墨卡托", "web mercator", "3857",
                                     "投影", "坐标转换", "wgs84"]):
            target_epsg = "3857" if any(w in text for w in ["墨卡托", "3857", "web mercator"]) else "4326"
            nid = _next_id()
            nodes.append(WorkflowNode(
                id=nid, skill="reprojection",
                description=f"重投影到 EPSG:{target_epsg}",
                inputs={"source": "previous_output"},
                outputs={"reprojected": f"{nid}_reprojected"},
                params={"target_crs": f"EPSG:{target_epsg}"},
                depends_on=deps.copy(),
                validation=f"output.crs().authid() == 'EPSG:{target_epsg}'",
                estimated_cost=15,
            ))
            deps = [nid]
            estimated_cost += 15

        # 3. 裁剪
        if any(w in text for w in ["裁剪", "clip", "按...裁剪", "裁剪到"]):
            nid = _next_id()
            nodes.append(WorkflowNode(
                id=nid, skill="raster_clip" if "tiff" in text else "vector_clip",
                description="空间裁剪",
                inputs={"target": "previous_output", "mask": "boundary"},
                outputs={"clipped": f"{nid}_clipped"},
                params={"crop_to_cutline": True},
                depends_on=deps.copy(),
                validation="output.featureCount() > 0",
                estimated_cost=20,
            ))
            deps = [nid]
            estimated_cost += 20

        # 4. 缓冲区分析
        if any(w in text for w in ["缓冲区", "buffer", "缓冲"]):
            nid = _next_id()
            dist = self._extract_buffer_distance(text)
            nodes.append(WorkflowNode(
                id=nid, skill="buffer_analysis",
                description=f"缓冲区分析 ({dist}m)",
                inputs={"source": "previous_output"},
                outputs={"buffer": f"{nid}_buffer"},
                params={"distance": dist, "segments": 30},
                depends_on=deps.copy(),
                validation="output.featureCount() > 0",
                estimated_cost=12,
            ))
            deps = [nid]
            estimated_cost += 12

        # 5. 空间连接
        if any(w in text for w in ["空间连接", "join", "连接", "叠加"]):
            nid = _next_id()
            nodes.append(WorkflowNode(
                id=nid, skill="spatial_join",
                description="空间连接分析",
                inputs={"layer_a": "layer_a", "layer_b": "layer_b"},
                outputs={"joined": f"{nid}_joined"},
                params={"predicate": "intersects"},
                depends_on=deps.copy(),
                validation="output.featureCount() > 0",
                estimated_cost=18,
            ))
            deps = [nid]
            estimated_cost += 18

        # 6. 导出
        if any(w in text for w in ["导出", "输出", "保存", "export", "save"]):
            fmt = "GeoJSON" if "geojson" in text else "GeoTIFF" if "tiff" in text else "GeoPackage"
            nid = _next_id()
            nodes.append(WorkflowNode(
                id=nid, skill="export",
                description=f"导出为 {fmt}",
                inputs={"source": "previous_output"},
                outputs={"exported": f"output.{fmt.lower()}"},
                params={"format": fmt},
                depends_on=deps.copy(),
                estimated_cost=5,
            ))
            estimated_cost += 5

        # 如果没有匹配到任何已知操作，创建一个探索性节点
        if not nodes:
            nid = _next_id()
            nodes.append(WorkflowNode(
                id=nid, skill="exploratory_analysis",
                description="探索性空间数据分析",
                inputs={"intent": user_intent},
                outputs={"report": f"{nid}_report"},
                params={"auto_detect": True},
                estimated_cost=30,
            ))
            estimated_cost = 30

        plan = ExecutionPlan(
            user_intent=user_intent,
            workflow_nodes=nodes,
            required_dependencies=[
                "qgis.core", "qgis.analysis", "osgeo.gdal",
                "geopandas", "shapely",
            ],
            estimated_total_cost=estimated_cost,
            token_cost=len(user_intent) * 3 + estimated_cost * 100,
            reasoning_trace=f"启发式解析识别到 {len(nodes)} 个处理步骤",
        )

        logger.info(
            f"Architect Agent 完成: {len(nodes)} 个节点, "
            f"估算 Token: {plan.token_cost:,}"
        )
        return plan

    def revise(self, plan: ExecutionPlan, error_context: str) -> ExecutionPlan:
        """根据执行反馈修正执行计划.

        Parameters
        ----------
        plan : ExecutionPlan
            原始执行计划
        error_context : str
            执行器反馈的错误上下文

        Returns
        -------
        ExecutionPlan
            修正后的执行计划
        """
        if self.llm is not None:
            prompt = (
                f"原始执行计划:\n{plan.to_yaml_str()}\n\n"
                f"执行错误:\n{error_context}\n\n"
                f"请修正执行计划，输出调整后的 JSON DAG。"
            )
            response = self.llm.complete(prompt, max_tokens=4096)
            try:
                data = json.loads(response)
                nodes = [
                    WorkflowNode(**n) for n in data["workflow_nodes"]
                ]
                return ExecutionPlan(
                    user_intent=plan.user_intent,
                    workflow_nodes=nodes,
                    required_dependencies=data.get("required_dependencies",
                                                    plan.required_dependencies),
                    estimated_total_cost=sum(n.estimated_cost for n in nodes),
                    token_cost=plan.token_cost + len(prompt) + len(response),
                    reasoning_trace=plan.reasoning_trace + "\n[Revised due to errors]",
                )
            except Exception:
                pass

        # 降级：在现有计划中插入错误处理节点
        plan.workflow_nodes.append(WorkflowNode(
            id=f"fix_{len(plan.workflow_nodes) + 1}",
            skill="error_recovery",
            description=f"自动插入：修复 {error_context[:60]}",
            inputs={"previous_output": "all"},
            outputs={"fixed": "recovered_output"},
            params={"error_context": error_context},
            estimated_cost=25,
        ))
        plan.reasoning_trace += f"\n[Auto-fix] inserted recovery node for: {error_context[:80]}"
        return plan

    @staticmethod
    def _extract_path_pattern(text: str) -> str:
        import re
        match = re.search(r'["\']?([A-Z]:[/\\][^\s\'"]+\.(?:tiff?|shp|gpkg|geojson))["\']?',
                          text, re.I)
        return match.group(1) if match else "data/*.tif"

    @staticmethod
    def _extract_vector_path(text: str) -> str:
        import re
        match = re.search(r'["\']?([A-Z]:[/\\][^\s\'"]+\.(?:shp|gpkg|geojson))["\']?',
                          text, re.I)
        return match.group(1) if match else "boundary.shp"

    @staticmethod
    def _extract_buffer_distance(text: str) -> float:
        import re
        match = re.search(r'(\d+\.?\d*)\s*(m|km|米|千米|公里|度)?\s*(缓冲|buffer)', text, re.I)
        if match:
            val = float(match.group(1))
            unit = match.group(2)
            if unit in ("km", "千米", "公里"):
                val *= 1000
            return val
        return 1000.0
