"""Unit tests for windows_logs.py.

The module parses Windows Event Log (.evtx) records into pandas DataFrames.
Real .evtx files are a binary format, so the ``Evtx.Evtx`` reader is mocked:
each fake record simply returns a canned XML string, exercising the real XML
parsing and DataFrame assembly without needing a binary fixture.

The pure helpers (parse_system, parse_event_data, parse_user_data,
to_snake_case, strip_ns) are tested directly against ElementTree input.

Run from the repository root with the project virtualenv:

    .venv/bin/python -m unittest discover -s windows_logs/tests -v
"""

import os
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

# Make ``windows_logs`` importable regardless of the current working directory.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import windows_logs as w  # noqa: E402

EVENTS_NS = "http://schemas.microsoft.com/win/2004/08/events/event"


# --------------------------------------------------------------------------- #
# XML fixtures / helpers
# --------------------------------------------------------------------------- #

def event_xml(system_inner, extra_inner=""):
    """Wrap the given <System> body (and optional EventData/UserData) in an Event."""
    return (
        f'<Event xmlns="{EVENTS_NS}">'
        f"<System>{system_inner}</System>"
        f"{extra_inner}"
        f"</Event>"
    )


FULL_SYSTEM = (
    '<Provider Name="Microsoft-Windows-Eventlog" Guid="{PROV-GUID}"/>'
    "<EventID>104</EventID>"
    "<Version>0</Version>"
    "<Level>4</Level>"
    "<Task>0</Task>"
    "<Opcode>0</Opcode>"
    "<Keywords>0x8000000000000000</Keywords>"
    '<TimeCreated SystemTime="2024-01-01T00:00:00.000000Z"/>'
    "<EventRecordID>42</EventRecordID>"
    '<Correlation ActivityID="{ACT-ID}" RelatedActivityID="{REL-ID}"/>'
    '<Execution ProcessID="4" ThreadID="8"/>'
    "<Channel>System</Channel>"
    "<Computer>HOST-01</Computer>"
    '<Security UserID="S-1-5-18"/>'
)


def fake_evtx(xml_strings):
    """Return a mock standing in for ``Evtx.Evtx`` that yields the given records.

    ``Evtx(fname)`` is used as a context manager whose ``log.records()`` yields
    records each exposing ``.xml()``.
    """
    def factory(_fname):
        records = []
        for xml in xml_strings:
            rec = mock.MagicMock()
            rec.xml.return_value = xml
            records.append(rec)
        log = mock.MagicMock()
        log.records.return_value = records
        cm = mock.MagicMock()
        cm.__enter__.return_value = log
        cm.__exit__.return_value = False
        return cm

    return factory


# --------------------------------------------------------------------------- #
# to_snake_case
# --------------------------------------------------------------------------- #

class ToSnakeCaseTests(unittest.TestCase):
    def test_pascal_case(self):
        self.assertEqual(w.to_snake_case("PackageIdentifier"), "package_identifier")
        self.assertEqual(w.to_snake_case("AppName"), "app_name")
        self.assertEqual(w.to_snake_case("ExceptionCode"), "exception_code")

    def test_trailing_acronym_word(self):
        self.assertEqual(w.to_snake_case("ProcessId"), "process_id")
        self.assertEqual(w.to_snake_case("PackageRelativeAppId"), "package_relative_app_id")

    def test_already_snake_or_lower(self):
        self.assertEqual(w.to_snake_case("client"), "client")

    def test_all_caps_stays_together(self):
        self.assertEqual(w.to_snake_case("ID"), "id")

    def test_leading_acronym(self):
        # Consecutive capitals are only split before the final Capital+lower run.
        self.assertEqual(w.to_snake_case("HTTPServer"), "http_server")

    def test_trailing_digits(self):
        self.assertEqual(w.to_snake_case("Data0"), "data0")


# --------------------------------------------------------------------------- #
# strip_ns
# --------------------------------------------------------------------------- #

class StripNsTests(unittest.TestCase):
    def test_removes_namespace(self):
        self.assertEqual(w.strip_ns("{" + EVENTS_NS + "}EventID"), "EventID")

    def test_no_namespace_returned_unchanged(self):
        self.assertEqual(w.strip_ns("EventID"), "EventID")

    def test_empty_braces(self):
        self.assertEqual(w.strip_ns("{}Local"), "Local")


# --------------------------------------------------------------------------- #
# parse_system
# --------------------------------------------------------------------------- #

class ParseSystemTests(unittest.TestCase):
    def _system_of(self, system_inner):
        root = ET.fromstring(event_xml(system_inner))
        return root.find(f"{w.NS}System")

    def test_full_record_maps_every_field(self):
        result = w.parse_system(self._system_of(FULL_SYSTEM))
        self.assertEqual(result, {
            "provider_name": "Microsoft-Windows-Eventlog",
            "provider_guid": "{PROV-GUID}",
            "event_id": "104",
            "version": "0",
            "level": "4",
            "task": "0",
            "opcode": "0",
            "keywords": "0x8000000000000000",
            "time_created": "2024-01-01T00:00:00.000000Z",
            "event_record_id": "42",
            "activity_id": "{ACT-ID}",
            "related_activity_id": "{REL-ID}",
            "process_id": "4",
            "thread_id": "8",
            "channel": "System",
            "computer": "HOST-01",
            "user_id": "S-1-5-18",
        })

    def test_missing_optional_elements_become_none(self):
        # Only EventID and Channel present; every attribute-bearing sub-element
        # (Provider, TimeCreated, Correlation, Execution, Security) is absent.
        result = w.parse_system(self._system_of("<EventID>1</EventID><Channel>System</Channel>"))
        self.assertEqual(result["event_id"], "1")
        self.assertEqual(result["channel"], "System")
        for missing in ("provider_name", "provider_guid", "time_created",
                        "activity_id", "related_activity_id", "process_id",
                        "thread_id", "user_id", "computer", "level"):
            self.assertIsNone(result[missing], f"expected {missing} to be None")

    def test_partial_correlation_only_activity_id(self):
        result = w.parse_system(self._system_of(
            '<EventID>1</EventID><Correlation ActivityID="{A}"/>'))
        self.assertEqual(result["activity_id"], "{A}")
        self.assertIsNone(result["related_activity_id"])

    def test_result_has_exactly_the_header_keys(self):
        result = w.parse_system(self._system_of(FULL_SYSTEM))
        self.assertEqual(set(result.keys()), set(w.header))


# --------------------------------------------------------------------------- #
# parse_event_data
# --------------------------------------------------------------------------- #

class ParseEventDataTests(unittest.TestCase):
    def _root(self, extra_inner):
        return ET.fromstring(event_xml("<EventID>1</EventID>", extra_inner))

    def test_named_data_pairs(self):
        root = self._root(
            "<EventData>"
            '<Data Name="TargetUserName">alice</Data>'
            '<Data Name="LogonType">3</Data>'
            "</EventData>"
        )
        self.assertEqual(w.parse_event_data(root), {"TargetUserName": "alice", "LogonType": "3"})

    def test_unnamed_data_uses_positional_key(self):
        root = self._root("<EventData><Data>first</Data><Data>second</Data></EventData>")
        self.assertEqual(w.parse_event_data(root), {"Data0": "first", "Data1": "second"})

    def test_no_event_data_returns_empty(self):
        root = self._root("")
        self.assertEqual(w.parse_event_data(root), {})

    def test_empty_data_element_maps_to_none(self):
        root = self._root('<EventData><Data Name="Foo"></Data></EventData>')
        self.assertEqual(w.parse_event_data(root), {"Foo": None})


# --------------------------------------------------------------------------- #
# parse_user_data
# --------------------------------------------------------------------------- #

class ParseUserDataTests(unittest.TestCase):
    def _root(self, extra_inner):
        return ET.fromstring(event_xml("<EventID>1</EventID>", extra_inner))

    def test_collects_leaf_fields_and_skips_containers(self):
        root = self._root(
            "<UserData>"
            "<CbsPackageChangeState>"
            "<PackageIdentifier>Package_for_KB123</PackageIdentifier>"
            "<Client>UpdateAgent</Client>"
            "</CbsPackageChangeState>"
            "</UserData>"
        )
        result = w.parse_user_data(root)
        self.assertEqual(result, {"PackageIdentifier": "Package_for_KB123", "Client": "UpdateAgent"})
        # The container element itself must not appear as a field.
        self.assertNotIn("CbsPackageChangeState", result)

    def test_strips_namespace_from_leaf_tags(self):
        custom_ns = "myschema"
        root = self._root(
            "<UserData>"
            f'<Payload xmlns="{custom_ns}"><Channel>Security</Channel></Payload>'
            "</UserData>"
        )
        self.assertEqual(w.parse_user_data(root), {"Channel": "Security"})

    def test_no_user_data_returns_empty(self):
        self.assertEqual(w.parse_user_data(self._root("")), {})


# --------------------------------------------------------------------------- #
# evtx_to_df
# --------------------------------------------------------------------------- #

class EvtxToDfTests(unittest.TestCase):
    def test_builds_dataframe_from_records(self):
        xml = event_xml(FULL_SYSTEM,
                        '<EventData><Data Name="param1">foo</Data></EventData>')
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml, xml])):
            df = w.evtx_to_df("ignored.evtx")

        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[0]["event_id"], "104")
        self.assertEqual(df.iloc[0]["computer"], "HOST-01")
        # Dynamic EventData column is present, un-snaked.
        self.assertEqual(df.iloc[0]["param1"], "foo")

    def test_empty_log_yields_empty_dataframe(self):
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([])):
            df = w.evtx_to_df("ignored.evtx")
        self.assertEqual(len(df), 0)

    def test_does_not_snake_case_event_data_keys(self):
        xml = event_xml("<EventID>1</EventID>",
                        '<EventData><Data Name="TargetUserName">bob</Data></EventData>')
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml])):
            df = w.evtx_to_df("ignored.evtx")
        self.assertIn("TargetUserName", df.columns)
        self.assertNotIn("target_user_name", df.columns)


# --------------------------------------------------------------------------- #
# evtx_to_df_snake
# --------------------------------------------------------------------------- #

class EvtxToDfSnakeTests(unittest.TestCase):
    def test_snake_cases_extra_fields_and_reads_user_data(self):
        xml = event_xml(
            "<EventID>1</EventID>",
            "<UserData><Payload>"
            "<PackageIdentifier>KB123</PackageIdentifier>"
            "<Client>UpdateAgent</Client>"
            "</Payload></UserData>",
        )
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml])):
            df = w.evtx_to_df_snake("ignored.evtx")

        self.assertEqual(df.iloc[0]["package_identifier"], "KB123")
        self.assertEqual(df.iloc[0]["client"], "UpdateAgent")
        # Original PascalCase key should not survive.
        self.assertNotIn("PackageIdentifier", df.columns)

    def test_event_data_keys_are_also_snake_cased(self):
        xml = event_xml("<EventID>1</EventID>",
                        '<EventData><Data Name="TargetUserName">bob</Data></EventData>')
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml])):
            df = w.evtx_to_df_snake("ignored.evtx")
        self.assertIn("target_user_name", df.columns)
        self.assertEqual(df.iloc[0]["target_user_name"], "bob")


# --------------------------------------------------------------------------- #
# setup_evtx_to_df / system_evtx_to_df (column reindexing)
# --------------------------------------------------------------------------- #

class SetupEvtxToDfTests(unittest.TestCase):
    def test_columns_are_header_plus_setup_header_in_order(self):
        xml = event_xml(
            "<EventID>4</EventID>",
            "<UserData><CbsPackageChangeState>"
            "<PackageIdentifier>KB123</PackageIdentifier>"
            "<Client>UpdateAgent</Client>"
            "</CbsPackageChangeState></UserData>",
        )
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml])):
            df = w.setup_evtx_to_df("ignored.evtx")

        self.assertEqual(list(df.columns), w.header + w.setup_header)
        self.assertEqual(df.iloc[0]["package_identifier"], "KB123")
        self.assertEqual(df.iloc[0]["client"], "UpdateAgent")

    def test_absent_setup_fields_are_filled_na(self):
        xml = event_xml("<EventID>4</EventID>")
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml])):
            df = w.setup_evtx_to_df("ignored.evtx")
        # A setup-only column not present in the record is added and left empty.
        self.assertIn("intended_package_state", df.columns)
        self.assertTrue(w.pd.isna(df.iloc[0]["intended_package_state"]))


class SystemEvtxToDfTests(unittest.TestCase):
    def test_columns_are_header_plus_system_header_in_order(self):
        xml = event_xml(FULL_SYSTEM)
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml])):
            df = w.system_evtx_to_df("ignored.evtx")
        self.assertEqual(list(df.columns), w.header + w.system_header)

    def test_userdata_channel_overrides_system_channel(self):
        # A log-cleared event carries the acted-on log name in UserData/Channel,
        # which collides with and overrides the record's own System/Channel.
        xml = event_xml(
            FULL_SYSTEM,  # System/Channel == "System"
            "<UserData><LogFileCleared>"
            "<Channel>Security</Channel>"
            "<SubjectUserName>admin</SubjectUserName>"
            "</LogFileCleared></UserData>",
        )
        with mock.patch.object(w.evtx, "Evtx", fake_evtx([xml])):
            df = w.evtx_to_df_snake("ignored.evtx")
        # In the snake DataFrame there is a single 'channel' key: UserData wins.
        self.assertEqual(df.iloc[0]["channel"], "Security")
        self.assertEqual(df.iloc[0]["subject_user_name"], "admin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
