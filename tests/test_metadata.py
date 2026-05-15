from src.metadata import (
    build_metadata_from_editor_rows,
    build_simple_metadata_filter,
    merge_metadata,
    metadata_filter_value,
    parse_metadata_lines,
)


def test_parse_metadata_lines_supports_string_numeric_and_list_values():
    result = parse_metadata_lines(
        """
        author="Robert Graves"
        year=1934
        tags=[history, roman]
        """
    )

    assert result.errors == []
    assert result.items == [
        {"key": "author", "string_value": "Robert Graves"},
        {"key": "year", "numeric_value": 1934.0},
        {"key": "tags", "string_list_value": {"values": ["history", "roman"]}},
    ]


def test_metadata_editor_rows_validate_reserved_and_numeric_values():
    result = build_metadata_from_editor_rows(
        [
            {"key": "department", "value": "Support", "type": "String"},
            {"key": "revision", "value": "2.5", "type": "Number"},
            {"key": "source_id", "value": "bad", "type": "String"},
        ]
    )

    assert result.items == [
        {"key": "department", "string_value": "Support"},
        {"key": "revision", "numeric_value": 2.5},
    ]
    assert "reserved" in result.errors[0]


def test_merge_metadata_enforces_file_search_item_limit():
    source = [{"key": "source_id", "string_value": "abc"}]
    user = [{"key": f"k{i}", "string_value": "v"} for i in range(20)]

    result = merge_metadata(source, user)

    assert "at most 20 custom metadata entries" in result.errors[0]


def test_build_simple_metadata_filter_quotes_strings_and_keeps_numbers():
    string_filter = build_simple_metadata_filter("department", "=", "Service Ops", "String")
    number_filter = build_simple_metadata_filter("year", ">=", "2024", "Number")

    assert metadata_filter_value(string_filter) == 'department = "Service Ops"'
    assert metadata_filter_value(number_filter) == "year >= 2024"


def test_advanced_metadata_filter_passes_through():
    result = build_simple_metadata_filter("", "=", "", "String", 'author = "Robert Graves"')

    assert metadata_filter_value(result) == 'author = "Robert Graves"'
