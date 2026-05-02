"""缓冲区分析 Skill — 可在 QGIS Python 中直接执行."""


def run(input_path: str, distance: float, output_path: str,
        unit: str = "meters", segments: int = 30, dissolve: bool = False) -> dict:
    """执行缓冲区分析.

    该脚本会被 Executor Agent 注入到 QGIS Python 环境执行。
    """
    from qgis.core import QgsApplication, QgsVectorLayer

    app = QgsApplication([], False)
    app.initQgis()

    try:
        import processing

        layer = QgsVectorLayer(input_path, "input", "ogr")
        if not layer.isValid():
            return {"success": False, "error": f"无法加载: {input_path}"}

        result = processing.run("native:buffer", {
            "INPUT": layer,
            "DISTANCE": distance,
            "SEGMENTS": segments,
            "DISSOLVE": dissolve,
            "OUTPUT": output_path,
        })

        out_layer = QgsVectorLayer(result["OUTPUT"], "output", "ogr")
        count = out_layer.featureCount() if out_layer.isValid() else 0

        return {
            "success": True,
            "output_path": output_path,
            "feature_count": count,
            "params": {"distance": distance, "unit": unit, "segments": segments},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        app.exitQgis()
