import pytest

from chinook_agent import db

BAD_IDS = ("2", 2.0, 0, -1, 2**63, None, [1], True)

CUSTOMER_FUNCTIONS = [
    pytest.param(db.get_library, id="get_library"),
    pytest.param(db.partial_albums, id="partial_albums"),
    pytest.param(lambda customer_id: db.missing_tracks(customer_id, 1), id="missing_tracks"),
    pytest.param(lambda customer_id: db.get_invoice(customer_id, 1), id="get_invoice"),
]
ALBUM_FUNCTIONS = [
    pytest.param(lambda album_id: db.missing_tracks(1, album_id), id="missing_tracks"),
]
INVOICE_FUNCTIONS = [
    pytest.param(lambda invoice_id: db.get_invoice(1, invoice_id), id="get_invoice"),
]


@pytest.mark.parametrize("function", CUSTOMER_FUNCTIONS)
def test_customer_id_must_be_a_real_int(function):
    for value in BAD_IDS:
        with pytest.raises(ValueError):
            function(value)


@pytest.mark.parametrize("function", ALBUM_FUNCTIONS)
def test_album_id_must_be_a_real_int(function):
    for value in BAD_IDS:
        with pytest.raises(ValueError):
            function(value)


@pytest.mark.parametrize("function", CUSTOMER_FUNCTIONS)
def test_boolean_customer_id_does_not_become_customer_one(function):
    with pytest.raises(ValueError):
        function(True)


@pytest.mark.parametrize("function", INVOICE_FUNCTIONS)
def test_invoice_id_must_be_a_real_int(function):
    for value in BAD_IDS:
        with pytest.raises(ValueError):
            function(value)
