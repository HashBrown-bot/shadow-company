from sqlalchemy import create_engine, text

from services.api.settings import database_url

SCHEMA_REVISION = "0007_e9"


def make_engine(url=None):
    return create_engine(url or database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3})


def check_database(engine):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != SCHEMA_REVISION:
            raise RuntimeError("数据库迁移版本不匹配")
    return revision
