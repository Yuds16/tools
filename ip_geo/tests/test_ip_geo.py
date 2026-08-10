"""Unit tests for ip_geo.py.

The module under test performs real HTTP requests against ip-api.com via
``urllib.request.urlopen``. These tests never touch the network: every call to
``urlopen`` is patched so we can assert on the URL/request that would be sent
and control the response (or error) the code sees.

Run from the repository with either::

    python3 -m unittest discover -s ip_geo/tests
    python3 ip_geo/tests/test_ip_geo.py
"""

import json
import os
import sys
import unittest
from unittest import mock

# Make ``ip_geo`` importable regardless of the current working directory.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ip_geo  # noqa: E402


def make_response(payload):
    """Build a fake object that mimics the ``urlopen`` return value.

    ``urlopen`` is used as a context manager whose result exposes ``.read()``
    returning encoded bytes, so the fake must support both protocols.
    """
    body = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode()
    response = mock.MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class GetCountryCodeFromIpTests(unittest.TestCase):
    """Tests for the single-IP lookup ``get_country_code_from_ip``."""

    def test_returns_country_code_on_success(self):
        response = make_response({"status": "success", "countryCode": "US"})
        with mock.patch("urllib.request.urlopen", return_value=response):
            self.assertEqual(ip_geo.get_country_code_from_ip("8.8.8.8"), "US")

    def test_builds_expected_url(self):
        response = make_response({"countryCode": "DE"})
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            ip_geo.get_country_code_from_ip("1.2.3.4")
        self.assertEqual(urlopen.call_args.args[0], "http://ip-api.com/json/1.2.3.4")

    def test_passes_timeout_to_urlopen(self):
        response = make_response({"countryCode": "DE"})
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            ip_geo.get_country_code_from_ip("1.2.3.4", timeout=3)
        self.assertEqual(urlopen.call_args.kwargs.get("timeout"), 3)

    def test_raises_lookup_error_when_service_reports_fail(self):
        response = make_response({"status": "fail", "message": "reserved range"})
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ip_geo.IPGeoLookupError) as ctx:
                ip_geo.get_country_code_from_ip("127.0.0.1")
        self.assertEqual(ctx.exception.ip_address, "127.0.0.1")
        self.assertEqual(ctx.exception.reason, "reserved range")

    def test_raises_response_error_when_country_code_missing(self):
        # Successful status but no country code is an unexpected response shape.
        response = make_response({"status": "success"})
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ip_geo.IPGeoResponseError):
                ip_geo.get_country_code_from_ip("8.8.8.8")

    def test_raises_response_error_when_not_a_json_object(self):
        response = make_response(["unexpected", "list"])
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ip_geo.IPGeoResponseError):
                ip_geo.get_country_code_from_ip("8.8.8.8")

    def test_raises_request_error_on_network_exception(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("no network")):
            with self.assertRaises(ip_geo.IPGeoRequestError):
                ip_geo.get_country_code_from_ip("8.8.8.8")

    def test_raises_response_error_on_invalid_json(self):
        response = make_response(b"not valid json")
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ip_geo.IPGeoResponseError):
                ip_geo.get_country_code_from_ip("8.8.8.8")

    def test_request_error_preserves_original_cause(self):
        original = OSError("connection refused")
        with mock.patch("urllib.request.urlopen", side_effect=original):
            with self.assertRaises(ip_geo.IPGeoRequestError) as ctx:
                ip_geo.get_country_code_from_ip("8.8.8.8")
        self.assertIs(ctx.exception.__cause__, original)


class BatchGetCountryCodesFromIpsTests(unittest.TestCase):
    """Tests for the batch lookup ``batch_get_country_codes_from_ips``."""

    def test_returns_codes_in_order(self):
        response = make_response([
            {"countryCode": "US"},
            {"countryCode": "DE"},
            {"countryCode": "JP"},
        ])
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = ip_geo.batch_get_country_codes_from_ips(["8.8.8.8", "1.1.1.1", "9.9.9.9"])
        self.assertEqual(result, ["US", "DE", "JP"])

    def test_failed_item_becomes_none(self):
        response = make_response([
            {"status": "success", "countryCode": "US"},
            {"status": "fail", "message": "invalid query"},
        ])
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = ip_geo.batch_get_country_codes_from_ips(["8.8.8.8", "bogus"])
        self.assertEqual(result, ["US", None])

    def test_item_missing_country_code_becomes_none(self):
        response = make_response([{"status": "success", "countryCode": "US"}, {"status": "success"}])
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = ip_geo.batch_get_country_codes_from_ips(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(result, ["US", None])

    def test_posts_json_payload_to_batch_endpoint(self):
        response = make_response([{"countryCode": "US"}, {"countryCode": "DE"}])
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            ip_geo.batch_get_country_codes_from_ips(["8.8.8.8", "1.1.1.1"])

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://ip-api.com/batch")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        # Payload must be valid JSON encoding exactly the requested IPs.
        self.assertEqual(json.loads(request.data.decode()), ["8.8.8.8", "1.1.1.1"])

    def test_payload_escapes_special_characters(self):
        # json.dumps must be used so odd input can't produce malformed JSON.
        response = make_response([{"countryCode": "US"}])
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            ip_geo.batch_get_country_codes_from_ips(['a"b'])
        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data.decode()), ['a"b'])

    def test_raises_request_error_on_network_exception(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            with self.assertRaises(ip_geo.IPGeoRequestError):
                ip_geo.batch_get_country_codes_from_ips(["8.8.8.8", "1.1.1.1"])

    def test_raises_response_error_on_invalid_json(self):
        response = make_response(b"<html>gateway timeout</html>")
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ip_geo.IPGeoResponseError):
                ip_geo.batch_get_country_codes_from_ips(["8.8.8.8", "1.1.1.1"])

    def test_raises_response_error_when_not_a_list(self):
        response = make_response({"unexpected": "object"})
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ip_geo.IPGeoResponseError):
                ip_geo.batch_get_country_codes_from_ips(["8.8.8.8"])

    def test_raises_response_error_on_length_mismatch(self):
        response = make_response([{"countryCode": "US"}])  # only one result for two IPs
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ip_geo.IPGeoResponseError):
                ip_geo.batch_get_country_codes_from_ips(["8.8.8.8", "1.1.1.1"])

    def test_single_ip_batch(self):
        response = make_response([{"countryCode": "GB"}])
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = ip_geo.batch_get_country_codes_from_ips(["212.58.244.22"])
        self.assertEqual(result, ["GB"])

    def test_empty_input_returns_empty_list(self):
        response = make_response([])
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = ip_geo.batch_get_country_codes_from_ips([])
        self.assertEqual(result, [])
        # Empty input must still serialize to a valid JSON array.
        self.assertEqual(urlopen.call_args.args[0].data.decode(), "[]")

    def test_accepts_non_list_iterable(self):
        response = make_response([{"countryCode": "US"}, {"countryCode": "DE"}])
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = ip_geo.batch_get_country_codes_from_ips(iter(["8.8.8.8", "1.1.1.1"]))
        self.assertEqual(result, ["US", "DE"])
        self.assertEqual(json.loads(urlopen.call_args.args[0].data.decode()), ["8.8.8.8", "1.1.1.1"])


class ExceptionHierarchyTests(unittest.TestCase):
    """The specific errors should all be catchable as IPGeoError."""

    def test_all_errors_derive_from_base(self):
        for cls in (ip_geo.IPGeoRequestError, ip_geo.IPGeoResponseError, ip_geo.IPGeoLookupError):
            self.assertTrue(issubclass(cls, ip_geo.IPGeoError))


if __name__ == "__main__":
    unittest.main(verbosity=2)
