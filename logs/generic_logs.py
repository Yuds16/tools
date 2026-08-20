import re
import pandas as pd

# Column delimiter used by these text logs. Every line (header and data alike)
# is a run of pipe-separated, whitespace-padded fields:
#
#   DATE       TIME             |LEVEL   |FACILITY  | ... | MESSAGE
#   2025-... 00:00:00.000Z      |Debug   |app       | ... | Runtime is loaded
#
DELIM = '|'


def normalize_column(name):
    """Plain-text header token -> snake_case identifier.

    Collapses any run of non-alphanumeric characters to a single underscore and
    lowercases, so 'FILE_NAME(LINE)' -> 'file_name_line', 'PID' -> 'pid'. Unlike
    the evtx modules' ``to_snake_case`` (which splits PascalCase word
    boundaries), these headers are already word-delimited by spaces/punctuation,
    so we only need to sanitize, not resegment.
    """
    return re.sub(r'[^0-9a-zA-Z]+', '_', name).strip('_').lower()


def parse_header(line):
    """Turn the header line into (columns, token_counts).

    Splitting on ``DELIM`` yields one segment per pipe-delimited field. A segment
    may itself hold several space-separated names — the leading 'DATE TIME'
    segment is really two logical columns sharing one field — so each segment
    contributes ``len(segment.split())`` columns. ``token_counts`` records how
    many columns came from each segment, so ``parse_line`` can split the matching
    data segment the same way.

    Returns:
        columns: flat list of snake_cased column names.
        token_counts: per-segment column counts, aligned with the segments of a
            data line split on ``DELIM``.
    """
    columns = []
    token_counts = []
    for segment in line.split(DELIM):
        words = segment.split()
        token_counts.append(len(words))
        columns.extend(normalize_column(w) for w in words)
    return columns, token_counts


def parse_line(line, token_counts):
    """Split one data line into values matching ``parse_header``'s columns.

    The line is split on ``DELIM`` into the same number of segments as the
    header. A segment mapped to a single column is taken whole (stripped); a
    segment mapped to N columns (e.g. the 'DATE TIME' field) is split into N
    whitespace-separated values. Short segments are padded with ``None`` so the
    value count always matches the column count.

    The final field (typically MESSAGE) is kept intact even if it contains a
    literal ``|``: the split is capped at the header's segment count, so any
    trailing pipes stay part of the message.
    """
    segments = line.split(DELIM, len(token_counts) - 1)
    values = []
    for i, count in enumerate(token_counts):
        segment = segments[i] if i < len(segments) else ''
        if count <= 1:
            values.append(segment.strip() or None)
        else:
            parts = segment.split(None, count - 1)
            parts += [None] * (count - len(parts))
            values.extend(p.strip() if isinstance(p, str) else p for p in parts)
    return values


def log_to_df(fname):
    """Parse a pipe-delimited text log into a pandas DataFrame.

    The first non-blank line is the header and defines the columns; every
    subsequent non-blank line is one row. Column names are discovered from the
    header (snake_cased), so no fixed layout is assumed — the parser adapts to
    whatever fields the file declares.

    Notes:
      - Blank lines are skipped (these logs contain occasional empty lines).
      - The 'DATE TIME' header field is expanded into separate ``date`` and
        ``time`` columns; the corresponding value is split on its first space.
      - Everything is text: values are taken verbatim as stripped strings (or
        ``None`` when empty); no type coercion or timestamp parsing is applied.
      - An empty value (or a missing trailing field) becomes ``None``.
    """
    with open(fname, 'r', encoding='utf-8') as f:
        lines = [ln.rstrip('\n') for ln in f]

    rows = []
    columns = None
    token_counts = None
    for line in lines:
        if not line.strip():
            continue
        if columns is None:
            columns, token_counts = parse_header(line)
            continue
        rows.append(parse_line(line, token_counts))

    if columns is None:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=columns)
