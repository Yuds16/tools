"""Country-code lookups for IP addresses via the ip-api.com service.

Failures are reported through a small exception hierarchy rather than sentinel
strings, so callers can tell *how* a lookup failed and react accordingly:

* :class:`IPGeoRequestError`  -- the HTTP request itself failed (network down,
  DNS failure, timeout, non-2xx status).
* :class:`IPGeoResponseError` -- a response was received but could not be
  decoded or had an unexpected shape.
* :class:`IPGeoLookupError`   -- the service explicitly reported that a given
  IP could not be resolved (e.g. a reserved or invalid address).

All three derive from :class:`IPGeoError`, so ``except IPGeoError`` catches
everything this module raises.
"""

import json
import urllib.request

DEFAULT_TIMEOUT = 10  # seconds

SINGLE_URL = "http://ip-api.com/json/{ip}"
BATCH_URL = "http://ip-api.com/batch"


class IPGeoError(Exception):
    """Base class for every error raised by this module."""


class IPGeoRequestError(IPGeoError):
    """The HTTP request to the geolocation service failed.

    Covers network/DNS errors, timeouts, and non-2xx HTTP responses. The
    originating exception is preserved via ``__cause__`` (``raise ... from``).
    """


class IPGeoResponseError(IPGeoError):
    """The service reply could not be decoded or had an unexpected shape."""


class IPGeoLookupError(IPGeoError):
    """The service reported that a specific IP address could not be resolved.

    Attributes:
        ip_address: The IP that failed to resolve.
        reason: The message returned by the service, if any.
    """

    def __init__(self, ip_address, reason=None):
        self.ip_address = ip_address
        self.reason = reason
        detail = f": {reason}" if reason else ""
        super().__init__(f"Lookup failed for {ip_address!r}{detail}")


def _read_json(url_or_request, timeout):
    """Perform the request and decode the JSON body.

    Raises:
        IPGeoRequestError: The request could not be completed.
        IPGeoResponseError: The response body was not valid JSON.
    """
    try:
        with urllib.request.urlopen(url_or_request, timeout=timeout) as response:
            raw = response.read()
    except OSError as exc:
        # urllib.error.URLError/HTTPError and socket timeouts all derive from
        # OSError, so this catches every transport-level failure.
        raise IPGeoRequestError(
            f"Request to geolocation service failed: {exc}"
        ) from exc

    try:
        return json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise IPGeoResponseError(
            f"Could not decode geolocation response: {exc}"
        ) from exc


def get_country_code_from_ip(ip_address, timeout=DEFAULT_TIMEOUT):
    """Look up the ISO country code for a single IP address.

    Args:
        ip_address: The IP address to geolocate, as a string.
        timeout: Socket timeout for the request, in seconds.

    Returns:
        The two-letter country code (e.g. ``"US"``, ``"DE"``).

    Raises:
        IPGeoRequestError: The request to the service failed.
        IPGeoResponseError: The response could not be decoded or lacked a
            country code despite a successful status.
        IPGeoLookupError: The service reported that the IP could not be
            resolved (e.g. a reserved or invalid address).
    """
    data = _read_json(SINGLE_URL.format(ip=ip_address), timeout)

    if not isinstance(data, dict):
        raise IPGeoResponseError(
            f"Expected a JSON object, got {type(data).__name__}"
        )
    if data.get("status") == "fail":
        raise IPGeoLookupError(ip_address, data.get("message"))

    country_code = data.get("countryCode")
    if not country_code:
        raise IPGeoResponseError(
            f"Response for {ip_address!r} contained no country code"
        )
    return country_code


def batch_get_country_codes_from_ips(ip_addresses, timeout=DEFAULT_TIMEOUT):
    """Look up ISO country codes for multiple IP addresses in one request.

    A single POST is sent to the batch endpoint. Transport- and response-level
    problems raise (the whole call failed), while a lookup that fails for an
    individual IP is reported as ``None`` in that position so partial results
    are preserved.

    Args:
        ip_addresses: An iterable of IP address strings to geolocate.
        timeout: Socket timeout for the request, in seconds.

    Returns:
        A list aligned with ``ip_addresses`` where each entry is the country
        code on success or ``None`` if that IP could not be resolved.

    Raises:
        IPGeoRequestError: The request to the service failed.
        IPGeoResponseError: The response could not be decoded, was not a JSON
            array, or did not have one result per input IP.
    """
    ip_addresses = list(ip_addresses)
    payload = json.dumps(ip_addresses).encode("utf-8")
    request = urllib.request.Request(
        BATCH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    data = _read_json(request, timeout)

    if not isinstance(data, list):
        raise IPGeoResponseError(
            f"Expected a JSON array, got {type(data).__name__}"
        )
    if len(data) != len(ip_addresses):
        raise IPGeoResponseError(
            f"Expected {len(ip_addresses)} result(s), got {len(data)}"
        )

    results = []
    for item in data:
        if isinstance(item, dict) and item.get("status") != "fail":
            results.append(item.get("countryCode") or None)
        else:
            results.append(None)
    return results
