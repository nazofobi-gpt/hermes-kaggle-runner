#!/usr/bin/env python3
"""Read-only G-003 probe for two independent PostgreSQL backend sessions.

The script never prints the connection string or exception text. It performs
SELECT-only checks and deliberately does not attempt any write/CAS operation.
"""

from __future__ import annotations

import os
import sys

dsn = os.environ.get("NEON_DATABASE_URL", "").strip()
if not dsn:
    print("G003_NEON_DATABASE_URL=NOT_CONFIGURED")
    raise SystemExit(0)

try:
    import psycopg
except Exception:
    print("G003_PSYCOPG_IMPORT=FAIL")
    raise SystemExit(20)

connections = []
try:
    for _ in range(2):
        connections.append(
            psycopg.connect(
                dsn,
                connect_timeout=10,
                autocommit=True,
                application_name="g003-readonly-pid-probe",
            )
        )

    observations = []
    for connection in connections:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_backend_pid(), current_database(), "
                "current_setting('transaction_read_only')"
            )
            observations.append(cursor.fetchone())

    pid_a, db_a, read_only_a = observations[0]
    pid_b, db_b, read_only_b = observations[1]

    if db_a != "g003_test" or db_b != "g003_test":
        print("G003_DATABASE_TARGET=FAIL")
        raise SystemExit(21)

    if pid_a == pid_b:
        print("G003_DISTINCT_BACKEND_PIDS=FAIL")
        raise SystemExit(22)

    print("G003_DATABASE_TARGET=PASS")
    print("G003_DISTINCT_BACKEND_PIDS=PASS")
    print(f"G003_BACKEND_PIDS={pid_a},{pid_b}")
    print(f"G003_TRANSACTION_READ_ONLY={read_only_a},{read_only_b}")
    print("G003_PROBE=READ_ONLY_ONLY")

except SystemExit:
    raise
except Exception as error:
    print("G003_CONNECTION_PROBE=FAIL")
    print(f"G003_ERROR_TYPE={type(error).__name__}")
    sqlstate = getattr(error, "sqlstate", None)
    if sqlstate:
        print(f"G003_SQLSTATE={sqlstate}")
    raise SystemExit(23)
finally:
    for connection in connections:
        try:
            connection.close()
        except Exception:
            pass
