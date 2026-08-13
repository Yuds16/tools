# windows_logs

Parse Windows Event Log (`.evtx`) files into [pandas](https://pandas.pydata.org)
DataFrames for analysis.

Each event record's fixed `<System>` metadata is flattened into a consistent
set of columns, and the per-event payload (`<EventData>` and/or `<UserData>`)
is expanded into additional columns. Helpers are provided to shape the result
for specific channels (Setup, System).

## Requirements

- Python 3.8+
- [`pandas`](https://pandas.pydata.org)
- [`python-evtx`](https://github.com/williballenthin/python-evtx) (imported as `Evtx`)

Install the dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

```python
import windows_logs as wl

# Generic: one row per record, System fields + raw EventData columns.
df = wl.evtx_to_df("Security.evtx")

# Same, but also reads UserData and snake_cases every payload column name.
df = wl.evtx_to_df_snake("System.evtx")

# Channel-shaped views: System fields + a fixed set of channel columns,
# reindexed into a stable column order (missing fields become NaN).
setup_df = wl.setup_evtx_to_df("Setup.evtx")
system_df = wl.system_evtx_to_df("System.evtx")
```

## API

### DataFrame builders

| Function | Description |
|---|---|
| `evtx_to_df(fname)` | One row per record: parsed `<System>` fields plus raw `<EventData>` `Name`→value pairs. Payload column names are left as-is (e.g. `TargetUserName`). |
| `evtx_to_df_snake(fname)` | Like `evtx_to_df`, but also reads `<UserData>` and converts every payload column name to `snake_case` so it lines up with the fixed header lists. |
| `setup_evtx_to_df(fname)` | `evtx_to_df_snake` reindexed to `header + setup_header` (Setup/Servicing events). |
| `system_evtx_to_df(fname)` | `evtx_to_df_snake` reindexed to `header + system_header` (e.g. log-cleared events). |

### Parsing helpers

| Function | Description |
|---|---|
| `parse_system(system_el)` | Map the fixed `<System>` sub-elements/attributes to the `header` fields. Missing elements yield `None`. |
| `parse_event_data(root)` | Collect `<EventData><Data Name=...>` pairs; unnamed `<Data>` become `Data0`, `Data1`, … |
| `parse_user_data(root)` | Walk `<UserData>` and return `{leaf_tag: text}` for leaf elements (namespaces stripped, containers skipped). |
| `to_snake_case(name)` | `PascalCase`/`CamelCase` → `snake_case` (e.g. `PackageIdentifier` → `package_identifier`). |
| `strip_ns(tag)` | Remove an XML `{namespace}` prefix from a tag. |

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

- **`channel` collision:** in the snake-cased frame, a payload field that maps
  to `channel` (e.g. the acted-on log name in a log-cleared event's
  `<UserData>`) overwrites the record's own `System/Channel`, because both use
  the key `channel`. `system_header` also repeats `channel`, so
  `system_evtx_to_df` produces two `channel` columns. Rename one field first if
  you need both values.
- **Everything is text:** values are taken verbatim from the XML as strings
  (or `None`); no type coercion or timestamp parsing is applied.
- **Memory:** the whole log is materialized into a single DataFrame in memory,
  so very large `.evtx` files are read in full.
