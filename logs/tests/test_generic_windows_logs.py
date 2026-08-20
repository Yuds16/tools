"""Unit tests for generic_windows_logs.py.

Real .evtx files are a binary format, so the ``Evtx.Evtx`` reader is mocked:
each fake record returns a canned XML string, exercising the real XML parsing
and DataFrame assembly without needing a binary fixture. The pure helpers are
tested directly against ElementTree input.

Run from the repository root with the project virtualenv:

    .venv/bin/python -m unittest discover -s windows_logs/tests -v
"""

import os
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

# Make ``generic_windows_logs`` importable regardless of the cwd.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import generic_windows_logs as g  # noqa: E402

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
    """Return a callable standing in for ``Evtx.Evtx`` yielding the given records.

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
        self.assertEqual(g.to_snake_case("PackageIdentifier"), "package_identifier")
        self.assertEqual(g.to_snake_case("AppName"), "app_name")

    def test_trailing_acronym_word(self):
        self.assertEqual(g.to_snake_case("ProcessId"), "process_id")

    def test_all_caps_stays_together(self):
        self.assertEqual(g.to_snake_case("ID"), "id")

    def test_leading_acronym(self):
        self.assertEqual(g.to_snake_case("HTTPServer"), "http_server")

    def test_already_lower(self):
        self.assertEqual(g.to_snake_case("client"), "client")

    def test_trailing_digits(self):
        self.assertEqual(g.to_snake_case("Data0"), "data0")


# --------------------------------------------------------------------------- #
# strip_ns
# --------------------------------------------------------------------------- #

class StripNsTests(unittest.TestCase):
    def test_removes_namespace(self):
        self.assertEqual(g.strip_ns("{" + EVENTS_NS + "}EventID"), "EventID")

    def test_no_namespace_returned_unchanged(self):
        self.assertEqual(g.strip_ns("EventID"), "EventID")

    def test_empty_braces(self):
        self.assertEqual(g.strip_ns("{}Local"), "Local")


# --------------------------------------------------------------------------- #
# parse_system
# --------------------------------------------------------------------------- #

class ParseSystemTests(unittest.TestCase):
    def _system_of(self, system_inner):
        return ET.fromstring(event_xml(system_inner)).find(f"{g.NS}System")

    def test_full_record_maps_every_field(self):
        result = g.parse_system(self._system_of(FULL_SYSTEM))
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
        result = g.parse_system(self._system_of("<EventID>1</EventID><Channel>System</Channel>"))
        self.assertEqual(result["event_id"], "1")
        for missing in ("provider_name", "provider_guid", "time_created",
                        "activity_id", "related_activity_id", "process_id",
                        "thread_id", "user_id", "computer", "level"):
            self.assertIsNone(result[missing], f"expected {missing} to be None")

    def test_keys_match_header(self):
        result = g.parse_system(self._system_of(FULL_SYSTEM))
        self.assertEqual(set(result.keys()), set(g.header))


# --------------------------------------------------------------------------- #
# parse_extra_fields  (the merged EventData + UserData parser)
# --------------------------------------------------------------------------- #

class ParseExtraFieldsTests(unittest.TestCase):
    def _root(self, extra_inner):
        return ET.fromstring(event_xml("<EventID>1</EventID>", extra_inner))

    def test_event_data_named_pairs_snake_cased(self):
        root = self._root(
            "<EventData>"
            '<Data Name="TargetUserName">alice</Data>'
            '<Data Name="LogonType">3</Data>'
            "</EventData>"
        )
        self.assertEqual(g.parse_extra_fields(root),
                         {"target_user_name": "alice", "logon_type": "3"})

    def test_event_data_unnamed_uses_positional_key(self):
        root = self._root("<EventData><Data>first</Data><Data>second</Data></EventData>")
        self.assertEqual(g.parse_extra_fields(root), {"data0": "first", "data1": "second"})

    def test_user_data_leaf_fields_snake_cased_and_containers_skipped(self):
        root = self._root(
            "<UserData><CbsPackageChangeState>"
            "<PackageIdentifier>KB123</PackageIdentifier>"
            "<Client>UpdateAgent</Client>"
            "</CbsPackageChangeState></UserData>"
        )
        result = g.parse_extra_fields(root)
        self.assertEqual(result, {"package_identifier": "KB123", "client": "UpdateAgent"})
        self.assertNotIn("cbs_package_change_state", result)

    def test_user_data_strips_leaf_namespace(self):
        root = self._root(
            '<UserData><Payload xmlns="myschema"><Channel>Security</Channel></Payload></UserData>'
        )
        self.assertEqual(g.parse_extra_fields(root), {"channel": "Security"})

    def test_merges_event_data_and_user_data(self):
        root = self._root(
            '<EventData><Data Name="Foo">1</Data></EventData>'
            "<UserData><P><Bar>2</Bar></P></UserData>"
        )
        self.assertEqual(g.parse_extra_fields(root), {"foo": "1", "bar": "2"})

    def test_user_data_overwrites_event_data_on_key_clash(self):
        # EventData is collected first, UserData second, so UserData wins.
        root = self._root(
            '<EventData><Data Name="Channel">FromEventData</Data></EventData>'
            "<UserData><P><Channel>FromUserData</Channel></P></UserData>"
        )
        self.assertEqual(g.parse_extra_fields(root), {"channel": "FromUserData"})

    def test_no_extra_sections_returns_empty(self):
        self.assertEqual(g.parse_extra_fields(self._root("")), {})

    def test_empty_data_value_maps_to_none(self):
        root = self._root('<EventData><Data Name="Foo"></Data></EventData>')
        self.assertEqual(g.parse_extra_fields(root), {"foo": None})


# --------------------------------------------------------------------------- #
# evtx_to_df
# --------------------------------------------------------------------------- #

class EvtxToDfTests(unittest.TestCase):
    def test_base_header_always_present_and_first(self):
        xml = event_xml(FULL_SYSTEM)
        with mock.patch.object(g.evtx, "Evtx", fake_evtx([xml])):
            df = g.evtx_to_df("ignored.evtx")
        self.assertEqual(list(df.columns), g.header)
        self.assertEqual(df.iloc[0]["event_id"], "104")

    def test_extra_columns_appended_sorted_after_header(self):
        xml = event_xml(
            "<EventID>1</EventID>",
            "<EventData>"
            '<Data Name="Zeta">z</Data>'
            '<Data Name="Alpha">a</Data>'
            "</EventData>",
        )
        with mock.patch.object(g.evtx, "Evtx", fake_evtx([xml])):
            df = g.evtx_to_df("ignored.evtx")
        self.assertEqual(list(df.columns), g.header + ["alpha", "zeta"])
        self.assertEqual(df.iloc[0]["alpha"], "a")
        self.assertEqual(df.iloc[0]["zeta"], "z")

    def test_columns_are_unioned_across_records(self):
        rec1 = event_xml("<EventID>1</EventID>", '<EventData><Data Name="Foo">bar</Data></EventData>')
        rec2 = event_xml("<EventID>2</EventID>", '<EventData><Data Name="Baz">qux</Data></EventData>')
        with mock.patch.object(g.evtx, "Evtx", fake_evtx([rec1, rec2])):
            df = g.evtx_to_df("ignored.evtx")

        self.assertEqual(list(df.columns), g.header + ["baz", "foo"])
        self.assertEqual(df.iloc[0]["foo"], "bar")
        self.assertEqual(df.iloc[1]["baz"], "qux")
        # A field absent from a given record shows up as NaN there.
        self.assertTrue(g.pd.isna(df.iloc[0]["baz"]))
        self.assertTrue(g.pd.isna(df.iloc[1]["foo"]))

    def test_extra_field_overwrites_colliding_header_field(self):
        # Application-crash style: EventData ProcessId (hex, the crashing app)
        # overwrites the record's Execution/ProcessID (decimal, the logger).
        xml = event_xml(
            FULL_SYSTEM,  # Execution ProcessID == "4"
            '<EventData><Data Name="ProcessId">0x1a4</Data></EventData>',
        )
        with mock.patch.object(g.evtx, "Evtx", fake_evtx([xml])):
            df = g.evtx_to_df("ignored.evtx")
        # 'process_id' stays a header column (not duplicated), but takes the
        # EventData value.
        self.assertEqual(list(df.columns).count("process_id"), 1)
        self.assertEqual(df.iloc[0]["process_id"], "0x1a4")

    def test_channel_collision_extra_wins(self):
        xml = event_xml(
            FULL_SYSTEM,  # System/Channel == "System"
            "<UserData><LogFileCleared><Channel>Security</Channel></LogFileCleared></UserData>",
        )
        with mock.patch.object(g.evtx, "Evtx", fake_evtx([xml])):
            df = g.evtx_to_df("ignored.evtx")
        self.assertEqual(list(df.columns).count("channel"), 1)
        self.assertEqual(df.iloc[0]["channel"], "Security")

    def test_multiple_records_row_count(self):
        xml = event_xml(FULL_SYSTEM)
        with mock.patch.object(g.evtx, "Evtx", fake_evtx([xml, xml, xml])):
            df = g.evtx_to_df("ignored.evtx")
        self.assertEqual(len(df), 3)

    def test_empty_log_returns_header_only_empty_frame(self):
        with mock.patch.object(g.evtx, "Evtx", fake_evtx([])):
            df = g.evtx_to_df("ignored.evtx")
        self.assertEqual(len(df), 0)
        self.assertEqual(list(df.columns), g.header)


if __name__ == "__main__":
    unittest.main(verbosity=2)
