"""SapODataAdapter — **stub, but a testable one.**

Status, stated precisely rather than as a generic "TODO: implement":
everything needed to make this real exists and is free to obtain today.
The blocker is not access, it is that nobody on the team has yet gone
through the ten-minute signup, and writing the OData response mapping
against a payload shape nobody has actually looked at would be guesswork
dressed as code. Full research and the exact steps are in
``docs/ERP_INTEGRATION_GUIDE.md`` section 1 (every claim there was
verified by live fetch on 2026-09-15, not recalled).

What is verified to exist:

  - **A free, self-serve SAP Universal ID** (accounts.sap.com), personal
    email, no company affiliation and no credit card.
  - **A genuinely public read-only sandbox** at ``sandbox.api.sap.com``,
    reachable with an API key that SAP Business Accelerator Hub
    (api.sap.com, formerly "SAP API Business Hub") generates for your
    account in its "Try Out" UI. The **Business Partner (A2X)** service
    (``API_BUSINESS_PARTNER``, entity set ``A_BusinessPartner``) is
    explicitly callable this way **without owning an S/4HANA system at
    all** — which is what makes this adapter's target real rather than
    hypothetical.
  - Request shape against the sandbox is plain HTTPS + two headers::

        GET https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner?$top=50
        APIKey: <key from the Try Out UI>
        Accept: application/json

    (The exact service path prefix is the one detail to copy out of the
    Try Out UI rather than trust from a docstring — the UI shows the
    literal URL it is calling. The guide says the same, for the same
    reason.)

Deliberately NOT guessed here, and why each matters:

  - **The OData version.** S/4HANA Cloud ships both v2 and v4 services and
    is mid-migration. v2 wraps collections in ``{"d": {"results": [...]}}``
    while v4 uses ``{"value": [...]}``; paging is ``__next`` vs
    ``@odata.nextLink``. A response parser written for the wrong one fails
    on the first real call, so the mapping waits for one real response.
  - **Which entity is a "supplier".** A2X models suppliers as business
    partners carrying a Supplier role (``A_SupplierCompany`` /
    ``BusinessPartnerRole``), not as a separate entity type. Picking the
    wrong filter yields a plausible-looking node list made of customers.
  - **Products.** ``API_PRODUCT_SRV`` (``A_Product``) is the natural
    counterpart to Odoo's ``product.template``, but it is a different
    service from Business Partner with its own sandbox path.

Against a real customer tenant rather than the sandbox, the differences
are: the host becomes ``https://<host>/sap/opu/odata/sap/<service>``, and
auth becomes OAuth 2.0 (or basic auth for a technical user) instead of the
``APIKey`` header. Nothing else in the shape changes.

Next concrete step for whoever picks this up: get the key (guide §1.2
steps 1-3), call the sandbox URL above with curl, paste one real response
into ``tests/fixtures/``, and write ``to_fragment()`` against it — the
same order ``odoo.py`` was written in.
"""

from typing import ClassVar

from .base import OrgDataAdapter, OrgGraphFragment

SANDBOX_BASE_URL = "https://sandbox.api.sap.com"
BUSINESS_PARTNER_SERVICE = "API_BUSINESS_PARTNER"
BUSINESS_PARTNER_ENTITY_SET = "A_BusinessPartner"
PRODUCT_SERVICE = "API_PRODUCT_SRV"
PRODUCT_ENTITY_SET = "A_Product"


class SapODataAdapter(OrgDataAdapter):
    """SAP S/4HANA business partners and products -> supplier/product nodes.

    Not implemented. ``fetch()`` raises rather than returning an empty
    fragment, so a caller that wires this adapter up by mistake fails
    immediately and visibly (docs/PLAN.md section 7: no silent fallbacks) —
    an empty graph would otherwise look exactly like "this tenant has no
    suppliers".
    """

    name: ClassVar[str] = "sap_odata"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = SANDBOX_BASE_URL,
        service: str = BUSINESS_PARTNER_SERVICE,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.service = service

    def fetch(self) -> OrgGraphFragment:
        raise NotImplementedError(
            "SapODataAdapter is a documented stub, not a silent no-op.\n"
            "Unlike OracleFusionAdapter, this one IS unblocked: SAP's public sandbox "
            f"({SANDBOX_BASE_URL}) serves {BUSINESS_PARTNER_SERVICE}/{BUSINESS_PARTNER_ENTITY_SET} "
            "read-only to any free SAP Universal ID, no S/4HANA system required.\n"
            "To implement: docs/ERP_INTEGRATION_GUIDE.md section 1.2: get an API key from "
            "api.sap.com's Try Out UI, capture one real response, then write the OData "
            "response mapping against it (the v2-vs-v4 envelope differs and must not be guessed)."
        )
