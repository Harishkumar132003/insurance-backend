"""Hybrid retrieval NL -> Cube SQL pipeline (v2, test harness).

Self-contained by design: nothing in this package imports from nl_sql_service or
intent_service, so the production pipeline and this one cannot break each other.
Only `app.core.config.settings` is shared.
"""
