import pytest

from chinook_agent import db

CUSTOMER_FUNCTIONS = (db.get_library, db.partial_albums)
BAD_IDS = ("2", 2.0, 0, -1, 2**63, None, [1])


@pytest.mark.parametrize("function", CUSTOMER_FUNCTIONS, ids=lambda f: f.__name__)
def test_customer_id_must_be_a_real_int(function):
    for value in BAD_IDS:
        with pytest.raises(ValueError):
            function(value)


@pytest.mark.parametrize("function", CUSTOMER_FUNCTIONS, ids=lambda f: f.__name__)
def test_boolean_customer_id_does_not_become_customer_one(function):
    with pytest.raises(ValueError):
        function(True)
