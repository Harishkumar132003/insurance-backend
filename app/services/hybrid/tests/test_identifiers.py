"""Identifier probe. The trigger and SQL construction are pure; the probe itself is not
exercised here (it needs Cube) — see the plan's end-to-end step for that."""
from dataclasses import dataclass

from app.schemas.hybrid import Entity
from app.services.hybrid.identifiers import (
    PROBE_FIELDS,
    PROBE_VIEW,
    Resolution,
    _available_fields,
    build_probe_sql,
    looks_like_identifier,
    resolution_hint,
)


@dataclass
class FakeMember:
    name: str
    view: str = PROBE_VIEW


class TestLooksLikeIdentifier:
    def test_accepts_the_ambiguous_bare_number(self):
        assert looks_like_identifier(Entity(value="260029370955", kind="uhid"))

    def test_accepts_regardless_of_claimed_kind(self):
        # The whole point: the claimed kind is untrusted, so it must not gate the probe.
        assert looks_like_identifier(Entity(value="260029370955", kind="claim"))
        assert looks_like_identifier(Entity(value="260029370955", kind="other"))

    def test_accepts_alphanumeric_identifiers(self):
        assert looks_like_identifier(Entity(value="CL260029370955", kind="claim"))
        assert looks_like_identifier(Entity(value="POL52435", kind="policy"))

    def test_rejects_names(self):
        assert not looks_like_identifier(Entity(value="ICICI Lombard", kind="provider"))
        assert not looks_like_identifier(Entity(value="Rahul", kind="patient"))

    def test_rejects_a_name_kind_even_when_it_has_digits(self):
        # "Apollo 24x7" is a provider name, not something to look up by equality.
        assert not looks_like_identifier(Entity(value="Apollo24x7", kind="provider"))

    def test_rejects_digitless_values(self):
        assert not looks_like_identifier(Entity(value="CANCELLED", kind="other"))

    def test_rejects_out_of_range_lengths(self):
        assert not looks_like_identifier(Entity(value="12", kind="other"))
        assert not looks_like_identifier(Entity(value="9" * 41, kind="other"))

    def test_rejects_whitespace(self):
        assert not looks_like_identifier(Entity(value="2600 2937", kind="other"))


class TestBuildProbeSql:
    def test_always_scopes_by_hospital(self):
        # The Cube path has no row-level security; without this predicate the probe
        # would read across tenants.
        sql = build_probe_sql(("uhid", "claim_number"))
        assert "hospital_id = %s" in sql
        assert sql.index("hospital_id = %s") < sql.index("uhid = %s")

    def test_binds_every_field(self):
        fields = ("uhid", "claim_number", "policy_number")
        sql = build_probe_sql(fields)
        assert sql.count("%s") == len(fields) + 1      # + hospital_id
        for f in fields:
            assert f"{f} = %s" in sql

    def test_targets_the_probe_view_and_caps_rows(self):
        sql = build_probe_sql(("uhid",))
        assert f"FROM {PROBE_VIEW}" in sql and "LIMIT" in sql

    def test_no_literal_interpolation(self):
        assert "'" not in build_probe_sql(("uhid", "claim_number"))


class TestAvailableFields:
    def test_narrows_to_what_the_model_exposes(self):
        catalog = [FakeMember("uhid"), FakeMember("claim_number"),
                   FakeMember("policy_number", view="other_view")]
        assert _available_fields(catalog) == ("uhid", "claim_number")

    def test_empty_when_the_view_is_gone(self):
        assert _available_fields([FakeMember("uhid", view="nope")]) == ()

    def test_preserves_declared_order(self):
        catalog = [FakeMember(f) for f, _ in reversed(PROBE_FIELDS)]
        assert _available_fields(catalog) == tuple(f for f, _ in PROBE_FIELDS)


class TestResolution:
    def test_single_match_resolves(self):
        r = Resolution(value="260029370955", matched=("uhid",))
        assert r.resolved_field == "uhid" and r.resolved_kind == "uhid"

    def test_multiple_matches_stay_ambiguous(self):
        r = Resolution(value="260029370955", matched=("uhid", "claim_number"))
        assert r.resolved_field is None and r.resolved_kind is None

    def test_no_match_resolves_to_nothing(self):
        assert Resolution(value="x", matched=()).resolved_field is None


class TestResolutionHint:
    def test_states_a_single_match_as_fact(self):
        hint = resolution_hint([Resolution(value="260029370955", matched=("uhid",))])
        assert "is a uhid" in hint and "uhid = '260029370955'" in hint

    def test_reports_ambiguity_without_choosing(self):
        hint = resolution_hint([Resolution(value="260029370955",
                                           matched=("uhid", "claim_number"))])
        assert "uhid and claim_number" in hint

    def test_zero_match_is_stated_explicitly(self):
        # Turns "no matching records" into a statement about the identifier itself.
        hint = resolution_hint([Resolution(value="999", matched=(),
                                           probed=("uhid", "claim_number"))])
        assert "NOT found" in hint and "uhid, claim_number" in hint

    def test_errored_probe_contributes_nothing(self):
        assert resolution_hint([Resolution(value="1", error="boom")]) == ""

    def test_empty_input(self):
        assert resolution_hint([]) == ""
