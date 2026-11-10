import pytest

from app.core.fingerprint import make_fingerprint
from app.core.tokens import approval_message, sign, verify
from app.rag.embeddings import DIM, cosine, embed
from mcp_servers.sqlguard import validate_sql


def test_signature_roundtrip():
    sig = sign("secret", b"body")
    assert verify("secret", b"body", sig)
    assert not verify("secret", b"tampered", sig)
    assert not verify("other", b"body", sig)
    assert not verify("secret", b"body", None)


def test_approval_token_is_bound_to_incident_action_and_target():
    token = sign("s", approval_message("inc-1", "rollback_service", "payments"))
    assert verify("s", approval_message("inc-1", "rollback_service", "payments"), token)
    assert not verify("s", approval_message("inc-2", "rollback_service", "payments"), token)
    assert not verify("s", approval_message("inc-1", "restart_container", "payments"), token)
    assert not verify("s", approval_message("inc-1", "rollback_service", "orders"), token)


def test_fingerprint_same_problem_same_code():
    assert make_fingerprint("payments", "HighErrorRate") == make_fingerprint("payments", "HighErrorRate")
    assert make_fingerprint("payments", "HighErrorRate") != make_fingerprint("orders", "HighErrorRate")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM log_events LIMIT 5",
    "select count(*) from metric_points where service = 'payments';",
    "WITH x AS (SELECT 1) SELECT * FROM x",
])
def test_sqlguard_allows_selects(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "DROP TABLE log_events",
    "SELECT 1; DROP TABLE log_events",
    "DELETE FROM log_events",
    "SELECT * FROM scenario_runs",
    "WITH d AS (DELETE FROM log_events RETURNING *) SELECT * FROM d",
    "SELECT pg_sleep(10)",
    "UPDATE incidents SET status = 'x'",
    "",
])
def test_sqlguard_blocks_everything_else(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_embedding_shape_and_similarity():
    a = embed("database connection pool timeout errors after config change")
    b = embed("connection pool timeout runbook config change rollback")
    c = embed("memory usage keeps growing garbage collection")
    assert len(a) == DIM
    assert abs(sum(x * x for x in a) - 1) < 1e-6
    assert cosine(a, b) > cosine(a, c)
