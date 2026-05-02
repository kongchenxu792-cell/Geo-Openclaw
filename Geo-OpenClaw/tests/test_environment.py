"""Environment Agent 单元测试."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.agents.environment_agent import (
    EnvironmentAgent, EnvironmentContext, DependencyStatus,
)


class TestEnvironmentAgent:
    """测试环境师 Agent 的感知和配置能力."""

    def setup_method(self):
        self.agent = EnvironmentAgent()

    def test_prepare_basic(self):
        """测试基础环境准备."""
        ctx = self.agent.prepare()
        assert isinstance(ctx, EnvironmentContext)
        assert ctx.python_version != ""
        assert len(ctx.dependencies) > 0

    def test_dependency_status_model(self):
        """测试依赖状态数据模型."""
        ds = DependencyStatus(
            name="GDAL", available=True, version="3.12.3",
            import_path="osgeo.gdal", notes="critical",
        )
        assert ds.available
        assert ds.version == "3.12.3"

    def test_context_summary(self):
        """测试环境上下文摘要生成."""
        ctx = EnvironmentContext(
            qgis_available=True,
            qgis_version="3.44.9",
            python_version="3.12.13",
            all_dependencies_met=True,
            dependencies=[
                DependencyStatus(name="GDAL", available=True, version="3.12.3",
                                 notes="critical"),
                DependencyStatus(name="GeoPandas", available=True, version="1.0.1",
                                 notes="optional"),
            ],
        )
        summary = ctx.summary()
        assert "3.44.9" in summary
        assert "GDAL" in summary

    def test_env_vars_construction(self):
        """测试环境变量构建."""
        with patch.object(Path, 'exists', return_value=True):
            env_vars = self.agent._build_env_vars(
                "C:/Program Files/QGIS 3.44.9"
            )
        assert "PYTHONUTF8" in env_vars
        assert "GDAL_FILENAME_IS_UTF8" in env_vars

    def test_search_paths(self):
        """测试搜索路径列表."""
        assert len(EnvironmentAgent.SEARCH_PATHS) > 0
        # 所有路径应是字符串
        for path, label in EnvironmentAgent.SEARCH_PATHS:
            assert isinstance(path, str)
            assert isinstance(label, str)

    def test_dependency_matrix_complete(self):
        """测试依赖矩阵的完整性."""
        assert len(EnvironmentAgent.DEPENDENCY_MATRIX) >= 6
        for import_path, display_name, is_critical in EnvironmentAgent.DEPENDENCY_MATRIX:
            assert isinstance(import_path, str)
            assert isinstance(display_name, str)
            assert isinstance(is_critical, bool)

    @patch("src.agents.environment_agent.EnvironmentAgent._find_qgis")
    def test_prepare_with_qgis_found(self, mock_find):
        """测试 QGIS 已安装的场景."""
        mock_find.return_value = "C:/Program Files/QGIS 3.44.9"
        ctx = self.agent.prepare()
        assert ctx.qgis_available
        assert ctx.qgis_root == "C:/Program Files/QGIS 3.44.9"

    @patch("src.agents.environment_agent.EnvironmentAgent._find_qgis")
    def test_prepare_without_qgis(self, mock_find):
        """测试 QGIS 未安装的场景."""
        mock_find.return_value = None
        ctx = self.agent.prepare()
        assert not ctx.qgis_available
        assert len(ctx.warnings) > 0
