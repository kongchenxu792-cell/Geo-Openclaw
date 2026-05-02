"""Executor Agent 单元测试."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.agents.architect_agent import ExecutionPlan, WorkflowNode
from src.agents.environment_agent import EnvironmentContext
from src.agents.executor_agent import ExecutorAgent, ExecutionResult
from src.core.qgis_controller import ProcessResult


class TestExecutorAgent:
    """测试执行者 Agent 的脚本编译和闭环验证."""

    def setup_method(self):
        self.agent = ExecutorAgent(max_retries=3)

    def _make_plan(self, nodes: list[WorkflowNode]) -> ExecutionPlan:
        return ExecutionPlan(
            user_intent="test",
            workflow_nodes=nodes,
            required_dependencies=["qgis.core", "osgeo.gdal"],
        )

    def _make_env(self) -> EnvironmentContext:
        return EnvironmentContext(
            qgis_available=True,
            qgis_root="C:/Program Files/QGIS 3.44.9",
            python_home="C:/Program Files/QGIS 3.44.9/apps/Python312",
            all_dependencies_met=True,
        )

    def test_script_compilation(self):
        """测试工作流编译为 Python 脚本."""
        nodes = [
            WorkflowNode(
                id="step_1", skill="reprojection",
                description="重投影到 EPSG:3857",
                inputs={"source": "input.tif"},
                params={"target_crs": "EPSG:3857"},
                depends_on=[],
            ),
            WorkflowNode(
                id="step_2", skill="raster_clip",
                description="按边界裁剪",
                inputs={"target": "step1", "mask": "boundary.shp"},
                params={},
                depends_on=["step_1"],
            ),
        ]
        plan = self._make_plan(nodes)
        env = self._make_env()

        script = self.agent._compile_script(plan, env)

        assert "step_1" in script
        assert "step_2" in script
        assert "reprojection" in script.lower()
        assert "clip" in script.lower()
        assert "Geo-OpenClaw Executor Agent" in script

    def test_compile_empty_plan(self):
        """测试空计划编译."""
        plan = self._make_plan([])
        env = self._make_env()

        script = self.agent._compile_script(plan, env)
        assert "script" in script.lower()

    def test_compile_unknown_skill(self):
        """测试未知 skill 的降级处理."""
        nodes = [
            WorkflowNode(
                id="step_x", skill="unknown_fancy_operation",
                description="某个未知操作",
                inputs={}, params={}, depends_on=[],
            ),
        ]
        plan = self._make_plan(nodes)
        env = self._make_env()

        script = self.agent._compile_script(plan, env)
        assert "unknown" in script.lower()
        # 不应该崩溃

    def test_node_dependency_resolution(self):
        """测试节点间的依赖解析."""
        nodes = [
            WorkflowNode(id="a", skill="vector_load",
                         description="load", params={}, depends_on=[],
                         inputs={"path": "roads.shp"}, outputs={"v": "a_v"}),
            WorkflowNode(id="b", skill="buffer_analysis",
                         description="buffer", params={"distance": 500},
                         depends_on=["a"],
                         inputs={"source": "a"}, outputs={"buf": "b_buf"}),
            WorkflowNode(id="c", skill="export",
                         description="export", params={"format": "GeoJSON"},
                         depends_on=["b"],
                         inputs={"source": "b"}, outputs={"exp": "c_exp"}),
        ]
        plan = self._make_plan(nodes)
        env = self._make_env()

        script = self.agent._compile_script(plan, env)

        # 验证缓冲区节点引用了加载节点的输出变量
        assert "_output_a" in script
        assert "_output_b" in script

    @patch("src.agents.executor_agent.QGISController")
    def test_execute_mocked_success(self, mock_ctrl):
        """模拟成功的执行流程."""
        mock_ctrl_instance = MagicMock()
        mock_ctrl_instance.execute.return_value = ProcessResult(
            success=True, exit_code=0,
            stdout="Done", stderr="",
            elapsed_ms=1234,
            artifact_dir="/tmp/test",
        )
        self.agent.qgis_ctrl = mock_ctrl_instance

        nodes = [
            WorkflowNode(id="s1", skill="reprojection",
                         description="test", params={}, depends_on=[],
                         inputs={}, outputs={}),
        ]
        plan = self._make_plan(nodes)
        env = self._make_env()

        result = self.agent.execute(plan, env)
        assert isinstance(result, ExecutionResult)
