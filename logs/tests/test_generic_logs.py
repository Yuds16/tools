"""Unit tests for generic_logs.py.

These logs are plain pipe-delimited text, so the parser is exercised directly
against the checked-in fixture (``sample_data/sample_log.log``) plus a few
inline strings that cover edge cases the fixture doesn't (missing/empty fields,
messages containing a literal ``|``, empty files).

Run from the repository root with the project virtualenv:

    .venv/bin/python -m unittest discover -s logs/tests -v
"""

import os
import sys
import unittest

# Make ``generic_logs`` importable regardless of the cwd.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import generic_logs as g  # noqa: E402

SAMPLE_LOG = os.path.join(os.path.dirname(__file__), "sample_data", "sample_log.log")

# Columns produced from the fixture's header row. 'DATE TIME' expands to two.
SAMPLE_COLUMNS = [
    "date", "time", "level", "facility", "process", "pid", "tid",
    "topic", "file_name_line", "message",
]


def write_log(tmp_path, text):
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    return tmp_path


# --------------------------------------------------------------------------- #
# normalize_column
# --------------------------------------------------------------------------- #

class NormalizeColumnTests(unittest.TestCase):
    def test_simple_upper(self):
        self.assertEqual(g.normalize_column("LEVEL"), "level")

    def test_parentheses_become_underscore(self):
        self.assertEqual(g.normalize_column("FILE_NAME(LINE)"), "file_name_line")

    def test_collapses_runs_and_trims(self):
        self.assertEqual(g.normalize_column("  PID  "), "pid")

    def test_already_snake(self):
        self.assertEqual(g.normalize_column("file_name"), "file_name")


# --------------------------------------------------------------------------- #
# parse_header
# --------------------------------------------------------------------------- #

class ParseHeaderTests(unittest.TestCase):
    def test_expands_date_time_and_counts_tokens(self):
        columns, counts = g.parse_header(
            "DATE       TIME   |LEVEL |FILE_NAME(LINE) | MESSAGE"
        )
        self.assertEqual(columns, ["date", "time", "level", "file_name_line", "message"])
        # First segment holds two columns, the rest one each.
        self.assertEqual(counts, [2, 1, 1, 1])

    def test_single_column(self):
        columns, counts = g.parse_header("MESSAGE")
        self.assertEqual((columns, counts), (["message"], [1]))


# --------------------------------------------------------------------------- #
# parse_line
# --------------------------------------------------------------------------- #

class ParseLineTests(unittest.TestCase):
    def test_splits_multi_token_segment(self):
        # First field maps to two columns -> split on first whitespace.
        values = g.parse_line("2025-01-01 00:00:00.000Z |Debug | hello", [2, 1, 1])
        self.assertEqual(values, ["2025-01-01", "00:00:00.000Z", "Debug", "hello"])

    def test_message_keeps_embedded_pipe(self):
        values = g.parse_line("a |b | has | pipes", [1, 1, 1])
        self.assertEqual(values, ["a", "b", "has | pipes"])

    def test_empty_field_becomes_none(self):
        values = g.parse_line("a |   | c", [1, 1, 1])
        self.assertEqual(values, ["a", None, "c"])

    def test_missing_trailing_fields_padded_with_none(self):
        values = g.parse_line("a |b", [1, 1, 1])
        self.assertEqual(values, ["a", "b", None])

    def test_short_multi_token_segment_padded(self):
        # Only one token where two columns are expected.
        values = g.parse_line("2025-01-01 |Debug", [2, 1])
        self.assertEqual(values, ["2025-01-01", None, "Debug"])


# --------------------------------------------------------------------------- #
# log_to_df — against the checked-in fixture
# --------------------------------------------------------------------------- #

class LogToDfFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = g.log_to_df(SAMPLE_LOG)

    def test_columns_match_header(self):
        self.assertEqual(list(self.df.columns), SAMPLE_COLUMNS)

    def test_blank_lines_skipped(self):
        # The fixture has 5 data rows plus one blank line that must be dropped.
        self.assertEqual(len(self.df), 5)

    def test_first_row_values(self):
        row = self.df.iloc[0]
        self.assertEqual(row["date"], "2025-XX-XX")
        self.assertEqual(row["time"], "00:00:00.000Z")
        self.assertEqual(row["level"], "Debug")
        self.assertEqual(row["facility"], "app")
        self.assertEqual(row["process"], "proc")
        self.assertEqual(row["pid"], "00000")
        self.assertEqual(row["tid"], "00000")
        self.assertEqual(row["topic"], "topic")
        self.assertEqual(row["file_name_line"], "runtime.cpp(73)")
        self.assertEqual(row["message"], "Runtime is loaded by process")

    def test_values_are_stripped_of_padding(self):
        # Header padding must not leak into parsed values.
        self.assertTrue(all(v == v.strip() for v in self.df["level"]))

    def test_topic_varies_across_rows(self):
        self.assertEqual(
            list(self.df["topic"]),
            ["topic", "topic", "client", "stub", "server"],
        )


# --------------------------------------------------------------------------- #
# log_to_df — edge cases via temp files
# --------------------------------------------------------------------------- #

class LogToDfEdgeCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(
            os.path.dirname(__file__), "sample_data", "_tmp_test.log"
        )

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_header_only_returns_empty_frame_with_columns(self):
        write_log(self.tmp, "DATE       TIME   |LEVEL | MESSAGE\n")
        df = g.log_to_df(self.tmp)
        self.assertEqual(len(df), 0)
        self.assertEqual(list(df.columns), ["date", "time", "level", "message"])

    def test_empty_file_returns_empty_frame(self):
        write_log(self.tmp, "")
        df = g.log_to_df(self.tmp)
        self.assertEqual(len(df), 0)

    def test_message_with_pipe_preserved(self):
        write_log(
            self.tmp,
            "DATE       TIME   |LEVEL | MESSAGE\n"
            "2025-01-01 00:00:00.000Z |Info | a | b | c\n",
        )
        df = g.log_to_df(self.tmp)
        self.assertEqual(df.iloc[0]["message"], "a | b | c")

    def test_empty_fields_map_to_none(self):
        write_log(
            self.tmp,
            "DATE       TIME   |LEVEL | MESSAGE\n"
            "2025-01-01 00:00:00.000Z |     | \n",
        )
        df = g.log_to_df(self.tmp)
        self.assertIsNone(df.iloc[0]["level"])
        self.assertIsNone(df.iloc[0]["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
