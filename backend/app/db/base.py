from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. Table models land here starting M2
    (regulation_version, clause, change, org_node, ...) — see docs/PLAN.md."""
