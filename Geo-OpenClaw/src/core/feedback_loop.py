"""自愈反馈引擎 — 错误分类、自动修正、重试循环."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.core.qgis_controller import ProcessResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ErrorCategory(Enum):
    """GIS 脚本常见错误分类."""

    CRS_MISMATCH = "crs_mismatch"
    PATH_NOT_FOUND = "path_not_found"
    ENCODING_ERROR = "encoding_error"
    DRIVER_MISSING = "driver_missing"
    GEOMETRY_INVALID = "geometry_invalid"
    MEMORY_EXHAUSTED = "memory_exhausted"
    DEPENDENCY_MISSING = "dependency_missing"
    PROJ_ERROR = "proj_error"
    UNKNOWN = "unknown"


@dataclass
class ErrorDiagnosis:
    """错误诊断结果."""

    category: ErrorCategory
    confidence: float           # 0.0 ~ 1.0
    original_error: str
    suggested_fix: str
    extracted_params: dict = field(default_factory=dict)


@dataclass
class HealingResult:
    """一次自愈尝试的结果."""

    attempt: int
    diagnosis: ErrorDiagnosis
    fixed_script: str
    process_result: Optional[ProcessResult] = None
    healed: bool = False


class ErrorParser:
    """GIS 错误智能解析器.

    通过正则 + 关键词匹配对 PyQGIS/GDAL 错误进行分类，
    并提取关键参数（如 EPSG 代码、文件路径等）。
    """

    PATTERNS = [
        (re.compile(r"Invalid latitude|webmerc|PROJ.*Invalid", re.I),
         ErrorCategory.PROJ_ERROR),
        (re.compile(r"No such file|Cannot open|does not exist|No such", re.I),
         ErrorCategory.PATH_NOT_FOUND),
        (re.compile(r"CRS.*not found|crs.*unknown|Invalid CRS", re.I),
         ErrorCategory.CRS_MISMATCH),
        (re.compile(r"not recognized.*format|driver.*not.*support|No driver", re.I),
         ErrorCategory.DRIVER_MISSING),
        (re.compile(r"encoding|codec can't decode|UnicodeDecodeError", re.I),
         ErrorCategory.ENCODING_ERROR),
        (re.compile(r"MemoryError|out of memory|Cannot allocate", re.I),
         ErrorCategory.MEMORY_EXHAUSTED),
        (re.compile(r"No module named|ImportError|ModuleNotFoundError", re.I),
         ErrorCategory.DEPENDENCY_MISSING),
        (re.compile(r"GEOS.*exception|TopologyException|Self-intersection|Invalid geometry",
         re.I), ErrorCategory.GEOMETRY_INVALID),
    ]

    def diagnose(self, stderr: str, stdout: str = "") -> ErrorDiagnosis:
        """对错误信息进行诊断分类.

        Parameters
        ----------
        stderr : str
            进程的 stderr 输出
        stdout : str
            进程的 stdout 输出（辅助诊断）

        Returns
        -------
        ErrorDiagnosis
        """
        combined = stderr + "\n" + stdout

        for pattern, category in self.PATTERNS:
            if pattern.search(combined):
                return self._build_diagnosis(category, combined, stderr)

        return ErrorDiagnosis(
            category=ErrorCategory.UNKNOWN,
            confidence=0.3,
            original_error=stderr[:1000],
            suggested_fix="无法自动诊断，需要升级到 Architect Agent 分析",
        )

    def _build_diagnosis(
        self, category: ErrorCategory, full_output: str, stderr: str
    ) -> ErrorDiagnosis:
        """构建带参数的诊断结果."""
        diagnosis = ErrorDiagnosis(
            category=category,
            confidence=0.85,
            original_error=stderr[:1000],
            suggested_fix="",
        )

        if category == ErrorCategory.CRS_MISMATCH:
            epsg_match = re.search(r"EPSG[: ]?(\d{4,6})", full_output)
            if epsg_match:
                diagnosis.extracted_params["epsg"] = int(epsg_match.group(1))
            diagnosis.suggested_fix = (
                "添加 CRS 转换步骤: 在空间操作前使用 QgsCoordinateTransform 统一 CRS"
            )

        elif category == ErrorCategory.PATH_NOT_FOUND:
            path_match = re.search(r"['\"]([^'\"]+\.[a-z]{2,4})['\"]", full_output)
            if path_match:
                diagnosis.extracted_params["missing_path"] = path_match.group(1)
            diagnosis.suggested_fix = (
                "自动修正路径分隔符并验证文件存在性"
            )

        elif category == ErrorCategory.PROJ_ERROR:
            diagnosis.suggested_fix = (
                "修正坐标定义顺序(lat/lon → lon/lat)，添加 PROJ_DATA 环境变量"
            )

        elif category == ErrorCategory.ENCODING_ERROR:
            diagnosis.suggested_fix = (
                "在文件 I/O 中显式指定 encoding='utf-8' 或检测原始编码后转码"
            )

        elif category == ErrorCategory.DEPENDENCY_MISSING:
            mod_match = re.search(r"No module named '(\w+)'", full_output)
            if mod_match:
                diagnosis.extracted_params["missing_module"] = mod_match.group(1)
            diagnosis.suggested_fix = (
                "降级为替代方案: 使用 osgeo.ogr 替代 geopandas / 使用 gdal.Warp 替代 rasterio"
            )

        elif category == ErrorCategory.GEOMETRY_INVALID:
            diagnosis.suggested_fix = (
                "对输入几何体执行 makeValid() / buffer(0) 修复"
            )

        elif category == ErrorCategory.MEMORY_EXHAUSTED:
            diagnosis.suggested_fix = (
                "启用分块处理 (blockSize)，减小单次读取范围"
            )

        return diagnosis


class FeedbackLoop:
    """闭环反馈执行引擎.

    核心逻辑:
    1. 注入脚本到 QGIS 环境执行
    2. 如果失败 → 解析错误 → 自动修正脚本 → 重试
    3. 最多 MAX_RETRIES 轮，超出则升级到 Architect Agent
    """

    MAX_RETRIES = 3

    def __init__(self, qgis_controller=None):
        self.qgis = qgis_controller
        self.parser = ErrorParser()
        self._heal_history: list[HealingResult] = []

    def run(
        self,
        script: str,
        env_context: dict | None = None,
    ) -> ProcessResult:
        """执行脚本并自动进行最多 MAX_RETRIES 轮自愈.

        Parameters
        ----------
        script : str
            初始 PyQGIS Python 脚本
        env_context : dict | None
            环境配置字典

        Returns
        -------
        ProcessResult
        """
        from src.core.qgis_controller import QGISController
        if self.qgis is None:
            self.qgis = QGISController()
            self.qgis.discover()

        current_script = script
        self._heal_history = []

        for attempt in range(self.MAX_RETRIES + 1):
            logger.info(f"执行尝试 {attempt + 1}/{self.MAX_RETRIES + 1}")

            result = self.qgis.execute(current_script)

            if result.success:
                logger.info(f"尝试 {attempt + 1} 成功")
                return result

            # 失败 — 尝试自愈
            if attempt >= self.MAX_RETRIES:
                logger.error(f"已达最大重试次数 ({self.MAX_RETRIES})，自愈失败")
                result.stderr += (
                    f"\n[Geo-OpenClaw] Max retries ({self.MAX_RETRIES}) exceeded. "
                    f"Healing history: {len(self._heal_history)} attempts."
                )
                return result

            diagnosis = self.parser.diagnose(result.stderr, result.stdout)
            logger.warning(
                f"尝试 {attempt + 1} 失败: {diagnosis.category.value} "
                f"(置信度: {diagnosis.confidence:.0%})"
            )

            if diagnosis.category == ErrorCategory.UNKNOWN:
                # 无法自动修复，直接返回
                logger.error("无法诊断错误类型，停止自愈")
                return result

            healed_script = self._apply_fix(
                current_script, diagnosis, attempt
            )
            healing = HealingResult(
                attempt=attempt + 1,
                diagnosis=diagnosis,
                fixed_script=healed_script,
                healed=False,
            )
            self._heal_history.append(healing)

            if healed_script == current_script:
                logger.warning("修复未产生变更，停止重试")
                return result

            current_script = healed_script
            logger.info(f"应用修复方案: {diagnosis.suggested_fix[:80]}")

        return result

    def _apply_fix(
        self, script: str, diagnosis: ErrorDiagnosis, attempt: int
    ) -> str:
        """根据诊断结果对脚本进行自动修正."""
        lines = script.split("\n")
        fixed_lines = []

        if diagnosis.category == ErrorCategory.CRS_MISMATCH:
            # 在脚本头部插入 CRS 转换辅助代码
            crs_fix = (
                "# [Healed] Auto-inserted CRS transform helper\n"
                "from qgis.core import QgsCoordinateReferenceSystem, "
                "QgsCoordinateTransform, QgsProject\n"
                "def _ensure_crs(layer, target_epsg=4326):\n"
                "    src = layer.crs()\n"
                "    dst = QgsCoordinateReferenceSystem(f'EPSG:{target_epsg}')\n"
                "    if src != dst:\n"
                "        xform = QgsCoordinateTransform(src, dst, QgsProject.instance())\n"
                "        layer = processing.run('native:reprojectlayer', {{"
                "            'INPUT': layer, 'TARGET_CRS': dst, 'OUTPUT': 'memory:'"
                "        }})['OUTPUT']\n"
                "    return layer\n"
            )
            fixed_lines.append(crs_fix)
            fixed_lines.extend(lines)

        elif diagnosis.category == ErrorCategory.ENCODING_ERROR:
            fixed_lines = []
            for line in lines:
                # 在 open() 调用中注入 encoding='utf-8'
                if 'open(' in line and 'encoding=' not in line:
                    line = line.replace(
                        "open(", "open(", 1
                    ).replace(")", ", encoding='utf-8')", 1)
                fixed_lines.append(line)
            if fixed_lines == lines:
                fixed_lines.insert(0, "# [Healed] Set default encoding")
                fixed_lines.insert(1, "import sys; sys.stdout.reconfigure(encoding='utf-8')")

        elif diagnosis.category == ErrorCategory.PATH_NOT_FOUND:
            fixed_lines = [
                "# [Healed] Auto path normalization",
                "import os, pathlib",
                "",
            ]
            for line in lines:
                # 将反斜杠统一为正斜杠
                line = line.replace("\\\\", "/").replace("\\", "/")
                fixed_lines.append(line)

        elif diagnosis.category == ErrorCategory.PROJ_ERROR:
            fixed_lines = [
                "# [Healed] PROJ coordinate order fix",
                "import os",
                "os.environ['PROJ_DATA'] = os.environ.get('PROJ_DATA', '')",
                "os.environ['GDAL_FILENAME_IS_UTF8'] = 'YES'",
                "",
            ] + lines

        elif diagnosis.category == ErrorCategory.DEPENDENCY_MISSING:
            mod = diagnosis.extracted_params.get("missing_module", "")
            if mod == "geopandas":
                fixed_lines = [
                    "# [Healed] Fallback: use osgeo.ogr instead of geopandas",
                    "from osgeo import ogr, osr",
                    "# geopandas fallback helper",
                    "def _ogr_read_vector(path):",
                    "    ds = ogr.Open(path)",
                    "    if not ds:",
                    "        raise RuntimeError(f'Cannot open {path}')",
                    "    layer = ds.GetLayer()",
                    "    features = [feat for feat in layer]",
                    "    ds = None",
                    "    return features",
                    "",
                ] + lines

        elif diagnosis.category == ErrorCategory.GEOMETRY_INVALID:
            fixed_lines = []
            for line in lines:
                fixed_lines.append(line)
                # 在 geometry 使用前插入 makeValid
                if '.geometry()' in line and 'makeValid' not in line:
                    fixed_lines.append(
                        "# [Healed] Geometry validation\n"
                        "geom = geom.makeValid()"
                    )

        else:
            fixed_lines = lines.copy()

        return "\n".join(fixed_lines)

    @property
    def heal_history(self) -> list[HealingResult]:
        return self._heal_history
