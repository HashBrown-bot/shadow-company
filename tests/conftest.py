import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from packages.transport.access import bootstrap, client_headers
from services.api.settings import DEFAULT_DATABASE_URL

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "environments/refund_approval/example.v0.2.yaml"


@pytest.fixture
def config_data():
    return yaml.safe_load(EXAMPLE_PATH.read_text())


@contextmanager
def temporary_database():
    base = make_url(os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL))
    name = "sim_test_" + uuid4().hex
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        url = base.set(database=name)
        engine = create_engine(url)
        alembic = Config("alembic.ini")
        alembic.attributes["database_url"] = url
        yield engine, alembic
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture(scope="session")
def database():
    # No skip and no SQLite fallback. An unavailable PostgreSQL is an actual failure.
    with temporary_database() as (engine, alembic):
        command.upgrade(alembic, "head")
        yield engine


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient

    from services.api.main import create_app

    with TestClient(create_app(database), headers=client_headers()) as client:
        yield client


@pytest.fixture(scope="session", autouse=True)
def example_environment(tmp_path_factory):
    from packages.transport.security import provision

    path = tmp_path_factory.mktemp("example-credentials") / "generated.json"
    provision(path)
    registry, token_file = bootstrap(path.parent / "access")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SIM_ACCESS_REGISTRY", registry)
        patch.setenv("SIM_TOKEN_FILE", token_file)
        patch.setenv("EXAMPLE_CREDENTIAL_FILE", str(path))
        patch.setenv("EXAMPLE_TEST_MODE", "1")
        yield


@pytest.fixture(scope="session")
def live_stack(database, tmp_path_factory, example_environment):
    """Real HTTP and separate OS processes, all against the disposable PostgreSQL database."""
    import socket
    import subprocess
    import sys
    import time

    import httpx

    for port in (8000, 8001, 8002, 8003):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))

    class RedactedEnvironment(dict):
        def __repr__(self):
            return "<process environment redacted>"

    env = RedactedEnvironment(os.environ.copy())
    env["DATABASE_URL"] = database.url.render_as_string(hide_password=False)
    from packages.transport.security import service_credentials

    credentials = {
        name: str(service_credentials(env["EXAMPLE_CREDENTIAL_FILE"], name))
        for name in ("refund-put", "payment-provider", "platform")
    }
    logs = tmp_path_factory.mktemp("e3-service-logs")
    children = []
    handles = []
    try:
        with httpx.Client(trust_env=False, timeout=3, headers=client_headers()) as http:
            for name, port, module, extra in [
                ("api", 8000, "services.api.main:app", []),
                ("provider", 8002, "main:app", ["--app-dir", "examples/payment-provider"]),
                ("put", 8001, "main:app", ["--app-dir", "examples/refund-put"]),
                ("credit", 8003, "main:app", ["--app-dir", "examples/credit-note-put"]),
            ]:
                handle = (logs / f"{name}.txt").open("w")
                handles.append(handle)
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        module,
                        *extra,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    env=env
                    | {
                        "EXAMPLE_CREDENTIAL_FILE": credentials[
                            {
                                "api": "platform",
                                "put": "refund-put",
                                "provider": "payment-provider",
                                "credit": "refund-put",
                            }[name]
                        ]
                    },
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
                children.append(child)
                deadline = time.monotonic() + 15
                while True:
                    if child.poll() is not None:
                        raise RuntimeError(f"{name} failed: {(logs / f'{name}.txt').read_text()}")
                    try:
                        if (
                            http.get(
                                f"http://127.0.0.1:{port}" + ("/api/health" if port == 8000 else "/health")
                            ).status_code
                            == 200
                        ):
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError("服务启动超时")
                    time.sleep(0.05)
            handle = (logs / "worker.txt").open("w")
            handles.append(handle)
            worker = subprocess.Popen(
                [sys.executable, "-m", "services.worker.main"],
                env=env | {"EXAMPLE_CREDENTIAL_FILE": credentials["platform"]},
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            children.append(worker)
            yield {"http": http, "env": env, "children": children, "logs": logs, "db": database}
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for handle in handles:
            handle.close()
