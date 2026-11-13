import json
from pathlib import Path

import pytest

from app.agent_rag.tables import parse_tables, split_row, table_evidence
from app.agent_rag.preprocess import extract_identifiers


def test_optional_outer_pipes_alignment_and_numeric_strings():
    table = parse_tables('Title\nName | Value\n:--- | ---:\nID | 00001000\n')[0]
    assert table.headers == ('Name', 'Value')
    assert table.rows == (('ID', '00001000'),)
    assert (table.start_line, table.end_line) == (2, 4)


def test_empty_edge_cells_are_preserved():
    assert split_row('| | Motor | |') == ('', 'Motor', '')
    assert split_row('||Motor||') == ('', 'Motor', '')


def test_escaped_and_code_span_pipes_do_not_shift_columns():
    assert split_row(r'| A\|B | `X|Y` | C |') == (r'A\|B', '`X|Y`', 'C')
    assert split_row('| ``X`|Y`` | C |') == ('``X`|Y``', 'C')
    assert split_row('| unmatched ` | C |') == ('unmatched `', 'C')
    assert split_row(r'| A\\| B |') == (r'A\\', 'B')


def test_prose_and_fenced_code_are_not_tables():
    text = 'A | B\nnot a delimiter\n\n```md\n| A | B |\n| --- | --- |\n| 1 | 2 |\n```'
    assert parse_tables(text) == []


def test_adjacent_tables_and_single_column_tables():
    tables = parse_tables('| A |\n| --- |\n| one |\n| B | C |\n| --- | --- |\n| two | three |')
    assert len(tables) == 2
    assert tables[0].rows == (('one',),)
    assert tables[1].headers == ('B', 'C')


def test_ragged_rows_preserved_and_never_guessed_or_filled():
    table = parse_tables('| A | B |\n| --- | --- |\n| value |\n| | explicit blank |\n| x | y | extra |')[0]
    assert table.rows == (('value',), ('', 'explicit blank'), ('x', 'y', 'extra'))
    assert 'ragged_rows' in table.warnings


def test_repeated_long_cells_detected_without_deletion():
    cell = 'full table repeated ' * 30
    text = '| A | B |\n| --- | --- |\n' + '\n'.join(f'| {cell} | {i} |' for i in range(4))
    table = parse_tables(text)[0]
    assert 'repeated_long_cells' in table.warnings
    assert len(table.rows) == 4 and table.rows[3][0] == cell.strip()
    assert 'repeated_long_cells' not in parse_tables('| A | B |\n| --- | --- |\n| 0 | 0 |\n| 0 | 0 |')[0].warnings


def test_duplicate_headers_and_html_span_are_not_repaired():
    table = parse_tables('| | value | value |\n| --- | --- | --- |\n| <td rowspan="2">x</td> | | 001 |')[0]
    assert set(table.warnings) == {'empty_headers', 'duplicate_headers', 'html_spans_unresolved'}
    assert table.rows[0][1] == ''


def test_evidence_selects_query_rows_and_reports_every_truncation():
    text = '| A | B |\n| --- | --- |\n| 1 | plain |\n| 2 | target detailed description |\n\n' * 2
    evidence = table_evidence(text, query='target', max_tables=1, max_rows=1, max_cell_chars=8)
    assert evidence['tables_omitted'] == 1
    table = evidence['tables'][0]
    assert table['rows'] == [{'row_index': 2, 'cells': ['2', 'target d']}]
    assert table['cells_truncated'] and table['rows_omitted'] == 1
    assert evidence['empty_cell_policy'] == 'preserved_not_inferred'
    assert evidence['text_origin'] == 'converted_markdown_not_pdf_verified'


@pytest.mark.parametrize('limits', [dict(max_tables=0), dict(max_rows=-1), dict(max_cell_chars=0)])
def test_evidence_rejects_nonpositive_limits(limits):
    with pytest.raises(ValueError):
        table_evidence('', **limits)


def test_identifier_extraction_uses_actual_column_positions():
    text = r'''| NO. | Name | PART NO. |
| --- | --- | --- |
| 1 | motor\|drive | SM1101012035 |
| 2 | `motor|drive` | 2064-01-101-01 |

NAME | DWG
--- | ---
part | 2064-05-003-03
'''
    identifiers = {(i.kind, i.normalized) for i in extract_identifiers(text)}
    assert identifiers == {('part_no', 'SM1101012035'), ('part_no', '2064-01-101-01'), ('drawing_no', '2064-05-003-03')}


def test_ambiguous_or_ragged_identifier_tables_are_not_used():
    text = '| NO. | PART NO. | PART NO. |\n| --- | --- | --- |\n| 1 | SM1101012035 | 2064-01-101-01 |'
    assert extract_identifiers(text) == []
    text = '| NO. | PART NO. |\n| --- | --- |\n| 1 | missing | SM1101012035 |'
    assert extract_identifiers(text) == []


MOTOR_TABLE = '''| | Motor model | DiS 60/600-B | DiS 80/400-B |
| --- | --- | --- | --- |
| | Motor specification | 2318-B220 | 2323-B120 |
| | Motor ID No. | 0633 | 0636 |
| PRM NO | SERVO PRM | | |
| 2003 | | 00001000 | 00001000 |
| 2165 | MAX CURRENT | 45 | 85 |
'''


def test_motor_context_survives_query_selection_without_guessing_merged_cells():
    table = table_evidence(MOTOR_TABLE, query='2165', max_rows=1)['tables'][0]
    assert table['headers'] == ['', 'Motor model', 'DiS 60/600-B', 'DiS 80/400-B']
    assert table['context_rows'] == [
        {'row_index': 1, 'cells': ['', 'Motor specification', '2318-B220', '2323-B120']},
        {'row_index': 2, 'cells': ['', 'Motor ID No.', '0633', '0636']},
        {'row_index': 3, 'cells': ['PRM NO', 'SERVO PRM', '', '']},
    ]
    assert table['rows'] == [{'row_index': 5, 'cells': ['2165', 'MAX CURRENT', '45', '85']}]
    assert table['total_rows'] == 5 and table['rows_omitted'] == 1


def test_metadata_labels_in_body_are_not_promoted_to_header_context():
    text = '| Number | Description |\n| --- | --- |\n| 1 | normal body |\n| Motor ID No. | later body value |'
    table = table_evidence(text)['tables'][0]
    assert table['context_rows'] == []
    assert len(table['rows']) == 2


def test_column_limit_reports_omission_without_shifting_or_losing_source_cells():
    text = '| A | B | C | D |\n| --- | --- | --- | --- |\n| 1 | 002 | 3 | 4 | extra |'
    table = table_evidence(text, max_columns=2)['tables'][0]
    assert table['headers'] == ['A', 'B']
    assert table['rows'][0]['cells'] == ['1', '002']
    assert table['column_count'] == 5 and table['columns_omitted'] == 3
    assert 'ragged_rows' in table['warnings']
    assert parse_tables(text)[0].rows[0] == ('1', '002', '3', '4', 'extra')


def test_context_rows_obey_cell_and_column_limits_too():
    table = table_evidence(MOTOR_TABLE, max_rows=1, max_columns=3, max_cell_chars=10)['tables'][0]
    assert table['columns_omitted'] == 1
    assert table['cells_truncated']
    assert all(len(row['cells']) <= 3 for row in table['context_rows'])
    assert all(len(cell) <= 10 for row in table['context_rows'] for cell in row['cells'])


def test_column_limit_must_be_positive():
    with pytest.raises(ValueError):
        table_evidence(MOTOR_TABLE, max_columns=0)


@pytest.mark.parametrize('pdf_page,first_id,last_id,first_current,last_current', [
    (779, '633', '643', '45', '85'), (781, '230', '242', '365', '365'),
])
def test_real_manual_motor_tables_preserve_model_parameter_correspondence(
        pdf_page, first_id, last_id, first_current, last_current):
    fixtures = json.loads((Path(__file__).parent / 'fixtures' / 'manual_motor_tables.json').read_text(encoding='utf-8'))
    source = next(f for f in fixtures if f['pdf_page'] == pdf_page)
    parsed = parse_tables(source['markdown'])[0]
    evidence = table_evidence(source['markdown'], query='2165', max_rows=1)['tables'][0]
    # Some exported tables have an empty trailing column. Do not discard or shift it.
    last_model = 12 if pdf_page == 779 else 10
    assert evidence['context_rows'][1]['cells'][2] == first_id
    assert evidence['context_rows'][1]['cells'][last_model] == last_id
    row = evidence['rows'][0]
    assert row['cells'][0] == '2165' and row['cells'][1] == 'MAX CURRENT'
    assert row['cells'][2] == first_current and row['cells'][last_model] == last_current
    parameter = next(r for r in parsed.rows if r[0] == '2003')
    assert parameter[2] == '00001000'
    assert evidence['headers'] == list(parsed.headers)
    assert len(evidence['context_rows']) == 3 and evidence['rows_omitted'] == 1
