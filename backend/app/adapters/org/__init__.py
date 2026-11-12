"""Org-data adapters: external systems -> Xposure's organization graph.

  - base.py           — OrgDataAdapter ABC + the node/relation vocabulary.
  - csv_assessment.py — CsvAssessmentSheetAdapter (NCA ECC self-assessment
                        spreadsheet). Working.
  - odoo.py           — OdooAdapter (read-only JSON-RPC). Working; request
                        shaping verified against a mocked transport, not a
                        live Odoo.
  - sap.py            — SapODataAdapter. Documented stub; a real public
                        sandbox exists, see docs/ERP_INTEGRATION_GUIDE.md §1.
  - oracle.py         — OracleFusionAdapter. Documented stub; no self-serve
                        access to Oracle Fusion exists at all, see §2.
"""

from .base import (
    ORG_NODE_TYPES,
    ORG_RELATIONS,
    OrgDataAdapter,
    OrgEdgeSpec,
    OrgGraphFragment,
    OrgNodeSpec,
    validate_fragment,
)
from .csv_assessment import CsvAssessmentSheetAdapter
from .odoo import OdooAdapter
from .oracle import OracleFusionAdapter
from .sap import SapODataAdapter

__all__ = [
    "ORG_NODE_TYPES",
    "ORG_RELATIONS",
    "CsvAssessmentSheetAdapter",
    "OdooAdapter",
    "OracleFusionAdapter",
    "OrgDataAdapter",
    "OrgEdgeSpec",
    "OrgGraphFragment",
    "OrgNodeSpec",
    "SapODataAdapter",
    "validate_fragment",
]
