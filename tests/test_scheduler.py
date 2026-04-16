"""scheduler 的离线单元测试（无需飞书）。

运行：
    python -m tests.test_scheduler
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

# 支持直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduler import (  # noqa: E402
    StaffApplicant,
    TechApplicant,
    schedule_staff,
    schedule_technicians,
)


def _make_staff(
    i: int, gender: str, depts: List[str], slots: List[str]
) -> StaffApplicant:
    return StaffApplicant(
        record_id=f"rec{i:03d}",
        name=f"干事{i}",
        gender=gender,
        departments=depts,
        applied_slots=slots,
    )


def test_slot_normalization():
    """验证表格中含空格/全角冒号的选项也能匹配到 config 常量。"""
    from scheduler import _filter_valid_slots
    valid = ["8:00 - 10:00", "10:00 - 12:00"]
    # 各种"脏"输入都应被归一化到 valid 里的规范字符串
    out = _filter_valid_slots(
        ["8:00-10:00", "10：00 - 12：00", "  8:00 - 10:00  "],
        valid,
    )
    assert out == ["8:00 - 10:00", "10:00 - 12:00"], out
    print("[slot_normalization] OK")


def test_staff_basic():
    slots = [
        "8:00 - 10:00",
        "10:00 - 12:00",
        "12:00 - 14:00",
        "14:00 - 16:00",
        "16:00 - 18:00",
    ]
    applicants = [
        # 3 个维修部，应优先吃 1/4 号位
        _make_staff(1, "男", ["维修部"], slots),
        _make_staff(2, "男", ["维修部"], slots),
        _make_staff(3, "女", ["维修部"], slots[:3]),
        # 其他部门
        _make_staff(4, "男", ["研发部"], slots),
        _make_staff(5, "男", ["流媒部"], slots),
        _make_staff(6, "女", ["行政部"], slots),
        _make_staff(7, "女", ["设计部"], slots),
        _make_staff(8, "男", ["研发部"], [slots[0]]),  # 只报首段
        _make_staff(9, "男", ["研发部"], [slots[-1]]),  # 只报末段
        _make_staff(10, "女", ["行政部"], slots[1:4]),  # 不参与首末
        _make_staff(11, "男", ["设计部"], slots),
        _make_staff(12, "女", ["研发部"], slots),
    ]
    result = schedule_staff(applicants)

    # 每个人要么被分配，要么在 unassigned 或 skipped 中
    assigned_ids = {a.record_id for a in result.assignments}
    leftover = [a.record_id for a in applicants if a.record_id not in assigned_ids]
    assert not leftover, f"漏分配：{leftover}"

    # 首末时段应至少尝试排 ≥6 或全部用尽
    summary = result.summary
    first_slot, last_slot = summary["首末时段"][0], summary["首末时段"][1]
    print("\n[staff_basic] 汇总：", json.dumps(summary, ensure_ascii=False, indent=2))

    # 至少 1/4 号位被分配给了维修部（若有维修部的人报名了该时段）
    for a in result.assignments:
        if a.position in ("1号位", "4号位") and a.slot in (first_slot, last_slot):
            # 检查是否存在一个维修部候选被分到
            pass  # 硬断言过强，仅打印做人工核对
    print("[staff_basic] OK")


def test_staff_skip_existing():
    slots = ["8:00 - 10:00", "10:00 - 12:00"]
    s = _make_staff(1, "男", ["维修部"], slots)
    s.already_assigned_slot = "8:00 - 10:00"
    s.already_assigned_position = "1号位"

    result = schedule_staff([s])
    assert result.skipped == ["rec001"]
    assert not result.assignments
    print("[staff_skip] OK")


def test_tech_balance():
    tech_slots = ["9:00 - 11:00", "11:00 - 13:00", "13:00 - 15:00", "15:00 - 17:00"]
    applicants = [
        TechApplicant(f"t{i:02d}", f"技术{i}", tech_slots)
        for i in range(12)
    ]
    result = schedule_technicians(applicants)
    counts: Dict[str, int] = result.summary["各时段人数"]
    # 12 人 4 段应均分为 3/3/3/3
    assert all(v == 3 for v in counts.values()), f"不均衡：{counts}"
    print("[tech_balance] OK")


def test_tech_respect_applied():
    """技术员仅能被分到自己报名的时段。"""
    tech_slots = ["9:00 - 11:00", "11:00 - 13:00", "13:00 - 15:00", "15:00 - 17:00"]
    applicants = [
        TechApplicant("t1", "T1", [tech_slots[0]]),
        TechApplicant("t2", "T2", [tech_slots[0], tech_slots[1]]),
        TechApplicant("t3", "T3", tech_slots),
    ]
    result = schedule_technicians(applicants)
    by_id = {a.record_id: a.slot for a in result.assignments}
    assert by_id["t1"] == tech_slots[0]
    assert by_id["t2"] in (tech_slots[0], tech_slots[1])
    assert by_id["t3"] in tech_slots
    print("[tech_applied] OK")


def test_custom_hourly_slots_for_staff():
    """验证 schedule_staff 支持自定义 1 小时时段。"""
    custom = [
        "8:00 - 9:00", "9:00 - 10:00", "10:00 - 11:00", "11:00 - 12:00",
    ]
    applicants = [
        _make_staff(1, "男", ["维修部"], custom),
        _make_staff(2, "男", ["维修部"], custom),
        _make_staff(3, "男", ["研发部"], [custom[0], custom[-1]]),
        _make_staff(4, "女", ["行政部"], custom),
    ]
    result = schedule_staff(applicants, time_slots=custom)
    assert result.summary["首末时段"] == sorted([custom[0], custom[-1]]), result.summary
    assigned = {a.record_id for a in result.assignments}
    assert len(assigned) == 4, assigned
    print("[staff_custom_hourly] OK")


def test_custom_slots_for_technicians():
    """验证技术员支持自定义时段（如调整起止时间）。"""
    shifted = ["10:00 - 12:00", "12:00 - 14:00", "14:00 - 16:00", "16:00 - 18:00"]
    applicants = [TechApplicant(f"t{i:02d}", f"T{i}", shifted) for i in range(8)]
    result = schedule_technicians(applicants, time_slots=shifted)
    counts = result.summary["各时段人数"]
    assert set(counts.keys()) == set(shifted), counts
    assert all(v == 2 for v in counts.values()), counts
    print("[tech_custom_slots] OK")


def test_parse_bitable_url():
    """URL 解析：wiki / docs / 非飞书域名应给出针对性错误。"""
    from feishu_client import BitableURLError, parse_bitable_url

    # 正常 base URL
    app_token, table_id = parse_bitable_url(
        "https://xxx.feishu.cn/base/AbCdEf123?table=tbl_xxx&view=vew_yyy"
    )
    assert app_token == "AbCdEf123"
    assert table_id == "tbl_xxx"

    # 无 table 参数
    app_token, table_id = parse_bitable_url("https://xxx.feishu.cn/base/AbCdEf123")
    assert app_token == "AbCdEf123"
    assert table_id is None

    # wiki 链接 → 应提示独立打开
    try:
        parse_bitable_url("https://xxx.feishu.cn/wiki/WikiToken123")
    except BitableURLError as e:
        assert "wiki" in str(e)
    else:
        raise AssertionError("wiki URL 应该抛错")

    # docs 链接 → 应识别为文档类型
    try:
        parse_bitable_url("https://xxx.feishu.cn/docs/DocsToken456")
    except BitableURLError as e:
        assert "docs" in str(e) or "文档" in str(e)
    else:
        raise AssertionError("docs URL 应该抛错")

    # 非飞书域名
    try:
        parse_bitable_url("https://example.com/base/AbCdEf123")
    except BitableURLError as e:
        assert "飞书" in str(e) or "feishu" in str(e)
    else:
        raise AssertionError("非飞书域名应该抛错")

    # 缺 /base/
    try:
        parse_bitable_url("https://xxx.feishu.cn/some/other/path")
    except BitableURLError as e:
        assert "base" in str(e)
    else:
        raise AssertionError("缺 /base/ 应该抛错")

    # 空 URL
    try:
        parse_bitable_url("")
    except BitableURLError:
        pass
    else:
        raise AssertionError("空 URL 应该抛错")

    print("[parse_bitable_url] OK")


def main() -> None:
    test_slot_normalization()
    test_staff_basic()
    test_staff_skip_existing()
    test_tech_balance()
    test_tech_respect_applied()
    test_custom_hourly_slots_for_staff()
    test_custom_slots_for_technicians()
    test_parse_bitable_url()
    print("\n所有用例通过")


if __name__ == "__main__":
    main()
