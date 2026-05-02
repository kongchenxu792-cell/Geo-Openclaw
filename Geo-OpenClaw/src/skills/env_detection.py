"""环境自动检测 Skill — QGIS/Proj/GDAL 路径发现."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Optional


def detect_qgis_installation() -> Optional[dict]:
    """自动检测 QGIS 安装路径和环境配置.

    Returns
    -------
    dict | None
        包含 root, python_home, version, env_vars 的字典
    """
    candidates = [
        "C:/Program Files/QGIS 3.44.9",
        "C:/Program Files/QGIS 3.40.5",
        "C:/Program Files/QGIS 3.38.4",
        "C:/OSGeo4W",
        "/Applications/QGIS.app/Contents/MacOS",
        "/usr",
    ]

    # 环境变量优先
    for var in ["QGIS_PREFIX_PATH", "OSGEO4W_ROOT"]:
        val = os.environ.get(var)
        if val and Path(val).exists():
            return _build_qgis_info(Path(val))

    for candidate in candidates:
        p = Path(candidate)
        if p.exists() and _is_valid_qgis_root(p):
            return _build_qgis_info(p)

    return None


def detect_python_environment() -> dict:
    """检测当前 Python 环境中可用的 GIS 库."""
    libs = {}
    checks = [
        ("qgis.core", "qgis_core"),
        ("osgeo.gdal", "gdal"),
        ("osgeo.ogr", "ogr"),
        ("osgeo.osr", "osr"),
        ("geopandas", "geopandas"),
        ("shapely", "shapely"),
        ("numpy", "numpy"),
        ("fiona", "fiona"),
        ("pyproj", "pyproj"),
        ("rasterio", "rasterio"),
    ]

    for mod_name, key in checks:
        try:
            mod = __import__(mod_name, fromlist=["__version__"])
            libs[key] = {
                "available": True,
                "version": getattr(mod, "__version__", "unknown"),
            }
        except ImportError:
            libs[key] = {"available": False, "version": None}

    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "libraries": libs,
    }


def configure_runtime_env(qgis_root: Path) -> dict[str, str]:
    """构建完整的 QGIS 运行时环境变量."""
    apps = qgis_root / "apps"
    env = {
        "PYTHONUTF8": "1",
        "GDAL_FILENAME_IS_UTF8": "YES",
    }

    # Python 路径
    for py_ver in ["Python312", "Python311", "Python39"]:
        py_dir = apps / py_ver
        if py_dir.exists():
            env["PYTHONHOME"] = str(py_dir)
            break

    # QGIS Python
    for qgis_ver in ["qgis-ltr", "qgis"]:
        qgis_py = apps / qgis_ver / "python"
        if qgis_py.exists():
            env["PYTHONPATH"] = str(qgis_py)
            env["QGIS_PREFIX_PATH"] = str(apps / qgis_ver)
            break

    # PROJ data
    proj_data = qgis_root / "share" / "proj"
    if proj_data.exists():
        env["PROJ_DATA"] = str(proj_data)

    # Qt5 plugins
    qt_plugins = apps / "Qt5" / "plugins"
    if qt_plugins.exists():
        env["QT_PLUGIN_PATH"] = str(qt_plugins)

    return env


def _is_valid_qgis_root(path: Path) -> bool:
    """验证目录是否包含有效的 QGIS 安装."""
    markers = [
        path / "apps" / "Python312" / "python.exe",
        path / "apps" / "qgis-ltr" / "python" / "qgis",
        path / "bin" / "qgis-ltr-bin.exe",
        path / "bin" / "qgis-bin.exe",
    ]
    return any(m.exists() for m in markers)


def _build_qgis_info(path: Path) -> dict:
    """从路径构建 QGIS 信息字典."""
    return {
        "root": str(path),
        "env_vars": configure_runtime_env(path),
        "valid": True,
    }
