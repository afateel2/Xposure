"""Single source of truth for known regulators/regulations, mirroring the
role ComplyX's corpus_registry.py plays there (docs/PLAN.md section 1) —
except here it seeds Postgres rows rather than just tagging Qdrant payloads,
since regulator/regulation are now real tables. NCA/ECC was the first
entry; add entries here as new regulators come into scope.

SASO/ROHS (see app/ingest_articles.py) is a real second
regulator, directly relevant to the demo company's own products (Eastern
Industrial Company makes electrical/electronic industrial equipment, and
RoHS restricts hazardous substances in exactly that product category).
Source verified against saso.gov.sa directly, not assumed, the same
discipline ECC-1:2018's sourcing used (docs/PLAN.md section 1).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RegulatorInfo:
    code: str
    name_en: str
    name_ar: str
    weight: float = 1.0  # M5 priority formula input


@dataclass(frozen=True)
class RegulationInfo:
    regulator_code: str
    code: str
    title_en: str
    title_ar: str


REGULATORS: list[RegulatorInfo] = [
    RegulatorInfo("nca", "National Cybersecurity Authority", "الهيئة الوطنية للأمن السيبراني"),
    RegulatorInfo("saso", "Saudi Standards, Metrology and Quality Organization", "الهيئة السعودية للمواصفات والمقاييس والجودة"),
]

REGULATIONS: list[RegulationInfo] = [
    RegulationInfo("nca", "ecc", "Essential Cybersecurity Controls", "الضوابط الأساسية للأمن السيبراني"),
    RegulationInfo(
        "saso", "rohs",
        "Technical Regulation for Restriction of Hazardous Substances in Electrical and Electronic Equipment",
        "اللائحة الفنية لتقييد المواد الخطرة في الأجهزة والمعدات الكهربائية والإلكترونية",
    ),
]

REGULATORS_BY_CODE = {r.code: r for r in REGULATORS}
REGULATIONS_BY_CODE = {(r.regulator_code, r.code): r for r in REGULATIONS}
