import pytest
import os
from app.core.config import settings

# Force test environment so tests don't inadvertently exhaust live external LLM quotas
settings.ENVIRONMENT = "test"
os.environ["ENVIRONMENT"] = "test"

from app.core.database import engine


@pytest.fixture(autouse=True)
async def cleanup_db_engine():
    yield
    await engine.dispose()

