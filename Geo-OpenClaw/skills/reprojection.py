"""重投影 Skill — 支持矢量和栅格."""


def run(input_path: str, target_crs: str, output_path: str,
        resampling: str = "bilinear") -> dict:
    """执行重投影.

    自动判断输入类型（矢量/栅格）并选择对应的 QGIS 处理算法。
    """
    from qgis.core import QgsApplication

    app = QgsApplication([], False)
    app.initQgis()

    try:
        import processing
        from qgis.core import QgsRasterLayer, QgsVectorLayer

        # 自动检测类型
        is_raster = input_path.lower().endswith(('.tif', '.tiff', '.img', '.vrt'))

        if is_raster:
            result = processing.run("gdal:warpreproject", {
                "INPUT": input_path,
                "TARGET_CRS": target_crs,
                "RESAMPLING": 1 if resampling == "bilinear" else 0,
                "OUTPUT": output_path,
            })
        else:
            result = processing.run("native:reprojectlayer", {
                "INPUT": input_path,
                "TARGET_CRS": target_crs,
                "OUTPUT": output_path,
            })

        return {
            "success": True,
            "output_path": output_path,
            "target_crs": target_crs,
            "type": "raster" if is_raster else "vector",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        app.exitQgis()
