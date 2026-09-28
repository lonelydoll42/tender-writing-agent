from __future__ import annotations

from tests.evals.cases import REGRESSION_CASES


def test_regression_catalog_has_the_ten_required_cases() -> None:
    assert [case["id"] for case in REGRESSION_CASES] == [
        "TC01",
        "TC02",
        "TC03",
        "TC04",
        "TC05",
        "TC06",
        "TC07",
        "TC08",
        "TC09",
        "TC10",
    ]
    assert sum(1 for case in REGRESSION_CASES if case["supported"]) == 9
    assert sum(1 for case in REGRESSION_CASES if not case["supported"]) == 1
