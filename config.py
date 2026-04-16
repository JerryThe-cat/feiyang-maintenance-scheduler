"""应用配置：飞书凭证与常量。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str


def load_feishu_config() -> FeishuConfig:
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET，请检查 .env 配置")
    return FeishuConfig(app_id=app_id, app_secret=app_secret)


# ---------- 业务常量 ----------

DEPARTMENTS: List[str] = ["维修部", "研发部", "行政部", "流媒部", "设计部"]

# 干事 5 个正式时段 + 1 个暂定（暂定不参与排班）
# 注意：这里的字符串需要与表格中单选/多选的选项值完全对应（忽略空白），
# 写回时以下方值为准，所以务必保证单选「安排时间段」里有这些选项。
STAFF_TIME_SLOTS: List[str] = [
    "8:00 - 10:00",
    "10:00 - 12:00",
    "12:00 - 14:00",
    "14:00 - 16:00",
    "16:00 - 18:00",
]
STAFF_TENTATIVE_SLOT = "暂定"

# 技术员 4 个时段
TECH_TIME_SLOTS: List[str] = [
    "9:00 - 11:00",
    "11:00 - 13:00",
    "13:00 - 15:00",
    "15:00 - 17:00",
]

# 点位定义（顺序即填充优先级）
POSITION_ORDER: List[str] = ["1号位", "4号位", "5号位", "6号位", "机动位", "学习位"]
POSITION_CAPACITY = {
    "1号位": 1,
    "4号位": 1,
    "5号位": 1,
    "6号位": 1,
    "机动位": 2,
    "学习位": 10**6,  # 视为无上限
}

# 1/4 号位优先部门
MAINTENANCE_PREFERRED_POSITIONS = {"1号位", "4号位"}
PREFERRED_DEPARTMENT = "维修部"

# 首末时段目标人数（尽力而为）
ENDPOINT_SLOT_TARGET = 6

# ---------- 字段名（可按实际表格调整） ----------

# 干事表字段
FIELD_STAFF_NAME = "姓名"
FIELD_STAFF_GENDER = "性别"
FIELD_STAFF_DEPARTMENT = "部门"
FIELD_STAFF_APPLIED_SLOTS = "报名时间段"
FIELD_STAFF_ASSIGNED_SLOT = "安排时间段"
FIELD_STAFF_ASSIGNED_POSITION = "安排位置"

# 技术员表字段
FIELD_TECH_NAME = "姓名"
FIELD_TECH_APPLIED_SLOTS = "报名时间段"
FIELD_TECH_ASSIGNED_SLOT = "安排时间段"
