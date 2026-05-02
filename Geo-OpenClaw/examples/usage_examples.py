# -*- coding: utf-8 -*-
"""Geo-OpenClaw 使用示例 — 展示三 Agent 流水线的各种用法."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def example_1_heuristic_mode():
    """示例 1: 启发式模式 — 无需 LLM API Key."""
    print("=" * 60)
    print(" 示例 1: 启发式模式 (无 LLM)")
    print("=" * 60)

    from src.agents.architect_agent import ArchitectAgent

    agent = ArchitectAgent(llm_client=None)
    plan = agent.design(
        "将 D:/data/landsat/ 下所有 TIFF 文件重投影到 EPSG:3857，"
        "然后按照 study_area.shp 的范围裁剪"
    )

    print(plan.to_yaml_str())
    print(f"\n依赖项: {plan.required_dependencies}")
    print(f"估算 Token: {plan.estimated_total_cost:,}")


def example_2_environment_detection():
    """示例 2: 环境自动检测."""
    print("\n" + "=" * 60)
    print(" 示例 2: 环境自动检测")
    print("=" * 60)

    from src.agents.environment_agent import EnvironmentAgent

    agent = EnvironmentAgent()
    ctx = agent.prepare()

    print(ctx.summary())
    print(f"\n关键缺失: {ctx.critical_missing}")
    print(f"环境变量数: {len(ctx.env_vars)}")


def example_3_self_healing():
    """示例 3: 自愈反馈机制演示."""
    print("\n" + "=" * 60)
    print(" 示例 3: Self-Healing 反馈机制")
    print("=" * 60)

    from src.core.feedback_loop import ErrorParser

    parser = ErrorParser()

    # 模拟常见错误
    test_errors = [
        ("CRS错误",
         "ERROR: No transform available between EPSG:4326 and EPSG:3857"),
        ("路径错误",
         "FileNotFoundError: No such file or directory: 'D:\\\\data\\\\roads.shp'"),
        ("编码错误",
         "UnicodeDecodeError: 'gbk' codec can't decode byte 0x80"),
        ("依赖缺失",
         "ModuleNotFoundError: No module named 'geopandas'"),
        ("PROJ错误",
         "ERROR 1: PROJ: webmerc: Invalid latitude"),
    ]

    for label, err_msg in test_errors:
        diagnosis = parser.diagnose(err_msg)
        print(f"\n[{label}]")
        print(f"  分类: {diagnosis.category.value} (置信度: {diagnosis.confidence:.0%})")
        print(f"  修复: {diagnosis.suggested_fix[:80]}...")


def example_4_token_tracking():
    """示例 4: Token 消耗追踪."""
    print("\n" + "=" * 60)
    print(" 示例 4: Token 消耗可视化")
    print("=" * 60)

    from src.utils.logger import TokenCounter

    counter = TokenCounter(
        architect=1820000,
        environment=520000,
        executor=1720000,
        orchestrator=620000,
        feedback=520000,
    )

    print(counter.visual_bar())
    print(f"\n总 Token: {counter.total:,}")


def example_5_full_pipeline_simulation():
    """示例 5: 完整流水线模拟 — 展示三 Agent 协作."""
    print("\n" + "=" * 60)
    print(" 示例 5: 完整流水线模拟")
    print("=" * 60)

    from src.agents.architect_agent import ArchitectAgent
    from src.agents.environment_agent import EnvironmentAgent

    # Phase 1: Architect
    print("\n[Phase 1] Architect Agent 工作流设计...")
    architect = ArchitectAgent(llm_client=None)
    plan = architect.design(
        "对 100 景 Landsat-8 影像计算 NDVI，并按照中国省级行政区划进行分区统计"
    )
    print(f"  节点数: {len(plan.workflow_nodes)}")
    print(f"  技能: {[n.skill for n in plan.workflow_nodes]}")

    # Phase 2: Environment
    print("\n[Phase 2] Environment Agent 环境准备...")
    env_agent = EnvironmentAgent()
    ctx = env_agent.prepare(plan.required_dependencies)
    print(f"  QGIS: {'OK' if ctx.qgis_available else 'N/A'}")
    print(f"  依赖: {sum(1 for d in ctx.dependencies if d.available)}/{len(ctx.dependencies)}")

    # Phase 3: Executor (模拟)
    print("\n[Phase 3] Executor Agent 脚本编译...")
    from src.agents.executor_agent import ExecutorAgent
    executor = ExecutorAgent(max_retries=3)
    script = executor._compile_script(plan, ctx)
    print(f"  脚本大小: {len(script):,} 字符")
    print(f"  行数: {script.count(chr(10))} 行")

    # Token 汇总
    from src.utils.logger import TokenCounter
    counter = TokenCounter(
        architect=plan.token_cost,
        environment=ctx.token_cost,
        executor=len(script) * 2 + 500,
    )
    print(f"\n  Token 预估消耗:")
    print(f"    Architect:   {counter.architect:,}")
    print(f"    Environment: {counter.environment:,}")
    print(f"    Executor:    {counter.executor:,}")
    print(f"    Total:       {counter.total:,}")


if __name__ == "__main__":
    example_1_heuristic_mode()
    example_2_environment_detection()
    example_3_self_healing()
    example_4_token_tracking()
    example_5_full_pipeline_simulation()
    print("\n[ALL EXAMPLES COMPLETE]")
