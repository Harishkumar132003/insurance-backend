"""Empty-result diagnosis. Pure — parses SQL and catalog descriptions, no I/O."""
from dataclasses import dataclass

from app.services.hybrid.diagnostics import (
    _literal_filters,
    empty_result_hint,
    value_domain,
)
import sqlglot


# The real description string from cube/pre_auth.yml, trimmed to one line.
PREAUTH_STATUS_DESC = (
    "Pre-auth workflow status, mirrored from the case. Complete set of possible "
    "values: DRAFT (not sent yet); SUBMITTED, ENHANCE_SUBMITTED, ADR_SUBMITTED, "
    "RECONSIDER (awaiting the insurer); ADR_NMI (insurer raised a query / needs more "
    "info); APPROVED, PARTIALLY_APPROVED, ENHANCEMENT_APPROVED (approvals); DENIED, "
    "ENHANCEMENT_DENIED (rejections); CANCELLED; and UNKNOWN (fallback)."
)


@dataclass
class FakeMember:
    name: str
    view: str = "master_hospital_360"
    kind: str = "dimension"
    title: str = ""
    description: str = ""


def _catalog():
    return [
        FakeMember("preauth_status", description=PREAUTH_STATUS_DESC),
        FakeMember("patient_name", description="Patient full name. Use for lookups."),
        FakeMember("cancelled", kind="segment", title="Cancelled",
                   description="Cancelled pre-auths where preauth_status = CANCELLED."),
    ]


class TestValueDomain:
    def test_extracts_the_enumerated_values(self):
        domain = value_domain(PREAUTH_STATUS_DESC)
        assert "CANCELLED" in domain and "ENHANCE_SUBMITTED" in domain
        assert "DRAFT" in domain and "UNKNOWN" in domain

    def test_ignores_prose_acronyms(self):
        # ADR and NMI appear as prose here; ADR_NMI is the real value.
        domain = value_domain(PREAUTH_STATUS_DESC)
        assert "ADR" not in domain and "NMI" not in domain
        assert "ADR_NMI" in domain

    def test_requires_a_domain_marker(self):
        # Without "possible values" this is just prose that happens to shout.
        assert value_domain("Use the UTR or TAT for this. See ADR notes.") == ()

    def test_empty_description(self):
        assert value_domain("") == ()


class TestLiteralFilters:
    def _tree(self, sql):
        return sqlglot.parse(sql, read="postgres")[0]

    def test_equality_either_way_round(self):
        assert ("preauth_status", "CANCELLED") in _literal_filters(
            self._tree("SELECT a FROM v WHERE preauth_status = 'CANCELLED'"))
        assert ("preauth_status", "CANCELLED") in _literal_filters(
            self._tree("SELECT a FROM v WHERE 'CANCELLED' = preauth_status"))

    def test_ilike(self):
        assert ("patient_name", "%ICICI%") in _literal_filters(
            self._tree("SELECT a FROM v WHERE patient_name ILIKE '%ICICI%'"))

    def test_in_list_expands(self):
        pairs = _literal_filters(
            self._tree("SELECT a FROM v WHERE preauth_status IN ('DENIED', 'CANCELLED')"))
        assert ("preauth_status", "DENIED") in pairs
        assert ("preauth_status", "CANCELLED") in pairs

    def test_numeric_literals_ignored(self):
        assert _literal_filters(self._tree("SELECT a FROM v WHERE amount = 100")) == []


class TestEmptyResultHint:
    def test_case_mismatch_names_the_stored_value(self):
        hint = empty_result_hint(
            "SELECT uhid FROM master_hospital_360 WHERE preauth_status = 'cancelled'",
            "master_hospital_360", _catalog())
        assert hint is not None
        assert "'CANCELLED'" in hint and "case-sensitive" in hint

    def test_unknown_value_lists_the_domain(self):
        hint = empty_result_hint(
            "SELECT uhid FROM master_hospital_360 WHERE preauth_status = 'foo'",
            "master_hospital_360", _catalog())
        assert hint is not None
        assert "no value 'foo'" in hint and "'DRAFT'" in hint

    def test_suggests_a_segment_when_one_encodes_the_filter(self):
        hint = empty_result_hint(
            "SELECT uhid FROM master_hospital_360 WHERE preauth_status = 'cancelled'",
            "master_hospital_360", _catalog())
        assert "segment `cancelled`" in hint

    def test_correct_value_is_not_diagnosed(self):
        # The filter is right; something else emptied the result. Saying nothing is
        # correct — a vague hint would burn a repair round.
        assert empty_result_hint(
            "SELECT uhid FROM master_hospital_360 WHERE preauth_status = 'CANCELLED'",
            "master_hospital_360", _catalog()) is None

    def test_no_domain_no_hint(self):
        assert empty_result_hint(
            "SELECT uhid FROM master_hospital_360 WHERE patient_name = 'Rahul'",
            "master_hospital_360", _catalog()) is None

    def test_no_filters_no_hint(self):
        assert empty_result_hint("SELECT uhid FROM master_hospital_360",
                                 "master_hospital_360", _catalog()) is None

    def test_unparseable_sql_returns_none(self):
        assert empty_result_hint("this is not sql (((", "master_hospital_360",
                                 _catalog()) is None

    def test_unknown_column_is_skipped(self):
        assert empty_result_hint(
            "SELECT a FROM master_hospital_360 WHERE nope = 'x'",
            "master_hospital_360", _catalog()) is None
