"""飞书开放平台 API 客户端：鉴权 + 多维表格读写。"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from config import FeishuConfig

logger = logging.getLogger(__name__)

OPEN_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuAPIError(RuntimeError):
    """飞书 API 返回非 0 code 时抛出。"""

    def __init__(self, code: int, msg: str, payload: Dict[str, Any] | None = None):
        super().__init__(f"[feishu {code}] {msg}")
        self.code = code
        self.msg = msg
        self.payload = payload or {}


class FeishuClient:
    """最小可用的飞书多维表格客户端。"""

    def __init__(self, config: FeishuConfig, timeout: int = 20):
        self._config = config
        self._timeout = timeout
        self._token: Optional[str] = None
        self._token_expire_at: float = 0.0

    # ---------- 鉴权 ----------

    def _tenant_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire_at - 60:
            return self._token

        url = f"{OPEN_API_BASE}/auth/v3/tenant_access_token/internal"
        resp = requests.post(
            url,
            json={"app_id": self._config.app_id, "app_secret": self._config.app_secret},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuAPIError(data.get("code", -1), data.get("msg", ""), data)

        self._token = data["tenant_access_token"]
        self._token_expire_at = now + int(data.get("expire", 7200))
        return self._token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tenant_access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{OPEN_API_BASE}{path}"
        headers = kwargs.pop("headers", None) or self._headers()
        resp = requests.request(method, url, headers=headers, timeout=self._timeout, **kwargs)
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise
        if data.get("code") != 0:
            raise FeishuAPIError(data.get("code", -1), data.get("msg", ""), data)
        return data.get("data", {}) or {}

    # ---------- 多维表格：元信息 ----------

    def list_tables(self, app_token: str) -> List[Dict[str, Any]]:
        """列出一个多维表格下的所有数据表。"""
        items: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                "GET",
                f"/bitable/v1/apps/{app_token}/tables",
                params=params,
            )
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return items

    def list_fields(self, app_token: str, table_id: str) -> List[Dict[str, Any]]:
        """列出数据表所有字段元信息。"""
        items: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                "GET",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                params=params,
            )
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return items

    # ---------- 多维表格：记录读写 ----------

    def list_records(self, app_token: str, table_id: str) -> List[Dict[str, Any]]:
        """分页拉取一个数据表的所有记录。"""
        items: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                "GET",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                params=params,
            )
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return items

    def batch_update_records(
        self,
        app_token: str,
        table_id: str,
        updates: List[Tuple[str, Dict[str, Any]]],
    ) -> int:
        """批量更新记录。updates 每项为 (record_id, {field: value})。

        每批最多 500 条（飞书限制），自动分批。
        返回实际发送的更新数量。
        """
        if not updates:
            return 0
        total = 0
        for batch in _chunked(updates, 500):
            records = [
                {"record_id": rid, "fields": fields} for rid, fields in batch
            ]
            self._request(
                "POST",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update",
                json={"records": records},
            )
            total += len(records)
        return total


def _chunked(seq: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ---------- URL 解析工具 ----------


class BitableURLError(ValueError):
    """URL 解析失败时抛出，附带用户可读的说明。"""


def parse_bitable_url(url: str) -> Tuple[str, Optional[str]]:
    """从多维表格 URL 中解析 app_token 与 table_id。

    支持形如：
      https://xxx.feishu.cn/base/<app_token>?table=<table_id>&view=...
      https://xxx.feishu.cn/base/<app_token>
    """
    from urllib.parse import urlparse, parse_qs

    raw = (url or "").strip()
    if not raw:
        raise BitableURLError("请粘贴多维表格 URL")

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    parts = [p for p in parsed.path.split("/") if p]

    # 明显不是飞书域名
    if host and not (host.endswith("feishu.cn") or host.endswith("larksuite.com")):
        raise BitableURLError(
            f"这不是飞书域名下的链接（host={host}）。请粘贴 feishu.cn 或 larksuite.com 的多维表格 URL。"
        )

    # wiki 包装：从 wiki 文档打开的 bitable，路径是 /wiki/<wiki_token>
    if "wiki" in parts:
        raise BitableURLError(
            "这是「飞书 wiki 链接」，不是多维表格的原始 URL。请在 wiki 里打开这张表 → "
            "点击右上角「…」→ 选择「在新窗口打开」或「独立页面打开」→ 再复制那个地址栏里的 URL（会含 /base/<app_token>）。"
        )

    # docs / sheets / mindnotes 等其他文档类型
    for other in ("docs", "docx", "sheets", "file", "mindnotes", "slides", "minutes"):
        if other in parts:
            raise BitableURLError(
                f"这似乎是飞书「{other}」文档链接，不是多维表格。请确保 URL 中包含 /base/<app_token>。"
            )

    app_token: Optional[str] = None
    if "base" in parts:
        idx = parts.index("base")
        if idx + 1 < len(parts):
            app_token = parts[idx + 1]
    if not app_token:
        raise BitableURLError(
            "URL 里没有找到 /base/<app_token> 段。请从飞书多维表格页面的地址栏直接复制 URL，"
            "标准格式：https://xxx.feishu.cn/base/<app_token>?table=<table_id>"
        )

    qs = parse_qs(parsed.query)
    table_id = (qs.get("table") or [None])[0]
    return app_token, table_id
