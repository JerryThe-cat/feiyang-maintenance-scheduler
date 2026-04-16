"""排班核心算法：干事 + 技术员。

约束概要：
- 每人从报名时段中被唯一分配到一个时段。
- 干事在时段内再分配到一个点位。
- 1/4 号位优先维修部；首/末时段优先男性、尽力 ≥6 人。
- 已有排班结果的行跳过（不覆盖）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import (
    ENDPOINT_SLOT_TARGET,
    MAINTENANCE_PREFERRED_POSITIONS,
    POSITION_CAPACITY,
    POSITION_ORDER,
    PREFERRED_DEPARTMENT,
    STAFF_TENTATIVE_SLOT,
    STAFF_TIME_SLOTS,
    TECH_TIME_SLOTS,
)

logger = logging.getLogger(__name__)


# ---------- 数据模型 ----------


@dataclass
class StaffApplicant:
    record_id: str
    name: str
    gender: str  # "男" / "女" / 其他
    departments: List[str]
    applied_slots: List[str]
    already_assigned_slot: Optional[str] = None
    already_assigned_position: Optional[str] = None

    @property
    def is_male(self) -> bool:
        return self.gender.strip() in ("男", "Male", "male", "M", "m")

    @property
    def is_maintenance(self) -> bool:
        return PREFERRED_DEPARTMENT in self.departments

    @property
    def already_scheduled(self) -> bool:
        return bool(self.already_assigned_slot) and bool(self.already_assigned_position)


@dataclass
class TechApplicant:
    record_id: str
    name: str
    applied_slots: List[str]
    already_assigned_slot: Optional[str] = None

    @property
    def already_scheduled(self) -> bool:
        return bool(self.already_assigned_slot)


@dataclass
class StaffAssignment:
    record_id: str
    name: str
    slot: str
    position: str


@dataclass
class TechAssignment:
    record_id: str
    name: str
    slot: str


@dataclass
class StaffScheduleResult:
    assignments: List[StaffAssignment] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)  # 已排过而跳过的 record_id
    unassigned: List[StaffApplicant] = field(default_factory=list)  # 无法安排的
    summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TechScheduleResult:
    assignments: List[TechAssignment] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    unassigned: List[TechApplicant] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


# ---------- 干事排班 ----------


def _normalize_slot(s: str) -> str:
    """去掉所有空白 + 把中文/全角标点替换为英文半角，用于容错匹配。"""
    if not s:
        return ""
    t = "".join(s.split())
    # 常见全角 / 特殊字符替换
    t = t.replace("：", ":").replace("—", "-").replace("–", "-").replace("～", "-").replace("~", "-")
    return t


def _filter_valid_slots(slots: Sequence[str], valid: Sequence[str]) -> List[str]:
    """保留在合法时段列表中的项，过滤掉'暂定'等。返回值使用 valid 里的规范字符串。

    比对使用 _normalize_slot 做容错：'8:00-10:00' / '8:00 - 10:00' / '8：00-10：00' 都能匹配。
    """
    valid_map = {_normalize_slot(v): v for v in valid}
    order = {v: i for i, v in enumerate(valid)}
    seen: set[str] = set()
    filtered: List[str] = []
    for s in slots:
        canonical = valid_map.get(_normalize_slot(s))
        if canonical and canonical not in seen:
            seen.add(canonical)
            filtered.append(canonical)
    filtered.sort(key=lambda s: order[s])
    return filtered


def _active_time_slots(applicants: Sequence[StaffApplicant]) -> List[str]:
    """取当次活动实际启用的时段（按出现过的合法时段取集合，保持默认顺序）。"""
    used = set()
    for a in applicants:
        for s in a.applied_slots:
            if s in STAFF_TIME_SLOTS:
                used.add(s)
    return [s for s in STAFF_TIME_SLOTS if s in used]


def schedule_staff(raw_applicants: Sequence[StaffApplicant]) -> StaffScheduleResult:
    """核心调度：贪心 + 多轮优先级。"""
    result = StaffScheduleResult()

    # 规范化：过滤暂定，去除已排班的人
    applicants: List[StaffApplicant] = []
    for a in raw_applicants:
        a.applied_slots = _filter_valid_slots(a.applied_slots, STAFF_TIME_SLOTS)
        if a.already_scheduled:
            result.skipped.append(a.record_id)
            continue
        if not a.applied_slots:
            # 仅报名暂定 / 无有效时段
            result.unassigned.append(a)
            continue
        applicants.append(a)

    active_slots = _active_time_slots(applicants)
    if not active_slots:
        result.summary = {"message": "无有效报名数据", "slots": {}}
        return result

    first_slot = active_slots[0]
    last_slot = active_slots[-1]
    endpoint_slots = {first_slot, last_slot}

    # 每时段每点位当前已分配人数
    slot_slots: Dict[str, Dict[str, List[StaffApplicant]]] = {
        s: {p: [] for p in POSITION_ORDER} for s in active_slots
    }

    assigned_ids: set[str] = set()

    # ---- Pass 1：为 1/4 号位优先分配维修部干事 ----
    # 顺序：先处理首末时段（它们同样需要 1/4 号位）
    slot_process_order = _slot_process_order(active_slots, endpoint_slots)

    for slot in slot_process_order:
        for pos in ("1号位", "4号位"):
            if _pos_full(slot_slots[slot][pos], pos):
                continue
            cand = _pick_candidate(
                applicants,
                assigned_ids,
                slot=slot,
                prefer_maintenance=True,
                prefer_male=(slot in endpoint_slots),
            )
            if cand is not None:
                slot_slots[slot][pos].append(cand)
                assigned_ids.add(cand.record_id)

    # ---- Pass 2：补齐 1/4 号位（不限部门），再填 5/6 号位 ----
    for slot in slot_process_order:
        for pos in ("1号位", "4号位", "5号位", "6号位"):
            while not _pos_full(slot_slots[slot][pos], pos):
                cand = _pick_candidate(
                    applicants,
                    assigned_ids,
                    slot=slot,
                    prefer_maintenance=(pos in MAINTENANCE_PREFERRED_POSITIONS),
                    prefer_male=(slot in endpoint_slots),
                )
                if cand is None:
                    break
                slot_slots[slot][pos].append(cand)
                assigned_ids.add(cand.record_id)

    # ---- Pass 3：机动位（≤2） ----
    for slot in slot_process_order:
        pos = "机动位"
        while not _pos_full(slot_slots[slot][pos], pos):
            cand = _pick_candidate(
                applicants,
                assigned_ids,
                slot=slot,
                prefer_maintenance=False,
                prefer_male=(slot in endpoint_slots),
            )
            if cand is None:
                break
            slot_slots[slot][pos].append(cand)
            assigned_ids.add(cand.record_id)

    # ---- Pass 4：首末时段"尽力而为 ≥6 人" ----
    # 此时 1~6 + 机动位 已经填到上限；若首末时段总人数仍不足 6，塞到学习位
    for slot in (first_slot, last_slot):
        while _slot_total(slot_slots[slot]) < ENDPOINT_SLOT_TARGET:
            cand = _pick_candidate(
                applicants,
                assigned_ids,
                slot=slot,
                prefer_maintenance=False,
                prefer_male=True,
            )
            if cand is None:
                break
            slot_slots[slot]["学习位"].append(cand)
            assigned_ids.add(cand.record_id)

    # ---- Pass 5：所有剩余干事进入学习位（优先放到仍有人报名的时段） ----
    remaining = [a for a in applicants if a.record_id not in assigned_ids]
    # 将剩余人员就地放入他们报了名的某个时段的学习位；若多个，取人最少的
    for a in remaining:
        target = min(
            a.applied_slots,
            key=lambda s: _slot_total(slot_slots[s]),
            default=None,
        )
        if target is None:
            result.unassigned.append(a)
            continue
        slot_slots[target]["学习位"].append(a)
        assigned_ids.add(a.record_id)

    # ---- 汇总 ----
    for slot in active_slots:
        for pos in POSITION_ORDER:
            for a in slot_slots[slot][pos]:
                result.assignments.append(
                    StaffAssignment(
                        record_id=a.record_id,
                        name=a.name,
                        slot=slot,
                        position=pos,
                    )
                )

    result.summary = _build_staff_summary(slot_slots, active_slots, endpoint_slots)
    return result


def _slot_process_order(
    active_slots: Sequence[str], endpoint_slots: set[str]
) -> List[str]:
    """先处理首末，再处理中间时段。"""
    head = [s for s in active_slots if s in endpoint_slots]
    mid = [s for s in active_slots if s not in endpoint_slots]
    return head + mid


def _pos_full(occupants: List[StaffApplicant], pos: str) -> bool:
    return len(occupants) >= POSITION_CAPACITY[pos]


def _slot_total(pos_map: Dict[str, List[StaffApplicant]]) -> int:
    return sum(len(v) for v in pos_map.values())


def _pick_candidate(
    applicants: Sequence[StaffApplicant],
    assigned_ids: set[str],
    slot: str,
    prefer_maintenance: bool,
    prefer_male: bool,
) -> Optional[StaffApplicant]:
    """从未分配人员中挑一个最合适的，优先顺序通过 (是否维修部, 是否男, 备选时段数越少越优先)。"""
    best: Optional[StaffApplicant] = None
    best_key: Optional[Tuple[int, int, int]] = None

    for a in applicants:
        if a.record_id in assigned_ids:
            continue
        if slot not in a.applied_slots:
            continue

        key = (
            0 if (prefer_maintenance and a.is_maintenance) else 1,
            0 if (prefer_male and a.is_male) else 1,
            len(a.applied_slots),  # 报名时段越少越优先（灵活度低）
        )
        if best is None or key < best_key:  # type: ignore[operator]
            best = a
            best_key = key
    return best


def _build_staff_summary(
    slot_slots: Dict[str, Dict[str, List[StaffApplicant]]],
    active_slots: Sequence[str],
    endpoint_slots: set[str],
) -> Dict[str, Any]:
    slot_stats = {}
    total = 0
    for slot in active_slots:
        per_pos = {p: len(slot_slots[slot][p]) for p in POSITION_ORDER}
        slot_total = sum(per_pos.values())
        total += slot_total
        slot_stats[slot] = {
            "总人数": slot_total,
            "按点位": per_pos,
            "首末目标差额": (
                max(ENDPOINT_SLOT_TARGET - slot_total, 0) if slot in endpoint_slots else 0
            ),
        }
    return {"总分配人数": total, "各时段": slot_stats, "首末时段": sorted(endpoint_slots)}


# ---------- 技术员排班 ----------


def schedule_technicians(raw_applicants: Sequence[TechApplicant]) -> TechScheduleResult:
    """技术员排班：平衡各时段人数，不涉及点位。"""
    result = TechScheduleResult()

    applicants: List[TechApplicant] = []
    for a in raw_applicants:
        a.applied_slots = _filter_valid_slots(a.applied_slots, TECH_TIME_SLOTS)
        if a.already_scheduled:
            result.skipped.append(a.record_id)
            continue
        if not a.applied_slots:
            result.unassigned.append(a)
            continue
        applicants.append(a)

    # 按报名时段数升序处理（灵活度低的优先固定），稳定排序保证可重现
    applicants.sort(key=lambda x: (len(x.applied_slots), x.name))

    slot_counts: Dict[str, int] = {s: 0 for s in TECH_TIME_SLOTS}
    for a in applicants:
        # 在其报名时段中，选当前人数最少的（负载均衡）
        target = min(a.applied_slots, key=lambda s: slot_counts[s])
        slot_counts[target] += 1
        result.assignments.append(
            TechAssignment(record_id=a.record_id, name=a.name, slot=target)
        )

    result.summary = {"各时段人数": slot_counts, "总分配人数": sum(slot_counts.values())}
    return result


# ---------- 与多维表格记录互转 ----------


def _as_str_list(val: Any) -> List[str]:
    """飞书多选字段可能是 ['a','b'] 或 'a'，文本字段也可能返回复杂结构。"""
    if val is None:
        return []
    if isinstance(val, list):
        out: List[str] = []
        for item in val:
            if isinstance(item, str):
                out.append(item.strip())
            elif isinstance(item, dict):
                # 可能是 {"text": "..."} 或 {"name": "..."}
                for k in ("text", "name", "value"):
                    if k in item and isinstance(item[k], str):
                        out.append(item[k].strip())
                        break
        return [s for s in out if s]
    if isinstance(val, str):
        return [val.strip()] if val.strip() else []
    return []


def _as_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        parts = _as_str_list(val)
        return parts[0] if parts else ""
    if isinstance(val, dict):
        for k in ("text", "name", "value"):
            if k in val and isinstance(val[k], str):
                return val[k].strip()
    return str(val).strip()


def build_staff_applicants(
    records: Sequence[Dict[str, Any]],
    field_map: Dict[str, str],
) -> List[StaffApplicant]:
    """将 bitable 记录转为 StaffApplicant。field_map 见 Field* 常量。"""
    out: List[StaffApplicant] = []
    for r in records:
        fields = r.get("fields", {}) or {}
        out.append(
            StaffApplicant(
                record_id=r.get("record_id") or r.get("id", ""),
                name=_as_str(fields.get(field_map["name"])),
                gender=_as_str(fields.get(field_map["gender"])),
                departments=_as_str_list(fields.get(field_map["department"])),
                applied_slots=_as_str_list(fields.get(field_map["applied_slots"])),
                already_assigned_slot=_as_str(fields.get(field_map["assigned_slot"])) or None,
                already_assigned_position=_as_str(fields.get(field_map["assigned_position"])) or None,
            )
        )
    return out


def build_tech_applicants(
    records: Sequence[Dict[str, Any]],
    field_map: Dict[str, str],
) -> List[TechApplicant]:
    out: List[TechApplicant] = []
    for r in records:
        fields = r.get("fields", {}) or {}
        out.append(
            TechApplicant(
                record_id=r.get("record_id") or r.get("id", ""),
                name=_as_str(fields.get(field_map["name"])),
                applied_slots=_as_str_list(fields.get(field_map["applied_slots"])),
                already_assigned_slot=_as_str(fields.get(field_map["assigned_slot"])) or None,
            )
        )
    return out
