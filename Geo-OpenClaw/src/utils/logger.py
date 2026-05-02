"""结构化日志系统 — 支持 Token 计数和分级输出."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass


@dataclass
class TokenCounter:
    """多 Agent Token 消耗追踪器."""

    architect: int = 0
    environment: int = 0
    executor: int = 0
    orchestrator: int = 0
    feedback: int = 0

    def add(self, agent: str, tokens: int) -> None:
        if hasattr(self, agent):
            setattr(self, agent, getattr(self, agent) + tokens)

    @property
    def total(self) -> int:
        return (self.architect + self.environment +
                self.executor + self.orchestrator + self.feedback)

    def breakdown(self) -> dict[str, int]:
        return {
            "architect": self.architect,
            "environment": self.environment,
            "executor": self.executor,
            "orchestrator": self.orchestrator,
            "feedback": self.feedback,
            "total": self.total,
        }

    def visual_bar(self, width: int = 50) -> str:
        """生成 ASCII 柱状图."""
        total = max(self.total, 1)
        lines = ["Token 消耗分布:"]
        labels = [
            ("Architect", self.architect),
            ("Environment", self.environment),
            ("Executor", self.executor),
            ("Orchestrator", self.orchestrator),
            ("Feedback", self.feedback),
        ]
        max_label = max(len(l) for l, _ in labels)
        for label, tokens in labels:
            bar_len = int(tokens / total * width)
            bar = "█" * bar_len + "░" * (width - bar_len)
            pct = tokens / total * 100
            lines.append(f"  {label:<{max_label}} {bar} {pct:5.1f}% ({tokens:,})")
        lines.append(f"  {'TOTAL':<{max_label}} {'─' * width} 100.0% ({total:,})")
        return "\n".join(lines)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """获取结构化的 logger 实例.

    格式: [2026-05-02 14:30:00] [Geo-OpenClaw] [architect_agent] INFO: message
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] [Geo-OpenClaw] [%(name)s] %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
