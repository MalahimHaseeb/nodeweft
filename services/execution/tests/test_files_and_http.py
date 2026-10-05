import io

import pytest
from openpyxl import Workbook

from app.engine.errors import NodeError
from app.nodes.excel import is_safe_key, parse_csv, parse_xlsx, read_local_file
from app.nodes.safe_http import clean_headers, is_blocked_address
from app.settings import ExecutionSettings


def test_csv_headers_are_normalised_and_blank_rows_skipped():
    content = b"Task ID, Title ,Due Date,Title\n1,Fix bug,2026-01-01,x\n,,,\n2,Ship,2026-02-01,y\n"
    items = parse_csv(content, 100)
    assert items[0] == {"task_id": "1", "title": "Fix bug", "due_date": "2026-01-01", "title_2": "x"}
    assert len(items) == 2


def test_row_limit_is_an_error_not_a_silent_cut():
    rows = "id\n" + "\n".join(str(index) for index in range(10))
    with pytest.raises(NodeError):
        parse_csv(rows.encode(), 5)


def test_xlsx_parsing_and_sheet_selection():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tasks"
    sheet.append(["ID", "Title"])
    sheet.append([1, "One"])
    sheet.append([2, "Two"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    assert parse_xlsx(buffer.getvalue(), "Tasks", 10) == [{"id": 1, "title": "One"}, {"id": 2, "title": "Two"}]
    with pytest.raises(NodeError):
        parse_xlsx(buffer.getvalue(), "Missing", 10)
    with pytest.raises(NodeError):
        parse_xlsx(b"not an excel file", None, 10)


def test_path_traversal_rejected(tmp_path):
    (tmp_path / "ok.csv").write_text("id\n1\n")
    settings = ExecutionSettings(allow_local_files=True, local_files_dir=str(tmp_path))
    assert read_local_file(settings, "ok.csv").startswith(b"id")
    with pytest.raises(NodeError):
        read_local_file(settings, "../etc/passwd")
    assert not is_safe_key("../secret.csv")
    assert not is_safe_key("/abs/path.csv")
    assert is_safe_key("folder/tasks.csv")


def test_local_files_disabled_by_default(tmp_path):
    settings = ExecutionSettings(local_files_dir=str(tmp_path))
    with pytest.raises(NodeError):
        read_local_file(settings, "ok.csv")


def test_blocked_addresses():
    for address in ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "0.0.0.0"]:
        assert is_blocked_address(address)
    assert not is_blocked_address("8.8.8.8")


def test_header_cleaning():
    assert clean_headers({"X-Api-Key": "abc"}) == {"X-Api-Key": "abc"}
    with pytest.raises(NodeError):
        clean_headers({"Host": "evil"})
    with pytest.raises(NodeError):
        clean_headers({"X-Test": "a\r\nInjected: 1"})
