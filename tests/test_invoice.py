import sqlite3
from decimal import Decimal

from chinook_agent import db

OWN_INVOICE = 382
FOREIGN_INVOICE = 293
PROTECTED_INVOICE = 207


def test_own_invoice_total_matches():
    invoice = db.get_invoice(1, OWN_INVOICE)

    assert invoice["invoice_id"] == OWN_INVOICE
    assert invoice["invoice_date"] == "2025-08-07"
    assert invoice["total"] == Decimal("8.91")
    assert len(invoice["lines"]) == 9


def test_lines_sum_to_total(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        owners = connection.execute("SELECT CustomerId, InvoiceId FROM Invoice").fetchall()
    finally:
        connection.close()

    assert len(owners) == 412
    for customer_id, invoice_id in owners:
        invoice = db.get_invoice(customer_id, invoice_id)
        charged = sum(
            (line["unit_price"] * line["quantity"] for line in invoice["lines"]),
            Decimal("0"),
        )

        assert charged == invoice["total"]


def test_foreign_invoice_looks_identical_to_missing_invoice():
    foreign = db.get_invoice(1, FOREIGN_INVOICE)
    missing = db.get_invoice(1, 999999)

    assert foreign == missing == db.INVOICE_NOT_FOUND


def test_refusal_echoes_no_invoice_data():
    refusal = str(db.get_invoice(1, FOREIGN_INVOICE))

    assert "293" not in refusal
    assert "0.99" not in refusal


def test_no_customer_can_read_another_customers_invoice(chinook_db):
    connection = sqlite3.connect(chinook_db)
    try:
        owners = dict(
            connection.execute(
                "SELECT InvoiceId, CustomerId FROM Invoice WHERE InvoiceId IN (1, 293, 382, 412)"
            )
        )
    finally:
        connection.close()

    for invoice_id, owner in owners.items():
        for customer_id in range(1, 60):
            if customer_id != owner:
                assert db.get_invoice(customer_id, invoice_id) == db.INVOICE_NOT_FOUND


def test_lines_carry_what_a_refund_needs():
    lines = db.get_invoice(54, PROTECTED_INVOICE)["lines"]
    protected = [line for line in lines if line["media_type"] == "Protected AAC audio file"]

    assert len(lines) == 9
    assert len(protected) == 6
    for line in lines:
        assert isinstance(line["unit_price"], Decimal)
        assert line["invoice_line_id"] and line["track_id"] and line["track"]


def test_not_found_result_cannot_be_mutated_by_a_caller():
    db.get_invoice(1, 999999)["error"] = "changed"

    assert db.INVOICE_NOT_FOUND == {"error": "Invoice not found on this account."}
