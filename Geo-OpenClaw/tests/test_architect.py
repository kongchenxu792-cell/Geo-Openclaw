"""Architect Agent 单元测试."""

import pytest
from src.agents.architect_agent import (
    ArchitectAgent, ExecutionPlan, WorkflowNode,
)


class TestArchitectAgent:
    """测试架构师 Agent 的工作流拆解能力."""

    def setup_method(self):
        self.agent = ArchitectAgent(llm_client=None)  # 使用启发式模式

    def test_design_simple_reprojection(self):
        """测试简单的重投影指令."""
        plan = self.agent.design(
            "将 data/dem.tif 投影到 EPSG:3857 Web墨卡托"
        )
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.workflow_nodes) > 0
        assert any(n.skill == "reprojection" for n in plan.workflow_nodes)

    def test_design_clip_with_reprojection(self):
        """测试裁剪+投影的复合指令."""
        plan = self.agent.design(
            "将 D:/rasters/ 下所有 TIFF 按武汉行政区边界裁剪，输出 Web 墨卡托投影"
        )
        assert len(plan.workflow_nodes) >= 2
        skills = [n.skill for n in plan.workflow_nodes]
        assert "raster_clip" in skills or "vector_clip" in skills
        assert "reprojection" in skills

    def test_design_buffer_analysis(self):
        """测试缓冲区分析指令."""
        plan = self.agent.design(
            "对 roads.shp 创建 500m 缓冲区"
        )
        assert any(n.skill == "buffer_analysis" for n in plan.workflow_nodes)

    def test_topological_order(self):
        """测试拓扑排序."""
        plan = self.agent.design(
            "加载 tif → 重投影到3857 → 按边界裁剪 → 导出GeoJSON"
        )
        ordered = plan.topological_order()
        assert len(ordered) == len(plan.workflow_nodes)

        # 验证依赖关系：裁剪在重投影之后
        clip_node = next(
            (n for n in ordered if "clip" in n.skill), None
        )
        reproj_node = next(
            (n for n in ordered if n.skill == "reprojection"), None
        )
        if clip_node and reproj_node:
            clip_idx = ordered.index(clip_node)
            reproj_idx = ordered.index(reproj_node)
            assert clip_idx > reproj_idx

    def test_yaml_serialization(self):
        """测试执行计划的 YAML 序列化."""
        plan = self.agent.design(
            "对 study_area.shp 做 1km 缓冲区"
        )
        yaml_str = plan.to_yaml_str()
        assert "Execution Plan" in yaml_str
        assert "buffer" in yaml_str.lower()

    def test_design_empty_intent(self):
        """测试模糊指令 — 应该生成探索性节点."""
        plan = self.agent.design("处理一下这个数据")
        assert len(plan.workflow_nodes) > 0

    def test_design_returns_dependencies(self):
        """测试计划是否包含依赖列表."""
        plan = self.agent.design(
            "将 dem.tif 按边界裁剪并计算坡度"
        )
        assert len(plan.required_dependencies) > 0
        assert "qgis.core" in plan.required_dependencies
