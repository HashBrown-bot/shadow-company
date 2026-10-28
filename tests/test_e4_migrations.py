from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import temporary_database
from tests.test_migrations import seed_run


def test_populated_e3_upgrade_preserves_evidence_and_scopes(config_data):
    with temporary_database() as (engine, config):
        command.upgrade(config, "0002_e3")
        scope = seed_run(engine, config_data)
        oid = uuid4()
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO observations VALUES (:p,:r,:id,'put','existing','product_observation','private://existing',:h,now(),'{\"amount_minor\":-1}')"
                ),
                scope | {"id": oid},
            )
            c.execute(text("INSERT INTO refund_put.namespaces VALUES (:p,:r,'{}')"), scope)
            c.execute(text("INSERT INTO refund_put.payments VALUES (:p,:r,'original',100,'CNY',0)"), scope)
        command.upgrade(config, "head")
        with engine.connect() as c:
            assert c.execute(
                text("SELECT payload FROM observations WHERE project_id=:p AND run_id=:r"), scope
            ).scalar_one() == {"amount_minor": -1}
            assert (
                c.execute(
                    text("SELECT behavior FROM refund_put.namespaces WHERE project_id=:p AND run_id=:r"),
                    scope,
                ).scalar_one()
                == "fixed"
            )
            assert (
                c.execute(
                    text("SELECT owner_id FROM refund_put.payments WHERE project_id=:p AND run_id=:r"), scope
                ).scalar_one()
                == "customer_a"
            )
            assert (
                c.execute(text("SELECT content_hash FROM contracts WHERE project_id=:p"), scope).scalar_one()
                == scope["h"]
            )
        eid = uuid4()
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO evaluations(project_id,run_id,evaluation_id,evidence_hash,rules_hash,payload) VALUES (:p,:r,:id,:h,:h,'{}')"
                ),
                scope | {"id": eid},
            )
        with pytest.raises(IntegrityError, match="immutable record"):
            with engine.begin() as c:
                c.execute(text("UPDATE evaluations SET payload='[]' WHERE evaluation_id=:id"), {"id": eid})
        with pytest.raises(IntegrityError):
            with engine.begin() as c:
                c.execute(
                    text(
                        "INSERT INTO check_results VALUES (:p,:r,:id,'REFUND_001','1','object','pass','scope test','[]',now(),:evaluation)"
                    ),
                    scope | {"id": uuid4(), "evaluation": uuid4()},
                )
        command.downgrade(config, "0002_e3")
        command.upgrade(config, "head")
        with engine.connect() as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM observations WHERE project_id=:p AND run_id=:r"), scope
                ).scalar_one()
                == 1
            )
