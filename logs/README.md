# windows_logs

Parse Windows Event Log (`.evtx`) files into [pandas](https://pandas.pydata.org)
DataFrames for analysis.

Every event record's fixed `<System>` metadata is flattened into a consistent
set of columns (`header`), and the per-event payload (`<EventData>` and/or
`<UserData>`) is expanded into additional columns.

This tool ships two modules:

| Module | Use it when |
|---|---|
| [`generic_windows_logs.py`](generic_windows_logs.py) | You want **one parser for any `.evtx` file**. Payload columns are discovered per file and unioned across records — no channel knowledge required. Start here. |
| [`windows_logs.py`](windows_logs.py) | You want **channel-shaped views** with a fixed, predictable column set (Setup, System), reindexed into a stable order. |

## Requirements

- Python 3.8+
- [`pandas`](https://pandas.pydata.org)
- [`python-evtx`](https://github.com/williballenthin/python-evtx) (imported as `Evtx`)

Install the dependencies with:

```bash
pip install -r requirements.txt
```

## generic_windows_logs.py

A single generic parser. Base `<System>` fields come first and are always
present; any `EventData`/`UserData` fields are discovered per record, snake-cased,
sorted, and unioned across the whole file — so the columns depend entirely on
what that file's records actually contain.

```python
import generic_windows_logs as gwl

df = gwl.evtx_to_df("Security.evtx")
# columns == header + sorted(extra fields found in the file)
```

### API

| Function | Description |
|---|---|
| `evtx_to_df(fname)` | Parse an `.evtx` file into a DataFrame: `header` columns first, then every discovered payload column (snake-cased, sorted, unioned across records). |
| `parse_system(system_el)` | Map the fixed `<System>` sub-elements/attributes to the `header` fields. Missing elements yield `None`. |
| `parse_extra_fields(root)` | Collect fields from `<EventData>` and/or `<UserData>` and snake_case every key. |
| `to_snake_case(name)` | `PascalCase`/`CamelCase` → `snake_case` (e.g. `PackageIdentifier` → `package_identifier`). |
| `strip_ns(tag)` | Remove an XML `{namespace}` prefix from a tag. |

## windows_logs.py

Channel-aware variant. It exposes lower-level parsers plus builders that
reindex the result into a fixed column layout per channel.

```python
import windows_logs as wl

# Generic: System fields + raw EventData columns (payload names left as-is).
df = wl.evtx_to_df("System.evtx")

# Also reads UserData and snake_cases every payload column name.
df = wl.evtx_to_df_snake("System.evtx")

# Channel-shaped views: System fields + a fixed set of channel columns,
# reindexed into a stable order (missing fields become NaN).
setup_df = wl.setup_evtx_to_df("Setup.evtx")
system_df = wl.system_evtx_to_df("System.evtx")
```

### API

| Function | Description |
|---|---|
| `evtx_to_df(fname)` | One row per record: `<System>` fields plus raw `<EventData>` `Name`→value pairs (payload names kept as-is, e.g. `TargetUserName`). |
| `evtx_to_df_snake(fname)` | Like `evtx_to_df`, but also reads `<UserData>` and snake_cases every payload column name. |
| `setup_evtx_to_df(fname)` | `evtx_to_df_snake` reindexed to `header + setup_header` (Setup/Servicing events). |
| `system_evtx_to_df(fname)` | `evtx_to_df_snake` reindexed to `header + system_header` (e.g. log-cleared events). |
| `parse_system` / `parse_event_data` / `parse_user_data` | Lower-level parsers for `<System>`, `<EventData>`, and `<UserData>` respectively. |
| `to_snake_case` / `strip_ns` | Shared string/tag helpers. |

### Column layouts

`header` holds the `<System>` columns shared by every record. `application_header`,
`setup_header`, and `system_header` list the per-channel payload columns.

## Testing

Tests mock the binary `.evtx` reader but use real pandas and XML parsing, so
they run offline without any `.evtx` fixtures:

```bash
python3 -m unittest discover -s windows_logs/tests -v
```

## Notes and limitations

- **Colliding field names:** when a payload field's snake-cased name matches a
  base `header` name, the payload value wins (it is merged in after the
  `<System>` fields). Common cases:
  - application-crash events — `process_id` (the crashing app's PID, hex)
    overwrites the record's `Execution/ProcessID` (the logger's PID, decimal);
  - log-cleared events — `channel` (the acted-on log) overwrites the record's
    `System/Channel`.

  In `generic_windows_logs.evtx_to_df` this stays a single column with the
  payload value. In `windows_logs.system_evtx_to_df`, `system_header` also
  lists `channel`, so the reindex produces two `channel` columns. Rename a
  field first if you need both values.
- **Discovered vs. fixed columns:** `generic_windows_logs` only shows columns
  for fields that actually appear in the file's records, so a field that simply
  didn't fire in a given batch won't appear at all (rather than as all-NaN).
  The fixed `windows_logs` channel builders always include their full column set.
- **Everything is text:** values are taken verbatim from the XML as strings
  (or `None`); no type coercion or timestamp parsing is applied.
- **Memory:** the whole log is materialized into a single DataFrame in memory,
  so very large `.evtx` files are read in full.
