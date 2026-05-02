"""通用地理处理原子操作 — 每个函数对应一个可编排的 Skill."""

from __future__ import annotations

from typing import Any


def buffer_analysis(
    input_path: str,
    distance: float,
    unit: str = "meters",
    segments: int = 30,
    dissolve: bool = False,
    output_path: str | None = None,
) -> dict[str, Any]:
    """缓冲区分析 Skill.

    Parameters
    ----------
    input_path : str
        输入矢量文件路径
    distance : float
        缓冲距离
    unit : str
        距离单位 (meters, degrees, kilometers)
    segments : int
        近似圆形的分段数
    dissolve : bool
        是否融合结果
    output_path : str | None
        输出文件路径

    Returns
    -------
    dict
        包含 output_path, feature_count, area 等
    """
    return {
        "skill": "buffer_analysis",
        "input": input_path,
        "params": {"distance": distance, "unit": unit,
                    "segments": segments, "dissolve": dissolve},
        "output_path": output_path or f"{input_path}_buffer.gpkg",
        "status": "ready",
    }


def reprojection(
    input_path: str,
    target_crs: str = "EPSG:3857",
    resampling: str = "bilinear",
    output_path: str | None = None,
) -> dict[str, Any]:
    """重投影 Skill.

    Parameters
    ----------
    input_path : str
        输入文件路径（矢量或栅格）
    target_crs : str
        目标坐标系 EPSG 代码
    resampling : str
        栅格重采样方法 (nearest, bilinear, cubic)
    output_path : str | None
        输出文件路径

    Returns
    -------
    dict
    """
    return {
        "skill": "reprojection",
        "input": input_path,
        "params": {"target_crs": target_crs, "resampling": resampling},
        "output_path": output_path or f"{input_path}_reprojected.tif",
        "status": "ready",
    }


def raster_clip(
    raster_path: str,
    mask_path: str,
    crop_to_cutline: bool = True,
    output_path: str | None = None,
) -> dict[str, Any]:
    """栅格裁剪 Skill.

    Parameters
    ----------
    raster_path : str
        输入栅格文件路径
    mask_path : str
        裁剪边界矢量文件路径
    crop_to_cutline : bool
        是否按边界精确裁剪
    output_path : str | None

    Returns
    -------
    dict
    """
    return {
        "skill": "raster_clip",
        "input": {"raster": raster_path, "mask": mask_path},
        "params": {"crop_to_cutline": crop_to_cutline},
        "output_path": output_path or f"{raster_path}_clipped.tif",
        "status": "ready",
    }


def vector_clip(
    vector_path: str,
    mask_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """矢量裁剪 Skill."""
    return {
        "skill": "vector_clip",
        "input": {"vector": vector_path, "mask": mask_path},
        "params": {},
        "output_path": output_path or f"{vector_path}_clipped.gpkg",
        "status": "ready",
    }


def spatial_join(
    layer_a_path: str,
    layer_b_path: str,
    predicate: str = "intersects",
    join_type: str = "one-to-one",
    output_path: str | None = None,
) -> dict[str, Any]:
    """空间连接 Skill."""
    return {
        "skill": "spatial_join",
        "input": {"layer_a": layer_a_path, "layer_b": layer_b_path},
        "params": {"predicate": predicate, "join_type": join_type},
        "output_path": output_path or "spatial_join_output.gpkg",
        "status": "ready",
    }


def zonal_statistics(
    raster_path: str,
    zones_path: str,
    statistics: list[str] | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """分区统计 Skill."""
    return {
        "skill": "zonal_statistics",
        "input": {"raster": raster_path, "zones": zones_path},
        "params": {"statistics": statistics or ["mean", "sum", "stddev"]},
        "output_path": output_path or "zonal_stats.csv",
        "status": "ready",
    }
