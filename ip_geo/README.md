# ip_geo

Look up the country of origin for IP addresses using the free
[ip-api.com](https://ip-api.com) geolocation service.

The tool provides two functions: a single-IP lookup and a batch lookup that
resolves many IPs in one request. Both depend only on the Python standard
library — there are no third-party dependencies.

## Requirements

- Python 3.6+
- Network access to `http://ip-api.com`

`requirements.txt` is intentionally empty; the module uses only `json` and
`urllib` from the standard library.

## Usage

```python
from ip_geo import (
    get_country_code_from_ip,
    batch_get_country_codes_from_ips,
    IPGeoError,
    IPGeoLookupError,
)

# Single IP — returns the code, or raises on failure.
try:
    code = get_country_code_from_ip("8.8.8.8")   # -> "US"
except IPGeoLookupError as exc:
    print(f"could not resolve {exc.ip_address}: {exc.reason}")
except IPGeoError as exc:
    print(f"lookup failed: {exc}")

# Multiple IPs in one request; order is preserved and unresolved IPs are None.
batch_get_country_codes_from_ips(["8.8.8.8", "1.1.1.1", "10.0.0.1"])
# -> ["US", "AU", None]
```

## Error handling

Failures are reported through an exception hierarchy instead of sentinel
strings, so callers can tell *how* a lookup failed:

| Exception | Meaning |
|---|---|
| `IPGeoError` | Base class — `except IPGeoError` catches everything below. |
| `IPGeoRequestError` | The HTTP request failed (network/DNS error, timeout, non-2xx status). The original error is preserved on `__cause__`. |
| `IPGeoResponseError` | A reply was received but could not be decoded or had an unexpected shape. |
| `IPGeoLookupError` | The service reported that a specific IP could not be resolved (e.g. a reserved/invalid address). Exposes `.ip_address` and `.reason`. |

## API

### `get_country_code_from_ip(ip_address, timeout=10)`

Look up the ISO country code for a single IP address.

| | |
|---|---|
| **Args** | `ip_address` (str) — the IP to geolocate; `timeout` (float) — socket timeout in seconds |
| **Returns** | The two-letter country code (e.g. `"US"`, `"DE"`) |
| **Raises** | `IPGeoRequestError`, `IPGeoResponseError`, `IPGeoLookupError` |

Backed by the `GET http://ip-api.com/json/{ip}` endpoint.

### `batch_get_country_codes_from_ips(ip_addresses, timeout=10)`

Look up ISO country codes for multiple IP addresses in a single request.

| | |
|---|---|
| **Args** | `ip_addresses` (iterable of str) — the IPs to geolocate; `timeout` (float) — socket timeout in seconds |
| **Returns** | A list aligned with the input: the country code per IP, or `None` where that IP could not be resolved |
| **Raises** | `IPGeoRequestError`, `IPGeoResponseError` |

Transport- and response-level problems raise (the whole call failed); a lookup
that fails for one IP is reported as `None` so partial results are preserved.
Backed by the `POST http://ip-api.com/batch` endpoint.

## Testing

Tests use the standard-library `unittest` framework and mock all network
calls, so they run offline and without extra dependencies:

```bash
python3 -m unittest discover -s ip_geo/tests -v
```

## Notes and limitations

- **Rate limits:** ip-api.com's free tier is limited (as of writing, ~45
  requests/minute for the single endpoint and up to 100 IPs per batch call).
  Sustained heavy use may be throttled — prefer `batch_get_country_codes_from_ips`
  when resolving many IPs.
- **HTTP, not HTTPS:** the free endpoint is plain HTTP; requests and responses
  are not encrypted.
- **Timeouts:** both functions accept a `timeout` (default 10s) and surface a
  timeout as `IPGeoRequestError`.
