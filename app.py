from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

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
from feishu_client import FeishuAPIError, FeishuClient, parse_bitable_url
from scheduler import (
    build_staff_applicants,
    build_tech_applicants,
    schedule_staff,
    schedule_technicians,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _get_client() -> FeishuClient:
    return FeishuClient(load_feishu_config())


# ---------- 路由 ----------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tables", methods=["POST"])
def api_list_tables():
    """根据多维表格 URL 列出所有数据表。"""
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "缺少多维表格 URL"}), 400

    try:
        app_token, table_id_in_url = parse_bitable_url(url)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        client = _get_client()
        tables = client.list_tables(app_token)
    except FeishuAPIError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_tables failed")
        return jsonify({"ok": False, "error": f"未知错误：{exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "app_token": app_token,
            "preselected_table_id": table_id_in_url,
            "tables": [
                {"table_id": t.get("table_id"), "name": t.get("name")} for t in tables
            ],
        }
    )


@app.route("/api/inspect", methods=["POST"])
def api_inspect():
    """诊断接口：返回字段元信息 + 前 3 条样本记录的原始字段值。"""
    payload = request.get_json(silent=True) or {}
    app_token = (payload.get("app_token") or "").strip()
    table_id = (payload.get("table_id") or "").strip()
    if not app_token or not table_id:
        return jsonify({"ok": False, "error": "缺少 app_token / table_id"}), 400

    try:
        client = _get_client()
        fields = client.list_fields(app_token, table_id)
        records = client.list_records(app_token, table_id)
    except FeishuAPIError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    except Exception as exc:  # noqa: BLE001
        logger.exception("inspect failed")
        return jsonify({"ok": False, "error": f"未知错误：{exc}"}), 500

    # 字段元信息
    field_info = [
        {
            "name": f.get("field_name") or f.get("name"),
            "type": f.get("type"),
            "ui_type": f.get("ui_type") or f.get("property", {}).get("ui_type"),
        }
        for f in fields
    ]

    samples = [r.get("fields", {}) for r in records[:3]]

    return jsonify(
        {
            "ok": True,
            "total_records": len(records),
            "fields": field_info,
            "samples": samples,
        }
    )


@app.route("/api/schedule", methods=["POST"])
def api_schedule():
    """执行排班并回填。"""
    payload = request.get_json(silent=True) or {}
    app_token = (payload.get("app_token") or "").strip()
    table_id = (payload.get("table_id") or "").strip()
    mode = (payload.get("mode") or "").strip()  # "staff" | "technician"
    dry_run = bool(payload.get("dry_run"))
    custom_fields: Dict[str, str] = payload.get("fields") or {}

    if not app_token or not table_id or mode not in ("staff", "technician"):
        return jsonify({"ok": False, "error": "缺少必要参数"}), 400

    try:
        client = _get_client()
        records = client.list_records(app_token, table_id)
    except FeishuAPIError as exc:
        return jsonify({"ok": False, "error": f"读取记录失败：{exc}"}), 502
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_records failed")
        return jsonify({"ok": False, "error": f"未知错误：{exc}"}), 500

    if mode == "staff":
        field_map = {
            "name": custom_fields.get("name") or FIELD_STAFF_NAME,
            "gender": custom_fields.get("gender") or FIELD_STAFF_GENDER,
            "department": custom_fields.get("department") or FIELD_STAFF_DEPARTMENT,
            "applied_slots": custom_fields.get("applied_slots") or FIELD_STAFF_APPLIED_SLOTS,
            "assigned_slot": custom_fields.get("assigned_slot") or FIELD_STAFF_ASSIGNED_SLOT,
            "assigned_position": custom_fields.get("assigned_position")
            or FIELD_STAFF_ASSIGNED_POSITION,
        }
        applicants = build_staff_applicants(records, field_map)
        result = schedule_staff(applicants)
        updates = [
            (
                a.record_id,
                {
                    field_map["assigned_slot"]: a.slot,
                    field_map["assigned_position"]: a.position,
                },
            )
            for a in result.assignments
        ]
        resp_body: Dict[str, Any] = {
            "ok": True,
            "mode": "staff",
            "dry_run": dry_run,
            "assignments": [
                {"record_id": a.record_id, "name": a.name, "slot": a.slot, "position": a.position}
                for a in result.assignments
            ],
            "skipped_count": len(result.skipped),
            "unassigned": [
                {"record_id": a.record_id, "name": a.name, "applied_slots": a.applied_slots}
                for a in result.unassigned
            ],
            "summary": result.summary,
        }
    else:
        field_map = {
            "name": custom_fields.get("name") or FIELD_TECH_NAME,
            "applied_slots": custom_fields.get("applied_slots") or FIELD_TECH_APPLIED_SLOTS,
            "assigned_slot": custom_fields.get("assigned_slot") or FIELD_TECH_ASSIGNED_SLOT,
        }
        applicants = build_tech_applicants(records, field_map)
        result = schedule_technicians(applicants)
        updates = [
            (a.record_id, {field_map["assigned_slot"]: a.slot})
            for a in result.assignments
        ]
        resp_body = {
            "ok": True,
            "mode": "technician",
            "dry_run": dry_run,
            "assignments": [
                {"record_id": a.record_id, "name": a.name, "slot": a.slot}
                for a in result.assignments
            ],
            "skipped_count": len(result.skipped),
            "unassigned": [
                {"record_id": a.record_id, "name": a.name, "applied_slots": a.applied_slots}
                for a in result.unassigned
            ],
            "summary": result.summary,
        }

    written = 0
    if not dry_run and updates:
        try:
            written = client.batch_update_records(app_token, table_id, updates)
        except FeishuAPIError as exc:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"写回结果失败：{exc}",
                        "preview": resp_body,
                    }
                ),
                502,
            )

    resp_body["written"] = written
    return jsonify(resp_body)


# ---------- 入口 ----------


def main() -> None:
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    logger.info("starting on http://%s:%s", host, port)
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
