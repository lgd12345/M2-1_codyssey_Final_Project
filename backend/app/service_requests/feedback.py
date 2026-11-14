"""Operator ratings of the AI analysis a request currently shows (its latest successful analysis).

One rating per person per analysis. A re-analysis is a new analysis and starts unrated; the earlier ratings stay with
the analysis they judged. Customers never see ratings.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.auth.service import AuthError
from app.service_requests.analysis import AnalysisRequestNotFound

RATINGS = ('helpful', 'not_helpful')
EMPTY = {'helpful': 0, 'notHelpful': 0, 'ratings': []}


class NoAnalysis(AuthError):
    status_code, code = 409, 'NO_ANALYSIS'
    message = '평가할 분석 결과가 없습니다.'


def _latest_analysis(connection, number: int) -> UUID:
    if connection.execute('SELECT 1 FROM service_request WHERE id=%s', (number,)).fetchone() is None:
        raise AnalysisRequestNotFound()
    row = connection.execute(
        "SELECT id FROM service_analysis WHERE request_id=%s AND status='succeeded' ORDER BY created_at DESC, id DESC LIMIT 1",
        (number,)).fetchone()
    if row is None:
        raise NoAnalysis()
    return row[0]


def rate(connection, number: int, user_id: UUID, rating: str) -> None:
    if rating not in RATINGS:
        raise ValueError('unknown rating')
    with connection.transaction():
        analysis_id = _latest_analysis(connection, number)
        connection.execute(
            """INSERT INTO service_analysis_feedback(analysis_id,user_id,rating) VALUES (%s,%s,%s)
               ON CONFLICT (analysis_id,user_id) DO UPDATE SET rating=EXCLUDED.rating, updated_at=now()""",
            (analysis_id, user_id, rating))


def clear(connection, number: int, user_id: UUID) -> None:
    with connection.transaction():
        analysis_id = _latest_analysis(connection, number)
        connection.execute('DELETE FROM service_analysis_feedback WHERE analysis_id=%s AND user_id=%s', (analysis_id, user_id))


def load(connection, ids: list[int]) -> dict[int, list[dict[str, str]]]:
    """Ratings of each request's current analysis. Before the table exists the feature is simply empty, so that
    requests keep loading; saving a rating reports the storage as not ready instead."""
    try:
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                """SELECT s.request_id, u.login_id AS by, f.rating
                   FROM service_analysis_feedback f
                   JOIN service_analysis s ON s.id=f.analysis_id
                   JOIN app_user u ON u.id=f.user_id
                   WHERE s.request_id=ANY(%s) AND s.status='succeeded'
                     AND s.id=(SELECT id FROM service_analysis WHERE request_id=s.request_id AND status='succeeded'
                               ORDER BY created_at DESC, id DESC LIMIT 1)
                   ORDER BY f.updated_at, u.login_id""", (ids,)).fetchall()
    except psycopg.errors.UndefinedTable:
        return {}
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row['request_id'], []).append({'by': row['by'], 'rating': row['rating']})
    return grouped


def summary(ratings: list[dict[str, str]]) -> dict[str, Any]:
    return {'helpful': sum(1 for r in ratings if r['rating'] == 'helpful'),
            'notHelpful': sum(1 for r in ratings if r['rating'] == 'not_helpful'), 'ratings': ratings}
