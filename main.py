"""CLI 入口：便于在不启动 Web 服务时直接排班。

用法示例：
    # 为干事排班（从 URL 自动解析 app_token，若 URL 未带 table 需 --table-id 指定）
    python main.py staff --url "https://xxx.feishu.cn/base/<app_token>?table=<table_id>"

    # 为技术员排班，仅预览
    python main.py technician --url "..." --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict

from config import (
    FIELD_STAFF_APPLIED_SLOTS,
    FIELD_STAFF_ASSIGNED_POSITION,
    FIELD_STAFF_ASSIGNED_SLOT,
    FIELD_STAFF_DEPARTMENT,
    FIELD_STAFF_GENDER,
    FIELD_STAFF_NAME,
    FIELD_TECH_APPLIED_SLOTS,
    FIELD_TECH_ASSIGNED_SLOT,
    FIELD_TECH_NAME,
    load_feishu_config,
)
from feishu_client import FeishuClient, parse_bitable_url
from scheduler import (
    build_staff_applicants,
    build_tech_applicants,
    schedule_staff,
    schedule_technicians,
)


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="大修活动自动化排班 CLI")
    ap.add_argument("mode", choices=["staff", "technician"], help="排班类型")
    ap.add_argument("--url", required=False, help="多维表格 URL（会自动解析 app_token / table_id）")
    ap.add_argument("--app-token", help="app_token（与 --url 二选一）")
    ap.add_argument("--table-id", help="数据表 ID（可覆盖 URL 中的值）")
    ap.add_argument("--dry-run", action="store_true", help="仅打印结果，不写回表格")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    app_token = args.app_token
    table_id = args.table_id
    if args.url:
        parsed_app, parsed_table = parse_bitable_url(args.url)
        app_token = app_token or parsed_app
        table_id = table_id or parsed_table
    if not app_token or not table_id:
        print("错误：请提供 --url（含 table 参数）或同时提供 --app-token/--table-id", file=sys.stderr)
        return 2

    client = FeishuClient(load_feishu_config())
    records = client.list_records(app_token, table_id)
    print(f"读取 {len(records)} 条记录，开始排班……")

    if args.mode == "staff":
        field_map = {
            "name": FIELD_STAFF_NAME,
            "gender": FIELD_STAFF_GENDER,
            "department": FIELD_STAFF_DEPARTMENT,
            "applied_slots": FIELD_STAFF_APPLIED_SLOTS,
            "assigned_slot": FIELD_STAFF_ASSIGNED_SLOT,
            "assigned_position": FIELD_STAFF_ASSIGNED_POSITION,
        }
        result = schedule_staff(build_staff_applicants(records, field_map))
        updates = [
            (
                a.record_id,
                {field_map["assigned_slot"]: a.slot, field_map["assigned_position"]: a.position},
            )
            for a in result.assignments
        ]
    else:
        field_map = {
            "name": FIELD_TECH_NAME,
            "applied_slots": FIELD_TECH_APPLIED_SLOTS,
            "assigned_slot": FIELD_TECH_ASSIGNED_SLOT,
        }
        result = schedule_technicians(build_tech_applicants(records, field_map))
        updates = [(a.record_id, {field_map["assigned_slot"]: a.slot}) for a in result.assignments]

    print("\n===== 分配摘要 =====")
    print(json.dumps(result.summary, ensure_ascii=False, indent=2))
    print(f"\n将写入 {len(updates)} 条更新，跳过 {len(result.skipped)} 条，未能分配 {len(result.unassigned)} 条")

    if args.dry_run:
        print("--dry-run：不写回表格。")
        return 0

    if updates:
        written = client.batch_update_records(app_token, table_id, updates)
        print(f"成功写回 {written} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
