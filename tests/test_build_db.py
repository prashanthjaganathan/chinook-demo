import sqlite3


def test_database_has_expected_row_counts(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        invoices = connection.execute("SELECT COUNT(*) FROM Invoice").fetchone()[0]
        tracks = connection.execute("SELECT COUNT(*) FROM Track").fetchone()[0]
        customers = connection.execute("SELECT COUNT(*) FROM Customer").fetchone()[0]
    finally:
        connection.close()

    assert (invoices, tracks, customers) == (412, 3503, 59)
