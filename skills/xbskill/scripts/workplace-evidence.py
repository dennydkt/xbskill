#!/usr/bin/env python3
"""Read-only exact text lookup with provenance; never adjudicates a claim."""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path


def lookup(raw, query, context=1):
    if not query or not query.strip():
        raise ValueError('E_QUERY_EMPTY')
    if context < 0 or context > 5:
        raise ValueError('E_CONTEXT_RANGE: expected 0..5')
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('records'), list):
        raise ValueError('E_SCHEMA: records array required')
    rows = data['records']
    ids = set()
    required = ('id', 'timestamp', 'author', 'text', 'source', 'locator')
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
            raise ValueError('E_RECORD_FIELDS: nonempty strings required')
        if row['id'] in ids:
            raise ValueError('E_DUPLICATE_ID: ' + row['id'])
        ids.add(row['id'])
        stamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('E_TIMEZONE_REQUIRED: ' + row['id'])
    matches = []
    for index, row in enumerate(rows):
        if query in row['text']:
            matches.append({'record': row, 'input_index': index,
                            'context': rows[max(0, index-context):index+context+1]})
    return {'schema_version': 1, 'input_sha256': hashlib.sha256(raw).hexdigest(),
            'query': query, 'match_mode': 'literal_case_sensitive',
            'record_count': len(rows), 'match_count': len(matches),
            'matches': matches, 'status': 'matched' if matches else 'no_match_in_supplied_records',
            'scope': 'supplied_records_only', 'semantic_verdict': 'not_performed',
            'source_authentication': 'not_performed', 'context_order': 'input_order'}


def main():
    # Keep the JSON transport stable when redirected on Windows.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--query', required=True)
    parser.add_argument('--context', type=int, default=1)
    args = parser.parse_args()
    try:
        result = lookup(Path(args.input).read_bytes(), args.query, args.context)
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
