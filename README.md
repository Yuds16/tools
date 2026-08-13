# tools

A collection of small, self-contained utilities. Each tool lives in its own
top-level directory with its own README, dependencies, and tests.

## Tools

| Tool | Description |
|---|---|
| [`ip_geo`](ip_geo/) | Look up the country of origin for one or many IP addresses via the free [ip-api.com](https://ip-api.com) service. Standard-library only. |
| [`windows_logs`](windows_logs/) | Parse Windows Event Log (`.evtx`) files into pandas DataFrames, with channel-specific views (Setup, System). |

## Repository layout

```
tools/
├── README.md          # this file
├── ip_geo/            # IP geolocation utility
│   ├── README.md      # tool-specific docs
│   ├── ip_geo.py      # implementation
│   ├── requirements.txt
│   └── tests/         # unittest suite
└── windows_logs/      # Windows Event Log (.evtx) parser
    ├── README.md
    ├── windows_logs.py
    ├── requirements.txt
    └── tests/
```

## Getting started

Each tool is independent — see its own README for usage details. In general:

```bash
# From the repository root, run a tool's tests:
python3 -m unittest discover -s ip_geo/tests -v
```

Any third-party dependencies are listed in the tool's own `requirements.txt`
(`ip_geo` currently has none — it uses only the Python standard library).

## Adding a new tool

1. Create a new top-level directory named after the tool.
2. Add the implementation, a `requirements.txt`, and a `tests/` suite.
3. Add a `README.md` for the tool.
4. Add a row to the **Tools** table above.
