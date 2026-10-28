import os

DEFAULT_DATABASE_URL = "postgresql+psycopg://sim@127.0.0.1:55432/simulation"


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL 必须使用 postgresql+psycopg 驱动")
    return url
