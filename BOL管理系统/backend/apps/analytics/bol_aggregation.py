"""Shared aggregation rules for line-level Budget and Achievable BOL records."""

from bol_platform.plant_utils import normalize_plant


def aggregate_bol_rows(records, bol_field, group_fields):
    """Sum BOL rows at the requested analytical grain.

    Production-line rows are additive, including multiple rows for the same line.
    Null, non-numeric, and non-positive BOL values are treated as missing data.
    Plant dimensions are normalized before grouping. Each result includes the
    normalized plants and number of contributing source rows for traceability.
    """
    groups = {}
    for record in records:
        dimensions = {}
        for field in group_fields:
            value = record.get(field)
            if field == 'plant':
                value = normalize_plant(value)
            elif field == 'process_type':
                value = (value or '').strip()
            dimensions[field] = value

        raw_bol = record.get(bol_field)
        if raw_bol is None:
            continue
        try:
            bol = float(raw_bol)
        except (TypeError, ValueError):
            continue
        if bol <= 0:
            continue

        key = tuple(dimensions[field] for field in group_fields)
        group = groups.setdefault(key, {
            **dimensions,
            'bol': 0.0,
            'source_row_count': 0,
            '_plants': set(),
        })
        group['bol'] += bol
        group['source_row_count'] += 1

        plant = normalize_plant(record.get('plant'))
        if plant and plant != '未知':
            group['_plants'].add(plant)

    results = []
    for key, group in groups.items():
        group['plants'] = tuple(sorted(group.pop('_plants')))
        results.append(group)
    results.sort(key=lambda row: tuple(str(row.get(field, '')) for field in group_fields))
    return results