"""Environment Agent — QGIS/PyQGIS 环境感知与自动配置."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DependencyStatus:
    """单个依赖包的状态."""

    name: str
    available: bool
    version: str = "unknown"
    import_path: str = ""
    notes: str = ""


@dataclass
class EnvironmentContext:
    """Environment Agent 生成的完整环境上下文."""

    qgis_available: bool = False
    qgis_root: str = ""
    qgis_version: str = ""
    python_home: str = ""
    python_version: str = ""
    all_dependencies_met: bool = False
    critical_missing: list[str] = field(default_factory=list)
    dependencies: list[DependencyStatus] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    platform: str = platform.platform()
    token_cost: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_env_dict(self) -> dict[str, str]:
        """转换为可用于子进程的环境变量字典."""
        return {
            **os.environ,
            **self.env_vars,
        }

    def summary(self) -> str:
        lines = [
            f"QGIS: {'可用' if self.qgis_available else '不可用'} "
            f"(v{self.qgis_version})",
            f"Python: {self.python_version}",
            f"依赖: {'完整' if self.all_dependencies_met else '缺失'}",
        ]
        for dep in self.dependencies:
            icon = "✓" if dep.available else "✗"
            lines.append(f"  {icon} {dep.name} {dep.version}")
        return "\n".join(lines)


class EnvironmentAgent:
    """环境师 Agent — 感知和配置本地 GIS 运行环境.

    核心职责:
    1. 自动发现 QGIS 安装路径（注册表/常见路径/环境变量）
    2. 配置 PYTHONHOME / QT_PLUGIN_PATH / PROJ_DATA 等 8+ 环境变量
    3. 依赖健康检查矩阵（qgis.core → osgeo.gdal → geopandas → shapely）
    4. 提供标准化的 EnvironmentContext 给 Executor Agent
    """

    # 依赖检查矩阵: (import 路径, 显示名称, 是否关键)
    DEPENDENCY_MATRIX = [
        ("qgis.core", "QGIS Core", True),
        ("qgis.analysis", "QGIS Analysis", True),
        ("osgeo.gdal", "GDAL", True),
        ("osgeo.ogr", "OGR", True),
        ("osgeo.osr", "OSR (PROJ)", True),
        ("geopandas", "GeoPandas", False),
        ("shapely", "Shapely", True),
        ("numpy", "NumPy", True),
        ("fiona", "Fiona", False),
        ("pyproj", "PyPROJ", False),
    ]

    # QGIS 常见安装路径（按优先级排序）
    SEARCH_PATHS = [
        ("C:/Program Files/QGIS 3.44.9", "3.44 LTR"),
        ("C:/Program Files/QGIS 3.40.5", "3.40"),
        ("C:/Program Files/QGIS 3.38.4", "3.38"),
        ("C:/OSGeo4W", "OSGeo4W"),
        ("/usr", "Linux System"),
        ("/Applications/QGIS.app/Contents/MacOS", "macOS"),
    ]

    def __init__(self):
        self.context: Optional[EnvironmentContext] = None

    def prepare(self, required_deps: list[str] | None = None) -> EnvironmentContext:
        """感知并配置完整的 QGIS 运行环境.

        Parameters
        ----------
        required_deps : list[str] | None
            Architect Agent 要求的依赖列表

        Returns
        -------
        EnvironmentContext
        """
        logger.info("Environment Agent 开始环境感知...")

        ctx = EnvironmentContext()

        # Step 1: 发现 QGIS 安装
        qgis_root = self._find_qgis()
        if qgis_root:
            ctx.qgis_available = True
            ctx.qgis_root = qgis_root
            ctx.env_vars = self._build_env_vars(qgis_root)
            ctx.qgis_version = self._detect_qgis_version(qgis_root)
            logger.info(f"QGIS 已发现: {qgis_root} (v{ctx.qgis_version})")
        else:
            ctx.qgis_available = False
            ctx.warnings.append("未找到 QGIS 安装，将使用轻量模式 (仅 GDAL/GeoPandas)")
            logger.warning("未找到 QGIS 安装")

        # Step 2: Python 环境信息
        ctx.python_home = ctx.env_vars.get("PYTHONHOME", sys_prefix())
        ctx.python_version = platform.python_version()

        # Step 3: 依赖健康检查
        ctx.dependencies = self._check_all_dependencies(ctx.env_vars)
        ctx.all_dependencies_met = all(
            d.available for d in ctx.dependencies if d.notes != "optional"
        )
        ctx.critical_missing = [
            d.name for d in ctx.dependencies
            if not d.available and d.notes == "critical"
        ]

        # Step 4: 指定依赖验证
        if required_deps:
            for dep_name in required_deps:
                if dep_name not in [d.name for d in ctx.dependencies]:
                    status = self._check_single_dep(dep_name, ctx.env_vars)
                    ctx.dependencies.append(status)

        ctx.token_cost = 500 + len(ctx.dependencies) * 100
        self.context = ctx

        logger.info(
            f"Environment Agent 完成: "
            f"QGIS={'OK' if ctx.qgis_available else 'N/A'}, "
            f"依赖={sum(1 for d in ctx.dependencies if d.available)}/"
            f"{len(ctx.dependencies)}"
        )
        return ctx

    def _find_qgis(self) -> str | None:
        """自动发现 QGIS 安装路径."""
        # 方法 1: 检查环境变量
        for var in ["QGIS_PREFIX_PATH", "OSGEO4W_ROOT", "QGIS_HOME"]:
            val = os.environ.get(var)
            if val and Path(val).exists():
                logger.info(f"通过环境变量 {var} 找到 QGIS: {val}")
                return val

        # 方法 2: 扫描已知路径
        for path, label in self.SEARCH_PATHS:
            if Path(path).exists():
                logger.info(f"通过路径扫描找到 QGIS ({label}): {path}")
                return path

        # 方法 3: Windows 注册表查询
        if platform.system() == "Windows":
            try:
                import winreg
                for key_path in [
                    r"SOFTWARE\QGIS",
                    r"SOFTWARE\OSGeo\QGIS",
                    r"SOFTWARE\WOW6432Node\QGIS",
                ]:
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                        val, _ = winreg.QueryValueEx(key, "InstallPath")
                        winreg.CloseKey(key)
                        if Path(val).exists():
                            logger.info(f"通过注册表找到 QGIS: {val}")
                            return val
                    except OSError:
                        continue
            except ImportError:
                pass

        return None

    def _build_env_vars(self, qgis_root: str) -> dict[str, str]:
        """构建完整的 QGIS 运行时环境变量."""
        root = Path(qgis_root)
        apps = root / "apps"

        # 自动检测 Python 版本目录
        python_dir = None
        for candidate in sorted(apps.glob("Python3*"), reverse=True):
            if candidate.is_dir():
                python_dir = candidate
                break

        env = {}
        if python_dir:
            env["PYTHONHOME"] = str(python_dir)
        env["PYTHONUTF8"] = "1"
        env["GDAL_FILENAME_IS_UTF8"] = "YES"

        # PROJ 数据
        proj_data = root / "share" / "proj"
        if proj_data.exists():
            env["PROJ_DATA"] = str(proj_data)

        # QGIS Python 模块路径
        for qgis_ver in ["qgis-ltr", "qgis"]:
            qgis_py = apps / qgis_ver / "python"
            if qgis_py.exists():
                env["PYTHONPATH"] = str(qgis_py)
                env["QGIS_PREFIX_PATH"] = str(apps / qgis_ver)
                break

        # Qt5 插件
        qt_plugins = apps / "Qt5" / "plugins"
        if qt_plugins.exists():
            env["QT_PLUGIN_PATH"] = str(qt_plugins)

        # GDAL 数据
        gdal_data = root / "share" / "gdal"
        if gdal_data.exists():
            env["GDAL_DATA"] = str(gdal_data)

        return env

    def _detect_qgis_version(self, qgis_root: str) -> str:
        """通过 Python 获取 QGIS 版本号."""
        env_vars = self._build_env_vars(qgis_root)
        env = {**os.environ, **env_vars}

        python_exe = "python.exe" if platform.system() == "Windows" else "python3"
        if "PYTHONHOME" in env_vars:
            python_exe = str(Path(env_vars["PYTHONHOME"]) / "python.exe")

        try:
            proc = subprocess.run(
                [python_exe, "-c",
                 "from qgis.core import Qgis; print(Qgis.QGIS_VERSION)"],
                capture_output=True, text=True, timeout=15,
                env=env,
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
        except Exception:
            pass

        # 降级：从路径名推断
        for part in Path(qgis_root).parts:
            if part.startswith("QGIS"):
                return part.replace("QGIS", "").strip()
        return "unknown"

    def _check_all_dependencies(
        self, env_vars: dict[str, str]
    ) -> list[DependencyStatus]:
        """全面检查依赖矩阵."""
        env = {**os.environ, **env_vars}
        results = []

        for import_path, display_name, is_critical in self.DEPENDENCY_MATRIX:
            status = DependencyStatus(
                name=display_name,
                available=False,
                import_path=import_path,
                notes="critical" if is_critical else "optional",
            )
            try:
                mod = __import__(import_path, fromlist=["__version__"])
                status.available = True
                status.version = getattr(mod, "__version__", "unknown")
            except ImportError:
                if is_critical:
                    status.notes = "critical"
            except Exception:
                pass

            results.append(status)

        return results

    def _check_single_dep(
        self, dep_name: str, env_vars: dict[str, str]
    ) -> DependencyStatus:
        """检查单个依赖."""
        status = DependencyStatus(
            name=dep_name, available=False, import_path=dep_name,
            notes="requested",
        )
        try:
            mod = __import__(dep_name, fromlist=["__version__"])
            status.available = True
            status.version = getattr(mod, "__version__", "unknown")
        except ImportError:
            pass
        return status


def sys_prefix() -> str:
    """获取当前 Python 的 sys.prefix."""
    import sys
    return sys.prefix
