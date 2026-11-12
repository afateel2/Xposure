"""Minimal Odoo external-API client over JSON-RPC (`/jsonrpc`).

Protocol (Odoo 17):
  - every call is POST {base}/jsonrpc with
    {"jsonrpc": "2.0", "method": "call", "id": n, "params": {service, method, args}};
  - `common.version` needs no login; `common.authenticate(db, login,
    password, {})` returns the numeric uid (or false);
  - `object.execute_kw(db, uid, password, model, method, args, kwargs)` runs
    an ORM method.
  - Odoo reports application errors with HTTP 200 and an "error" key, so
    the body is always checked, never only the HTTP status.

Honest failure handling: every failure becomes an ErpError with a stable
`kind` and a bilingual message. Nothing here returns a fake value on
failure. The password is only ever placed in the request body; it is never
logged, never included in an ErpError message and never stored anywhere
except the SecretStr in the settings object.

Tests inject a fake transport through the module-level TRANSPORT hook (an
httpx.MockTransport that behaves like Odoo), so no network is needed.
"""

import itertools
import logging
from typing import Any

import httpx

from .settings import ErpSettings

log = logging.getLogger("xposure.erp")

# Test hook: an httpx.BaseTransport used instead of the real network.
TRANSPORT: httpx.BaseTransport | None = None

CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 15.0

_MAX_ERROR_CHARS = 300


class ErpError(Exception):
    """kind: not_configured | unreachable | timeout | auth | api | not_found"""

    def __init__(self, kind: str, message_en: str, message_ar: str, detail: str = ""):
        super().__init__(message_en)
        self.kind = kind
        self.message_en = message_en
        self.message_ar = message_ar
        self.detail = detail

    @property
    def combined(self) -> str:
        """One string for HTTP `detail` (the frontend shows detail as text)."""
        return f"{self.message_en} | {self.message_ar}"


def not_configured_error() -> ErpError:
    return ErpError(
        "not_configured",
        "The ERP (Odoo) is not configured. Set ODOO_URL and ODOO_PASSWORD in .env and start Odoo "
        "with: docker compose --profile odoo up -d",
        "نظام تخطيط الموارد (Odoo) غير مهيأ. حدد ODOO_URL وODOO_PASSWORD في ملف .env وشغّل Odoo "
        "عبر الأمر: docker compose --profile odoo up -d",
    )


class OdooClient:
    def __init__(
        self, settings: ErpSettings, *, connect_timeout: float = CONNECT_TIMEOUT, read_timeout: float = READ_TIMEOUT
    ):
        if not settings.configured:
            raise not_configured_error()
        self._base = settings.odoo_url.rstrip("/")
        self._db = settings.odoo_db
        self._user = settings.odoo_user
        self._password = settings.odoo_password.get_secret_value()
        self._uid: int | None = None
        self._ids = itertools.count(1)
        self._http = httpx.Client(
            transport=TRANSPORT,
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
        )

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OdooClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------
    def _rpc(self, service: str, method: str, args: list[Any]) -> Any:
        body = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": next(self._ids),
            "params": {"service": service, "method": method, "args": args},
        }
        try:
            response = self._http.post(f"{self._base}/jsonrpc", json=body)
        except httpx.TimeoutException as exc:
            log.warning("odoo %s.%s timed out", service, method)
            raise ErpError(
                "timeout",
                "The ERP (Odoo) did not answer in time. Check that the Odoo container is healthy and try again.",
                "لم يستجب نظام Odoo في الوقت المحدد. تأكد من سلامة حاوية Odoo ثم أعد المحاولة.",
                detail=type(exc).__name__,
            ) from exc
        except httpx.HTTPError as exc:
            log.warning("odoo %s.%s unreachable: %s", service, method, type(exc).__name__)
            raise ErpError(
                "unreachable",
                "The ERP (Odoo) is not reachable. Start it with: docker compose --profile odoo up -d",
                "تعذر الوصول إلى نظام Odoo. شغّله عبر الأمر: docker compose --profile odoo up -d",
                detail=type(exc).__name__,
            ) from exc

        if response.status_code >= 500:
            raise ErpError(
                "api",
                f"The ERP (Odoo) returned a server error (HTTP {response.status_code}).",
                f"أعاد نظام Odoo خطأ في الخادم (HTTP {response.status_code}).",
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ErpError(
                "api",
                "The ERP (Odoo) returned a response that is not JSON. Check ODOO_URL.",
                "أعاد نظام Odoo استجابة ليست بصيغة JSON. تحقق من ODOO_URL.",
            ) from exc

        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            message = ""
            if isinstance(err, dict):
                inner = err.get("data") if isinstance(err.get("data"), dict) else {}
                message = str(inner.get("message") or err.get("message") or "")
            message = message.strip().splitlines()[0][:_MAX_ERROR_CHARS] if message.strip() else "unknown error"
            raise ErpError(
                "api",
                f"The ERP (Odoo) refused the request: {message}",
                f"رفض نظام Odoo الطلب: {message}",
                detail=message,
            )
        if not isinstance(data, dict) or "result" not in data:
            raise ErpError(
                "api",
                "The ERP (Odoo) sent an unexpected response.",
                "أرسل نظام Odoo استجابة غير متوقعة.",
            )
        return data["result"]

    # -- public API --------------------------------------------------------
    def version(self) -> dict[str, Any]:
        """common.version: works without credentials, so it tells 'server
        is up' apart from 'credentials are wrong'."""
        result = self._rpc("common", "version", [])
        return result if isinstance(result, dict) else {}

    def authenticate(self) -> int:
        if self._uid is not None:
            return self._uid
        uid = self._rpc("common", "authenticate", [self._db, self._user, self._password, {}])
        if not uid:
            raise ErpError(
                "auth",
                f"The ERP (Odoo) rejected the login for user {self._user!r} on database {self._db!r}. "
                "Check ODOO_USER, ODOO_PASSWORD and ODOO_DB, and that the database was initialised.",
                f"رفض نظام Odoo تسجيل الدخول للمستخدم {self._user!r} على قاعدة البيانات {self._db!r}. "
                "تحقق من ODOO_USER وODOO_PASSWORD وODOO_DB ومن تهيئة قاعدة البيانات.",
            )
        self._uid = int(uid)
        return self._uid

    def execute_kw(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        uid = self.authenticate()
        return self._rpc(
            "object", "execute_kw", [self._db, uid, self._password, model, method, args, kwargs or {}]
        )

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        limit: int | None = None,
        order: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"fields": fields}
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        if context:
            kwargs["context"] = context
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def create(self, model: str, values: dict[str, Any]) -> int:
        return int(self.execute_kw(model, "create", [values]))

    def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict[str, Any]]:
        return self.execute_kw(model, "read", [ids], {"fields": fields})

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        return bool(self.execute_kw(model, "write", [ids, values]))
