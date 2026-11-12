"""OdooAdapter — read-only pull of products, product lines and suppliers
from an Odoo instance over JSON-RPC.

Odoo is the realistic "we already have an ERP" story for a mid-size Saudi
manufacturer, and unlike SAP/Oracle it is self-hostable, which is why the
takeoff prompt (section 8) asks for this one as a real implementation
rather than a stub: a demo Odoo can be started next to the rest of the
stack and the integration shown live.

**Read-only by construction.** Every call this adapter makes is
``search_read``. There is no write path, no ``create``/``write``/``unlink``
anywhere in this file, and adding one would be a deliberate change, not an
accident — Xposure has no business mutating a customer's ERP.

Protocol notes that actually matter when writing this correctly (Odoo's
JSON-RPC has two shapes that trip people up):

  - Everything is a POST to ``{base_url}/jsonrpc`` with
    ``{"jsonrpc": "2.0", "method": "call", "id": <n>, "params": {...}}``.
    The outer ``"method"`` is ALWAYS the literal string ``"call"``; the
    thing you actually want is ``params.method``. Getting these two
    confused is the single most common Odoo JSON-RPC mistake.
  - Authentication is its own call (``service: "common"``, ``method:
    "login"``) that returns a numeric ``uid``. That uid is then passed as
    a positional argument to every subsequent ``service: "object"`` call,
    together with the password again — there is no session cookie or
    bearer token in this flow.
  - **Odoo reports application errors with HTTP 200 and an ``"error"``
    key in the body.** A bare ``raise_for_status()`` therefore passes
    cleanly on a failed login, a missing model, or an access-rights
    refusal. ``_call()`` checks the body explicitly; without that check
    the adapter would return an empty fragment on an auth failure, which
    is exactly the silent-fallback failure docs/PLAN.md section 7
    forbids.

Verification status: the request shaping, the error handling and the
record-to-node mapping are covered by unit tests against a mocked HTTP
transport (tests/unit/test_org_adapters.py). This has NOT been run against
a live Odoo — stated plainly rather than implied, in the same spirit as
llm.py's note about classify_change().

One modelling decision worth knowing about: ``product.category`` has no
counterpart in the fixed org-node vocabulary (product, process, policy,
control_mapping, evidence, owner, supplier, site — see base.py). Categories
are still worth importing, because a product LINE is the level a compliance
team actually maps controls to ("all UAV avionics"), not the individual
SKU. They are therefore stored as ``product`` nodes flagged
``attrs["is_product_line"] = True``, with each concrete product linked to
its line by a ``belongs_to_line`` edge. The alternative — adding a
``product_line`` node type — was rejected because the node vocabulary is a
cross-milestone contract (M5 weights by type, M6 routes actions by type),
so widening it for one adapter's convenience is not a local decision.
"""

from typing import Any, ClassVar

import httpx

from .base import OrgDataAdapter, OrgEdgeSpec, OrgGraphFragment, OrgNodeSpec

# Fields requested per model. Listed explicitly rather than pulling whole
# records: Odoo returns every field when `fields` is omitted, which on a
# real product.template means ~200 columns per row of which we use four.
PRODUCT_FIELDS = ["id", "name", "default_code", "categ_id", "type", "active"]
CATEGORY_FIELDS = ["id", "name", "parent_id", "complete_name"]
PARTNER_FIELDS = ["id", "name", "ref", "country_id", "supplier_rank", "email"]
SUPPLIERINFO_FIELDS = ["id", "partner_id", "product_tmpl_id"]


class OdooError(RuntimeError):
    """An error Odoo reported in a 200-OK JSON-RPC body."""


class OdooAdapter(OrgDataAdapter):
    """Pulls ``product.template``, ``product.category``, ``res.partner``
    (suppliers) and ``product.supplierinfo`` into org nodes/edges.

    Args:
        base_url: e.g. "http://127.0.0.1:8069" (no trailing /jsonrpc).
        db: Odoo database name.
        username: login (usually an email).
        password: password or API key.
        limit: per-model record cap. Defaults to 500 — a demo-scale guard,
            not a real pagination strategy; see the TODO in fetch().
        include_supplier_links: pull ``product.supplierinfo`` to connect
            suppliers to the products they supply. Default True. This is
            the one model here the takeoff prompt does not name, and it is
            included deliberately: without it every supplier arrives as an
            isolated node with no edges, which app.impact's graph traversal
            can never reach from a control mapping — i.e. importing
            suppliers at all would be pointless.
        timeout: seconds, per request.
    """

    name: ClassVar[str] = "odoo"

    def __init__(
        self,
        base_url: str,
        db: str,
        username: str,
        password: str,
        *,
        limit: int = 500,
        include_supplier_links: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self.limit = limit
        self.include_supplier_links = include_supplier_links
        self.timeout = timeout
        self._uid: int | None = None
        self._request_id = 0

    # ── JSON-RPC plumbing ─────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def build_payload(self, service: str, method: str, args: list[Any]) -> dict[str, Any]:
        """The JSON-RPC envelope. Separated from _call() so a test can
        assert on the exact request shape without mocking a transport."""
        return {
            "jsonrpc": "2.0",
            "method": "call",  # always the literal "call" — see module docstring
            "id": self._next_id(),
            "params": {"service": service, "method": method, "args": args},
        }

    def _call(self, client: httpx.Client, service: str, method: str, args: list[Any]) -> Any:
        response = client.post(f"{self.base_url}/jsonrpc", json=self.build_payload(service, method, args))
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            error = body["error"] or {}
            data = error.get("data") or {}
            raise OdooError(
                f"Odoo rejected {service}.{method}: "
                f"{data.get('message') or error.get('message') or error!r}"
            )
        return body.get("result")

    def _login(self, client: httpx.Client) -> int:
        """Odoo returns ``False`` (not an error object) for bad credentials,
        so a truthiness check is the only way to catch it."""
        uid = self._call(client, "common", "login", [self.db, self.username, self.password])
        if not isinstance(uid, int) or uid is False:
            raise OdooError(
                f"Odoo login failed for user {self.username!r} on database {self.db!r} "
                f"(the server returned {uid!r} rather than a uid). Check the database name: "
                f"a wrong db name fails exactly like a wrong password here."
            )
        self._uid = uid
        return uid

    def search_read(
        self,
        client: httpx.Client,
        model: str,
        domain: list[Any],
        fields: list[str],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if self._uid is None:
            raise RuntimeError("search_read() called before _login(): call fetch() instead.")
        result = self._call(
            client, "object", "execute_kw",
            [
                self.db, self._uid, self.password,
                model, "search_read",
                [domain],
                {"fields": fields, "limit": limit if limit is not None else self.limit},
            ],
        )
        return result or []

    # ── mapping ───────────────────────────────────────────────────────────

    @staticmethod
    def _m2o(value: Any) -> tuple[int, str] | None:
        """Odoo serializes a many2one as ``[id, "display name"]`` — or as
        ``False`` when unset, which is why this cannot just index [0]."""
        if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
            return int(value[0]), str(value[1])
        return None

    @staticmethod
    def category_key(odoo_id: int) -> str:
        return f"odoo_category_{odoo_id}"

    @staticmethod
    def product_key(odoo_id: int) -> str:
        return f"odoo_product_{odoo_id}"

    @staticmethod
    def partner_key(odoo_id: int) -> str:
        return f"odoo_supplier_{odoo_id}"

    def to_fragment(
        self,
        categories: list[dict[str, Any]],
        products: list[dict[str, Any]],
        suppliers: list[dict[str, Any]],
        supplier_links: list[dict[str, Any]],
    ) -> OrgGraphFragment:
        """Pure record -> spec mapping, no I/O. Split out so the mapping is
        testable against literal Odoo response payloads."""
        nodes: list[OrgNodeSpec] = []
        edges: list[OrgEdgeSpec] = []
        known_categories: set[int] = set()
        known_products: set[int] = set()
        known_suppliers: set[int] = set()

        for category in categories:
            cid = int(category["id"])
            known_categories.add(cid)
            nodes.append(OrgNodeSpec(
                key=self.category_key(cid),
                type="product",
                name=str(category.get("complete_name") or category.get("name") or f"Category {cid}"),
                attrs={
                    "source": self.name,
                    "odoo_model": "product.category",
                    "odoo_id": cid,
                    "is_product_line": True,
                },
            ))

        # Parent/child category chain, only where both ends were pulled —
        # an out-of-limit parent must not become a dangling edge.
        for category in categories:
            parent = self._m2o(category.get("parent_id"))
            if parent and parent[0] in known_categories:
                edges.append(OrgEdgeSpec(
                    self.category_key(int(category["id"])),
                    self.category_key(parent[0]),
                    "belongs_to_line",
                ))

        for product in products:
            pid = int(product["id"])
            known_products.add(pid)
            attrs: dict[str, Any] = {
                "source": self.name,
                "odoo_model": "product.template",
                "odoo_id": pid,
                "is_product_line": False,
            }
            if product.get("default_code"):
                attrs["sku"] = str(product["default_code"])
            if product.get("type"):
                attrs["odoo_type"] = str(product["type"])
            nodes.append(OrgNodeSpec(
                key=self.product_key(pid),
                type="product",
                name=str(product.get("name") or f"Product {pid}"),
                attrs=attrs,
            ))
            category = self._m2o(product.get("categ_id"))
            if category and category[0] in known_categories:
                edges.append(OrgEdgeSpec(self.product_key(pid), self.category_key(category[0]), "belongs_to_line"))

        for partner in suppliers:
            sid = int(partner["id"])
            known_suppliers.add(sid)
            attrs = {"source": self.name, "odoo_model": "res.partner", "odoo_id": sid}
            if partner.get("ref"):
                attrs["ref"] = str(partner["ref"])
            if partner.get("email"):
                attrs["email"] = str(partner["email"])
            country = self._m2o(partner.get("country_id"))
            if country:
                attrs["country"] = country[1]
            if partner.get("supplier_rank") is not None:
                attrs["supplier_rank"] = partner["supplier_rank"]
            nodes.append(OrgNodeSpec(
                key=self.partner_key(sid), type="supplier",
                name=str(partner.get("name") or f"Partner {sid}"), attrs=attrs,
            ))

        seen_links: set[tuple[int, int]] = set()
        for link in supplier_links:
            partner = self._m2o(link.get("partner_id"))
            template = self._m2o(link.get("product_tmpl_id"))
            if not partner or not template:
                continue
            if partner[0] not in known_suppliers or template[0] not in known_products:
                continue  # one end outside the pulled window; skip rather than dangle
            if (partner[0], template[0]) in seen_links:
                continue  # supplierinfo allows several price lines per supplier/product pair
            seen_links.add((partner[0], template[0]))
            edges.append(OrgEdgeSpec(self.partner_key(partner[0]), self.product_key(template[0]), "supplies"))

        return OrgGraphFragment(nodes=nodes, edges=edges)

    # ── fetch ─────────────────────────────────────────────────────────────

    def fetch(self) -> OrgGraphFragment:
        # TODO(pagination): `limit` is a flat cap, not pagination. A real
        # tenant with >500 product templates would be silently truncated,
        # which is precisely the kind of quiet data loss this project's
        # guardrails are against — but Odoo's offset-based paging needs a
        # live instance to verify against (an untested paging loop that
        # double-counts or drops a page is worse than an honest cap), so
        # it waits for the demo Odoo profile.
        with httpx.Client(timeout=self.timeout) as client:
            self._login(client)
            categories = self.search_read(client, "product.category", [], CATEGORY_FIELDS)
            products = self.search_read(
                client, "product.template", [["active", "=", True]], PRODUCT_FIELDS,
            )
            suppliers = self.search_read(
                client, "res.partner", [["supplier_rank", ">", 0]], PARTNER_FIELDS,
            )
            supplier_links: list[dict[str, Any]] = []
            if self.include_supplier_links:
                supplier_links = self.search_read(
                    client, "product.supplierinfo", [], SUPPLIERINFO_FIELDS,
                )
        return self.to_fragment(categories, products, suppliers, supplier_links)
