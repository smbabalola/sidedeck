import os

import pytest
from alembic import command
from alembic.config import Config

from sidedeck.infrastructure.database import create_database


POSTGRES_URL = os.environ.get("SIDEDECK_TEST_POSTGRES_URL")


@pytest.mark.skipif(POSTGRES_URL is None, reason="disposable PostgreSQL URL not provisioned")
def test_postgres_alembic_upgrade_downgrade() -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", POSTGRES_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    create_database(POSTGRES_URL).dispose()
