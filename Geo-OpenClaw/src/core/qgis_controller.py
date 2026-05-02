"""QGIS 进程管理器 — 管理 PyQGIS 子进程的完整生命周期."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# QGIS 已知安装模式
KNOWN_QGIS_ROOTS = [
    "C:/Program Files/QGIS 3.44.9",
    "C:/Program Files/QGIS 3.40.5",
    "C:/Program Files/QGIS 3.38.4",
    "C:/OSGeo4W",
    "/Applications/QGIS.app/Contents/MacOS",
    "/usr",
]


@dataclass
class QGISRuntime:
    """描述一个可用的 QGIS 运行时环境."""

    root: str
    python_home: str
    python_bin: str
    qt5_plugins: str
    proj_data: str
    qgis_python_path: str
    version: str = "unknown"
    validated: bool = False

    def to_env_dict(self) -> dict[str, str]:
        """生成 subprocess 兼容的环境变量字典."""
        env = os.environ.copy()
        env.update({
            "PYTHONHOME": self.python_home,
            "PYTHONUTF8": "1",
            "GDAL_FILENAME_IS_UTF8": "YES",
            "PROJ_DATA": self.proj_data,
            "PYTHONPATH": self.qgis_python_path,
            "QGIS_PREFIX_PATH": str(Path(self.root) / "apps" / "qgis-ltr"),
            "QT_PLUGIN_PATH": self.qt5_plugins,
        })
        # 将 Qt5 bin 目录插入 PATH 最前面，确保 DLL 加载
        qt_bin = str(Path(self.root) / "apps" / "Qt5" / "bin")
        qgis_bin = str(Path(self.root) / "apps" / "qgis-ltr" / "bin")
        env["PATH"] = os.pathsep.join([
            qt_bin, qgis_bin,
            str(Path(self.root) / "bin"),
            str(Path(self.python_home) / "Scripts"),
            env.get("PATH", ""),
        ])
        return env

    def get_python_exe(self) -> str:
        return str(Path(self.python_home) / "python.exe")


@dataclass
class ProcessResult:
    """subprocess 执行的结构化返回."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    elapsed_ms: float
    output_files: list[str] = field(default_factory=list)
    artifact_dir: str = ""


class QGISController:
    """QGIS Python 子进程管理器.

    职责:
    1. 自动发现本地 QGIS 安装
    2. 构建隔离的 subprocess 运行时环境
    3. 注入 Python 脚本并捕获完整输出
    4. 超时控制与进程清理
    """

    def __init__(self, preferred_root: str | None = None):
        self.runtime: Optional[QGISRuntime] = None
        if preferred_root:
            self.runtime = self._build_runtime(preferred_root)

    def discover(self) -> QGISRuntime | None:
        """自动发现并验证可用的 QGIS 安装."""
        for root in KNOWN_QGIS_ROOTS:
            if self.runtime is not None:
                break
            path = Path(root)
            if not path.exists():
                continue
            runtime = self._build_runtime(str(path))
            if runtime and self._validate_runtime(runtime):
                self.runtime = runtime
                logger.info(f"发现 QGIS 运行时: {runtime.root} (v{runtime.version})")
                return runtime
        logger.warning("未找到有效的 QGIS 安装")
        return None

    def execute(
        self,
        script: str,
        timeout_sec: int = 300,
        artifact_dir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ProcessResult:
        """在 QGIS Python 环境中执行脚本.

        Parameters
        ----------
        script : str
            要执行的 PyQGIS Python 脚本内容
        timeout_sec : int
            超时秒数
        artifact_dir : str | None
            输出目录（如不指定则用临时目录）
        extra_env : dict | None
            额外的环境变量

        Returns
        -------
        ProcessResult
        """
        if self.runtime is None:
            self.discover()
        if self.runtime is None:
            return ProcessResult(
                success=False, exit_code=-1,
                stdout="", stderr="QGIS runtime not found",
                elapsed_ms=0,
            )

        out_dir = artifact_dir or tempfile.mkdtemp(prefix="geo_claw_")
        os.makedirs(out_dir, exist_ok=True)

        env = self.runtime.to_env_dict()
        if extra_env:
            env.update(extra_env)
        env["GEO_CLAW_OUTPUT_DIR"] = out_dir

        # 写入临时脚本文件（避免命令行转义问题）
        script_path = Path(out_dir) / "_exec.py"
        script_path.write_text(script, encoding="utf-8")

        logger.info(f"执行脚本: {script_path} ({len(script)} 字符)")
        logger.debug(f"环境: PYTHONHOME={self.runtime.python_home}")

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [self.runtime.get_python_exe(), str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=out_dir,
                env=env,
            )
            elapsed = (time.perf_counter() - t0) * 1000
        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProcessResult(
                success=False, exit_code=-2,
                stdout="", stderr=f"Timeout after {timeout_sec}s",
                elapsed_ms=elapsed,
                artifact_dir=out_dir,
            )

        success = proc.returncode == 0
        if success:
            logger.info(f"脚本执行成功 ({elapsed:.0f}ms)")
        else:
            logger.error(
                f"脚本执行失败 (exit={proc.returncode}, {elapsed:.0f}ms)\n"
                f"stderr: {proc.stderr[:500]}"
            )

        return ProcessResult(
            success=success,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed_ms=elapsed,
            artifact_dir=out_dir,
        )

    def _build_runtime(self, root: str) -> Optional[QGISRuntime]:
        """根据根目录构建 QGISRuntime 结构."""
        root_p = Path(root)
        python_home = root_p / "apps" / "Python312"
        if not python_home.exists():
            # 尝试 OSGeo4W 布局
            python_home = root_p / "apps" / "Python39"
        if not python_home.exists():
            return None

        qt5_plugins = root_p / "apps" / "Qt5" / "plugins"
        proj_data = root_p / "share" / "proj"
        qgis_py = root_p / "apps" / "qgis-ltr" / "python"

        return QGISRuntime(
            root=str(root_p),
            python_home=str(python_home),
            python_bin=str(python_home / "python.exe"),
            qt5_plugins=str(qt5_plugins),
            proj_data=str(proj_data),
            qgis_python_path=str(qgis_py),
        )

    def _validate_runtime(self, rt: QGISRuntime) -> bool:
        """验证运行时是否可以正常 import qgis."""
        try:
            proc = subprocess.run(
                [rt.get_python_exe(), "-c",
                 "import qgis.core; print(qgis.core.Qgis.QGIS_VERSION)"],
                capture_output=True, text=True, timeout=15,
                env=rt.to_env_dict(),
            )
            if proc.returncode == 0:
                rt.version = proc.stdout.strip()
                rt.validated = True
                return True
        except Exception:
            pass
        return False
