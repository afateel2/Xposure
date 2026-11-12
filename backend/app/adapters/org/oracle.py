"""OracleFusionAdapter — **stub, and blocked, which is a different thing
from SapODataAdapter's stub.**

This one is not waiting on someone to spend ten minutes signing up. It is
waiting on access that does not exist for a team like ours. Verified by
live research on 2026-09-15 (docs/ERP_INTEGRATION_GUIDE.md section 2 —
including a first-pass assumption that Oracle's free tier would cover
Fusion, which turned out to be wrong when actually checked):

  - **Oracle Cloud Free Tier is infrastructure only.** OCI's $300 credit
    and "Always Free" resources cover compute, Autonomous Database,
    storage and networking. Fusion *Applications* (ERP/HCM/SCM/CX) are a
    different product line and are not included at any tier. This is the
    trap: "Oracle has a free tier" is true and irrelevant here.
  - **There is no public sandbox.** Nothing equivalent to SAP's
    ``sandbox.api.sap.com`` exists for Fusion. The base URL contains a
    per-tenant hostname, so there is no shared endpoint to call even
    anonymously.
  - **Fusion Cloud ERP is paid SaaS with no free trial found** (third-party
    estimates put core financials around $175/user/month — directional,
    not an Oracle quote).
  - **Oracle PartnerNetwork, the usual route to a demo tenant, excludes
    us by its own published rules**: a member must be an established
    company at least 6 months old with at least 5 employees.
  - The nearest thing to a free look is a sales-mediated guided demo
    (oracle.com/applications/demo/) — form-fill-and-wait, with no
    indication it grants standalone API credentials.

So this adapter stays a documented stub *on purpose*, not by neglect.
Writing the request/response code against docs alone would encode
assumptions nobody can falsify until a real tenant appears, which is worse
than an honest stub: it would look implemented in a demo and fail on first
contact with reality. That is the same reasoning as llm.py's explicit
"this has never been called against a real model" note, applied to an
integration.

What IS public and does not need an account — Oracle's REST API docs — so
the shape below is documented fact, usable the day a tenant exists:

  - **Base URL**::

        https://<tenant>.fa.<datacenter>.oraclecloud.com/fscmRestApi/resources/<version>/<resource>

    e.g. ``https://acme.fa.us2.oraclecloud.com/fscmRestApi/resources/11.13.18.05/suppliers``.
    ``<tenant>`` and ``<datacenter>`` only exist once an instance is
    provisioned — there is no filling these in from documentation.
  - **Auth**: Basic over TLS (dev only, and broken by MFA) or OAuth 2.0
    against the instance's IAM identity domain (Oracle's own
    recommendation; client credentials for server-to-server).
  - **Discovery**: every resource supports a ``/describe`` suffix, which is
    how you would learn the real field names of ``suppliers`` /
    ``itemsV2`` without guessing them here.
  - Relevant resources for this adapter's purpose: ``suppliers``
    (Procurement) -> ``supplier`` nodes, ``itemsV2`` (Product Management)
    -> ``product`` nodes.

Reference docs: ``docs.oracle.com/en/cloud/saas/applications-common/25d/farca/``
and ``docs.oracle.com/en/cloud/saas/supply-chain-management/22d/fasrp/Quick_Start.html``.
"""

from typing import ClassVar

from .base import OrgDataAdapter, OrgGraphFragment

# Format string, not a usable URL — both placeholders are per-tenant.
BASE_URL_TEMPLATE = "https://{tenant}.fa.{datacenter}.oraclecloud.com/fscmRestApi/resources/{version}"
DEFAULT_RESOURCE_VERSION = "11.13.18.05"
SUPPLIER_RESOURCE = "suppliers"
ITEM_RESOURCE = "itemsV2"


class OracleFusionAdapter(OrgDataAdapter):
    """Oracle Fusion Cloud ERP suppliers and items -> supplier/product nodes.

    Not implemented, and blocked on access rather than on effort — see the
    module docstring. ``fetch()`` raises rather than returning an empty
    fragment (docs/PLAN.md section 7: no silent fallbacks).
    """

    name: ClassVar[str] = "oracle_fusion"

    def __init__(
        self,
        tenant: str | None = None,
        datacenter: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        resource_version: str = DEFAULT_RESOURCE_VERSION,
    ) -> None:
        self.tenant = tenant
        self.datacenter = datacenter
        self.username = username
        self.password = password
        self.resource_version = resource_version

    def base_url(self) -> str:
        """The tenant-specific REST root. Raises if either per-tenant
        placeholder is unset — there is no default to fall back to, and a
        half-filled URL would produce a DNS error three layers deeper."""
        if not self.tenant or not self.datacenter:
            raise ValueError(
                "OracleFusionAdapter needs both a tenant and a datacenter: Fusion has no shared "
                f"host. Pattern: {BASE_URL_TEMPLATE}"
            )
        return BASE_URL_TEMPLATE.format(
            tenant=self.tenant, datacenter=self.datacenter, version=self.resource_version
        )

    def fetch(self) -> OrgGraphFragment:
        raise NotImplementedError(
            "OracleFusionAdapter is a documented stub, and stays one until the team has a real "
            "Fusion tenant.\n"
            "This is not the same situation as SapODataAdapter: Oracle has no public sandbox, "
            "its free tier is OCI infrastructure only (Fusion Applications are excluded at every "
            "tier), Fusion ERP is paid SaaS with no free trial, and Oracle PartnerNetwork "
            "excludes companies under 6 months old or under 5 employees.\n"
            "See docs/ERP_INTEGRATION_GUIDE.md section 2 for the full picture and for the public "
            "REST shape (base URL pattern, OAuth2/Basic auth, /describe) to build against once "
            "access exists."
        )
