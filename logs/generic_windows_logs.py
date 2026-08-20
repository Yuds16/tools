import re
import pandas as pd
import xml.etree.ElementTree as ET
import Evtx.Evtx as evtx

NS = '{http://schemas.microsoft.com/win/2004/08/events/event}'

# Base <System> fields present on every evtx record, regardless of channel or
# event type. Anything beyond this is discovered dynamically per file, since
# EventData/UserData field sets vary by provider/EventID.
header = ['provider_name', 'provider_guid', 'event_id', 'version', 'level', 'task', 'opcode',
          'keywords', 'time_created', 'event_record_id', 'activity_id', 'related_activity_id',
          'process_id', 'thread_id', 'channel', 'computer', 'user_id']


def to_snake_case(name):
    """PascalCase/CamelCase -> snake_case, e.g. 'PackageIdentifier' -> 'package_identifier'."""
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    s2 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1)
    return s2.lower()


def strip_ns(tag):
    return tag.split('}', 1)[-1] if '}' in tag else tag


def parse_system(system_el):
    """Pull the fixed <System> fields present on every evtx record."""
    def find(tag):
        el = system_el.find(f'{NS}{tag}')
        return el.text if el is not None else None

    provider = system_el.find(f'{NS}Provider')
    time_created = system_el.find(f'{NS}TimeCreated')
    correlation = system_el.find(f'{NS}Correlation')
    execution = system_el.find(f'{NS}Execution')
    security = system_el.find(f'{NS}Security')

    return {
        'provider_name': provider.get('Name') if provider is not None else None,
        'provider_guid': provider.get('Guid') if provider is not None else None,
        'event_id': find('EventID'),
        'version': find('Version'),
        'level': find('Level'),
        'task': find('Task'),
        'opcode': find('Opcode'),
        'keywords': find('Keywords'),
        'time_created': time_created.get('SystemTime') if time_created is not None else None,
        'event_record_id': find('EventRecordID'),
        'activity_id': correlation.get('ActivityID') if correlation is not None else None,
        'related_activity_id': correlation.get('RelatedActivityID') if correlation is not None else None,
        'process_id': execution.get('ProcessID') if execution is not None else None,
        'thread_id': execution.get('ThreadID') if execution is not None else None,
        'channel': find('Channel'),
        'computer': find('Computer'),
        'user_id': security.get('UserID') if security is not None else None,
    }


def parse_extra_fields(root):
    """Collects fields from whichever of <EventData> (generic <Data Name=...>
    pairs, used by classic events like Application crashes) or <UserData>
    (a custom-schema element whose children ARE the fields, used by newer
    manifest-based events like Setup/Servicing and log-cleared events) the
    record actually contains, and snake_cases every key so results line up
    with snake_case header lists regardless of which shape was used."""
    data = {}

    event_data_el = root.find(f'{NS}EventData')
    if event_data_el is not None:
        for i, d in enumerate(event_data_el.findall(f'{NS}Data')):
            data[d.get('Name') or f'Data{i}'] = d.text

    user_data_el = root.find(f'{NS}UserData')
    if user_data_el is not None:
        for el in user_data_el.iter():
            if el is user_data_el:
                continue
            if len(el) == 0:  # leaf node, i.e. an actual field
                data[strip_ns(el.tag)] = el.text

    return {to_snake_case(k): v for k, v in data.items()}


def evtx_to_df(fname):
    """One generic parser for any evtx file — no header list required. Base
    <System> fields (`header`) come first and are always present; anything
    beyond that (EventData/UserData) is discovered per-record and unioned
    across the file, so the resulting columns depend entirely on what that
    file's records actually contain.

    NB: if an extra field's snake_cased name collides with a base `header`
    name, the extra field wins (applied after the base System fields via
    dict.update). Seen in this schema so far:
      - application crash events: 'process_id' - the crashing app's PID (hex)
        overwrites the record's own Execution/ProcessID (decimal, who logged
        the event)
      - log-cleared events: 'channel' - the event's own Channel field
        overwrites the record's System/Channel (usually identical in
        practice, but not guaranteed across all EventIDs)
    If you need both values, rename the base `header` entry or post-process
    the raw dicts before they're merged.

    Also: since columns are only discovered from records actually present in
    the file, a field that's always present in your data but happened not to
    fire in this particular batch of records won't appear as a column at all
    (rather than showing up as all-NaN) — a corner case a fixed header list
    doesn't have."""
    rows = []
    with evtx.Evtx(fname) as log:
        for record in log.records():
            root = ET.fromstring(record.xml())
            row = parse_system(root.find(f'{NS}System'))
            row.update(parse_extra_fields(root))
            rows.append(row)

    df = pd.DataFrame(rows)
    extra_cols = sorted(c for c in df.columns if c not in header)
    return df.reindex(columns=header + extra_cols)