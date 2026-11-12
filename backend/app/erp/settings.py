"""ERP settings, read from the same .env file as app.config.Settings.

Kept in this package (instead of app/config.py) so the ERP integration is
one self-contained unit with no edit to a shared file. The password is a
pydantic SecretStr so it can never end up in a repr, a log line or an
error message by accident."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/erp/settings.py -> repo root, same file app/config.py reads.
_ENV_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".env"

PROJECT_NAME = "Compliance Actions"


class ErpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Empty odoo_url or odoo_password means "ERP not configured": the API
    # says so honestly instead of pretending.
    odoo_url: str = ""
    # What a browser should open (deep links). Defaults to odoo_url.
    odoo_public_url: str = ""
    odoo_db: str = "xposure_erp"
    odoo_user: str = "admin"
    odoo_password: SecretStr = SecretStr("")
    odoo_project_name: str = PROJECT_NAME
    # Base URL of the Xposure web app, used for the deep link inside a task.
    xposure_public_url: str = "http://127.0.0.1:3010"

    @property
    def configured(self) -> bool:
        return bool(self.odoo_url.strip() and self.odoo_password.get_secret_value())

    @property
    def public_url(self) -> str:
        return (self.odoo_public_url or self.odoo_url).rstrip("/")


def get_erp_settings() -> ErpSettings:
    """Fresh on every call (cheap): tests and operators can change the
    environment without a process-wide cache going stale."""
    return ErpSettings()
