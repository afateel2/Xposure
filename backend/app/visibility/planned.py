"""
Regulators on the roadmap that are not monitored yet. They are listed so the
UI can show them honestly as "planned". They are never counted as monitored,
never given a scan time and never given a status other than `planned`.

An entry disappears from this list automatically once a real regulator with the
same code exists in the database (see routes/overview.py), so adding a
regulator to app/regulation_registry.py never produces a duplicate tile.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedRegulator:
    code: str
    name_en: str
    name_ar: str
    scope_en: str
    scope_ar: str


PLANNED_REGULATORS: tuple[PlannedRegulator, ...] = (
    PlannedRegulator(
        "saso", "Saudi Standards, Metrology and Quality Organization", "الهيئة السعودية للمواصفات والمقاييس والجودة",
        "Technical regulations and product standards", "اللوائح الفنية ومعايير المنتجات",
    ),
    PlannedRegulator(
        "sfda", "Saudi Food and Drug Authority", "الهيئة العامة للغذاء والدواء",
        "Food, drug and medical device regulation", "تنظيم الغذاء والدواء والأجهزة الطبية",
    ),
    PlannedRegulator(
        "ncec", "National Center for Environmental Compliance", "المركز الوطني للرقابة على الالتزام البيئي",
        "Environmental compliance", "الالتزام البيئي",
    ),
    PlannedRegulator(
        "gami", "General Authority for Military Industries", "الهيئة العامة للصناعات العسكرية",
        "Defense manufacturing licensing and requirements", "تراخيص ومتطلبات الصناعات العسكرية",
    ),
)
