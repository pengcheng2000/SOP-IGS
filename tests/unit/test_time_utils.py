from datetime import UTC, datetime

from app.time_utils import utc_iso


def test_naive_sqlite_datetime_is_serialized_as_utc():
    naive_utc = datetime(2026, 9, 16, 8, 34, 46, tzinfo=UTC).replace(tzinfo=None)
    assert utc_iso(naive_utc) == "2026-09-16T08:34:46Z"
