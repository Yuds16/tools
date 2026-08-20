import re
import pandas as pd
import xml.etree.ElementTree as ET
import Evtx.Evtx as evtx

NS = '{http://schemas.microsoft.com/win/2004/08/events/event}'

header = ['provider_name', 'provider_guid', 'event_id', 'version', 'level', 'task', 'opcode',
          'keywords', 'time_created', 'event_record_id', 'activity_id', 'related_activity_id',
          'process_id', 'thread_id', 'channel', 'computer', 'user_id']

application_header = ['AppName', 'AppVersion', 'AppTimeStamp', 'ModuleName', 'ModuleVersion',
                       'ModuleTimeStamp', 'ExceptionCode', 'FaultingOffset', 'ProcessId',
                       'ProcessCreationTime', 'AppPath', 'ModulePath', 'IntegratorReportId',
                       'PackageFullName', 'PackageRelativeAppId']

setup_header = ['package_identifier', 'initial_package_state', 'initial_package_state_textized',
                 'intended_package_state', 'intended_package_state_textized', 'client']

system_header = ['subject_user_name', 'subject_domain_name', 'channel', 'backup_path',
                  'client_process_id', 'client_process_start_key']


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


def parse_event_data(root):
    """Pull <EventData><Data Name=...>value</Data></EventData> pairs.
    These vary by EventID even within a single channel, so keys are
    collected dynamically instead of assumed up front."""
    event_data_el = root.find(f'{NS}EventData')
    data = {}
    if event_data_el is not None:
        for i, d in enumerate(event_data_el.findall(f'{NS}Data')):
            name = d.get('Name') or f'Data{i}'
            data[name] = d.text
    return data


def evtx_to_df(fname):
    rows = []
    with evtx.Evtx(fname) as log:
        for record in log.records():
            root = ET.fromstring(record.xml())
            row = parse_system(root.find(f'{NS}System'))
            row.update(parse_event_data(root))
            rows.append(row)
    return pd.DataFrame(rows)


def to_snake_case(name):
    """PascalCase/CamelCase -> snake_case, e.g. 'PackageIdentifier' -> 'package_identifier'."""
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    s2 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1)
    return s2.lower()


def strip_ns(tag):
    return tag.split('}', 1)[-1] if '}' in tag else tag


def parse_user_data(root):
    """Setup/Servicing events, and many Security-auditing events (e.g. log-cleared
    events), use <UserData> instead of <EventData>: a single custom-schema element
    whose children ARE the fields, rather than generic <Data Name=...> pairs.
    Walks those children and returns {leaf_tag: text}."""
    user_data_el = root.find(f'{NS}UserData')
    data = {}
    if user_data_el is not None:
        for el in user_data_el.iter():
            if el is user_data_el:
                continue
            if len(el) == 0:  # leaf node, i.e. an actual field
                data[strip_ns(el.tag)] = el.text
    return data


def evtx_to_df_snake(fname):
    """Like evtx_to_df, but also reads <UserData> (not just <EventData>) and
    snake_cases every extra field name, so results line up with snake_case
    headers like setup_header / system_header."""
    rows = []
    with evtx.Evtx(fname) as log:
        for record in log.records():
            root = ET.fromstring(record.xml())
            row = parse_system(root.find(f'{NS}System'))
            extra = parse_event_data(root)
            extra.update(parse_user_data(root))
            row.update({to_snake_case(k): v for k, v in extra.items()})
            rows.append(row)
    return pd.DataFrame(rows)


def setup_evtx_to_df(fname):
    df = evtx_to_df_snake(fname)
    return df.reindex(columns=header + setup_header)


def system_evtx_to_df(fname):
    df = evtx_to_df_snake(fname)
    # NB: 'channel' appears in both `header` (the record's own System/Channel,
    # e.g. always "System") and `system_header` (a field naming which log was
    # acted on, e.g. for a log-cleared event). Both keys collide as 'channel'
    # in evtx_to_df_snake's row.update(), so the EventData/UserData value wins
    # over the base System one. Rename one of them first if you need both.
    return df.reindex(columns=header + system_header)