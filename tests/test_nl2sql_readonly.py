"""Defence-in-depth: NL2SQL executes LLM-generated SQL inside a read-only
PostgreSQL transaction, so any write that slips past the regex blocklist
(_validate_sql) is rejected by the database itself.

These are pure unit tests over _execute_query with a faked DB connection —
they assert the guard is *wired* (the statements issued, in order). The actual
"cannot execute in a read-only transaction" rejection is a PostgreSQL behaviour
and is not reproducible against the sqlite test DB.
"""

from unittest.mock import patch

import pytest

from aifw.nl2sql.engine import _execute_query, _validate_sql


class _FakeCursor:
    def __init__(self):
        self.executed: list[str] = []
        self.description: list = []

    def execute(self, sql):
        self.executed.append(sql)

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, vendor, in_atomic_block=False):
        self.vendor = vendor
        self.in_atomic_block = in_atomic_block
        self._cursor = _FakeCursor()

    def cursor(self):
        return self._cursor


def test_should_enforce_read_only_transaction_on_postgres():
    conn = _FakeConn("postgresql")
    with patch("django.db.connections", {"analytics": conn}), patch("django.db.transaction") as tx:
        _execute_query("SELECT 1", db_alias="analytics", max_rows=100, timeout_seconds=5)

    stmts = conn._cursor.executed
    assert stmts[0] == "SET TRANSACTION READ ONLY"  # first statement of the txn
    assert any("statement_timeout" in s for s in stmts)
    assert stmts[-1].startswith("SELECT 1")  # the LLM SQL runs after the guards
    tx.atomic.assert_called_once_with(using="analytics")
    tx.set_rollback.assert_called_once()  # read-only — never commit


def test_should_skip_read_only_when_already_in_atomic_block():
    """Cannot set READ ONLY mid-transaction; degrade to regex-only (logged)."""
    conn = _FakeConn("postgresql", in_atomic_block=True)
    with patch("django.db.connections", {"analytics": conn}), patch("django.db.transaction") as tx:
        _execute_query("SELECT 1", db_alias="analytics", max_rows=100, timeout_seconds=5)

    stmts = conn._cursor.executed
    assert all("READ ONLY" not in s for s in stmts)
    tx.atomic.assert_not_called()


def test_should_not_issue_postgres_only_statements_on_sqlite():
    conn = _FakeConn("sqlite")
    with patch("django.db.connections", {"analytics": conn}), patch("django.db.transaction") as tx:
        _execute_query("SELECT 1", db_alias="analytics", max_rows=100, timeout_seconds=5)

    stmts = conn._cursor.executed
    assert all("READ ONLY" not in s for s in stmts)
    assert all("statement_timeout" not in s for s in stmts)  # SET LOCAL no-op guard
    tx.atomic.assert_not_called()
    assert stmts == ["SELECT 1 LIMIT 101"]


# ── Stacked Queries (platform#2546) ──────────────────────────────────────────
# Gemessen am 2026-08-31 gegen aifw 0.13.1: `SELECT * FROM a; SELECT pg_sleep(10)`
# wurde durchgelassen. Die Keyword-Liste prueft die gesamte Zeichenkette und faengt
# eine zweite Anweisung nur, wenn diese ein verbotenes Wort enthaelt — zwei SELECTs
# bestehen sie, und das zweite kann trotzdem ein DoS sein.
# Anlass: der NL2SQL-Dienst in ttz-hub prueft das seit jeher selbst und soll auf
# diese Engine umgestellt werden. Ohne diesen Schutz waere die Umstellung ein
# Sicherheitsrueckschritt.
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT * FROM a; SELECT pg_sleep(10)",
        "WITH x AS (SELECT 1) SELECT * FROM x; SELECT 2",
    ],
)
def test_should_reject_stacked_statements(sql):
    assert _validate_sql(sql, set()) == "Nur eine SQL-Anweisung ist erlaubt."


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT 1;",  # abschliessendes Semikolon ist keine zweite Anweisung
        "SELECT 1 ; ",
        "SELECT ';' AS x",  # Semikolon im Stringliteral
        "SELECT 'a;b' FROM t",
        "WITH x AS (SELECT 1) SELECT * FROM x",
    ],
)
def test_should_allow_single_statements_and_semicolons_in_strings(sql):
    # Der Gegenfall: die Regel darf nicht breiter greifen als gemeint. Ein
    # Semikolon in einem Stringliteral ist Daten, keine Anweisungsgrenze.
    assert _validate_sql(sql, set()) is None
