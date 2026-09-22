import pytest
from app.services.docx.toc import number_separator_span


@pytest.mark.parametrize("original,expected", [
    ("1.\t概述\t5\r", "1. 概述\t5\r"),
    ("5.2.1.\t\tBMS\t12\r", "5.2.1. BMS\t12\r"),
    ("5.2.1.1.  消防系统\t13\r", "5.2.1.1. 消防系统\t13\r"),
    ("4.3. 样品照片\t6\r", "4.3. 样品照片\t6\r"),
    ("报告更新说明\t3\r", "报告更新说明\t3\r"),
])
def test_toc_only_number_separator(original, expected):
    span = number_separator_span(original)
    actual = original[:span[0]] + ' ' + original[span[1]:] if span else original
    assert actual == expected
