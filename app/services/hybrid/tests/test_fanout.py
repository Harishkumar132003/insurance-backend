"""Multi-branch (fan-out) behaviour.

Two halves. The pure half checks that `apply_fanout_guard` no longer deletes a branch
and that `guard_sql` rejects a measure projected twice. The live half is the one that
matters: it asserts Cube really does resolve a multi-fact query correctly, which is the
whole basis for having stopped dropping branches. If a Cube upgrade or a new view
regresses that, this test fails instead of an answer quietly going wrong.

The live tests need Cube on CUBE_SQL_HOST:CUBE_SQL_PORT. When it is unreachable they
report and return rather than raise — the runner has no skip protocol and an
unreachable Cube is not a code defect.
"""
from app.services.hybrid.cube_meta import Member
from app.services.hybrid.execute import SqlGuardError, guard_sql
from app.services.hybrid.retrieval import apply_fanout_guard
from app.schemas.hybrid import Hit, MemberSelection

VIEW = "master_hospital_360"

# Two averages and two sums, one pair per one_to_many branch of `hospitalization`.
PREAUTH_TAT = "preauth_average_transition_tat_hours"
CLAIM_TAT = "claim_average_transition_tat_hours"
PREAUTH_RAISED = "total_preauth_raised_amount"
CLAIM_RAISED = "total_claim_raised_amount"
SETTLED = "total_settled_amount"


def _measure(name: str, cube: str) -> Member:
    return Member(qname=f"{VIEW}.{name}", view=VIEW, name=name, kind="measure",
                  dtype="number", agg="sum", title=name, description="", cube=cube)


def _catalog() -> list[Member]:
    return [
        _measure(PREAUTH_TAT, "preauth_status_tracking"),
        _measure(CLAIM_TAT, "claim_status_tracking"),
        _measure(PREAUTH_RAISED, "preauth_status_tracking"),
        _measure(CLAIM_RAISED, "claim_status_tracking"),
        Member(qname=f"{VIEW}.policy_provider_name", view=VIEW, name="policy_provider_name",
               kind="dimension", dtype="string", agg="", title="Provider", description="",
               cube="policy_provider_configs"),
    ]


class TestGuardKeepsBothBranches:
    """The regression that produced "both are 20.39 hours"."""

    def test_measures_from_two_branches_both_survive(self):
        sel = MemberSelection(measures=[f"{VIEW}.{CLAIM_TAT}", f"{VIEW}.{PREAUTH_TAT}"])
        ranked = [Hit(qname=f"{VIEW}.{CLAIM_TAT}", rank=1, score=1.0),
                  Hit(qname=f"{VIEW}.{PREAUTH_TAT}", rank=2, score=1.0)]

        out, info = apply_fanout_guard(sel, _catalog(), ranked)

        assert f"{VIEW}.{PREAUTH_TAT}" in out.measures, "pre-auth measure was dropped again"
        assert f"{VIEW}.{CLAIM_TAT}" in out.measures
        assert info is not None and info["dropped_measures"] == []
        assert sorted(info["branches"]) == ["claim_status_tracking", "preauth_status_tracking"]

    def test_single_branch_reports_nothing(self):
        sel = MemberSelection(measures=[f"{VIEW}.{CLAIM_TAT}"])
        out, info = apply_fanout_guard(sel, _catalog(), [])
        assert out.measures == [f"{VIEW}.{CLAIM_TAT}"]
        assert info is None


class TestDuplicateMeasureGuard:
    def test_same_measure_twice_under_two_aliases_is_rejected(self):
        sql = (f"SELECT MEASURE({CLAIM_TAT}) AS preauth_hours, "
               f"MEASURE({CLAIM_TAT}) AS claim_hours FROM {VIEW}")
        try:
            guard_sql(sql, VIEW, _catalog())
        except SqlGuardError as e:
            assert CLAIM_TAT in str(e)
        else:
            raise AssertionError("duplicate projected measure was allowed through")

    def test_a_ratio_reusing_measures_is_allowed(self):
        # MEASURE(x) twice inside ONE expression is legitimate arithmetic, not padding.
        sql = (f"SELECT MEASURE({CLAIM_RAISED}) / NULLIF(MEASURE({PREAUTH_RAISED}), 0) AS ratio, "
               f"MEASURE({PREAUTH_RAISED}) AS raised FROM {VIEW}")
        guard_sql(sql, VIEW, _catalog())

    def test_two_distinct_measures_are_allowed(self):
        sql = (f"SELECT MEASURE({PREAUTH_TAT}) AS preauth_hours, "
               f"MEASURE({CLAIM_TAT}) AS claim_hours FROM {VIEW}")
        guard_sql(sql, VIEW, _catalog())


# ---- live Cube -------------------------------------------------------------
def _query(sql: str):
    from app.services.hybrid.execute import _run_blocking

    _, rows = _run_blocking(sql)
    return rows


def _cube_up() -> bool:
    try:
        _query("SELECT 1")
        return True
    except Exception:
        return False


def _num(v):
    return None if v is None else float(v)


class TestCubeResolvesMultiFactQueries:
    """Combined must equal separate. This is the evidence the guard change rests on."""

    def _combined_matches_separate(self, combined_sql: str, per_measure: dict[str, str]):
        if not _cube_up():
            print("      (Cube unreachable — live multi-fact check not run)")
            return
        combined = _query(combined_sql)[0]
        for alias, single_sql in per_measure.items():
            separate = list(_query(single_sql)[0].values())[0]
            assert _num(combined[alias]) == _num(separate), (
                f"{alias}: combined {combined[alias]} != separate {separate}")

    def test_two_branches_plain(self):
        self._combined_matches_separate(
            f"SELECT MEASURE({PREAUTH_TAT}) AS pa, MEASURE({CLAIM_TAT}) AS cl FROM {VIEW}",
            {"pa": f"SELECT MEASURE({PREAUTH_TAT}) FROM {VIEW}",
             "cl": f"SELECT MEASURE({CLAIM_TAT}) FROM {VIEW}"})

    def test_two_branches_sums(self):
        self._combined_matches_separate(
            f"SELECT MEASURE({PREAUTH_RAISED}) AS pa, MEASURE({CLAIM_RAISED}) AS cl FROM {VIEW}",
            {"pa": f"SELECT MEASURE({PREAUTH_RAISED}) FROM {VIEW}",
             "cl": f"SELECT MEASURE({CLAIM_RAISED}) FROM {VIEW}"})

    def test_three_branches(self):
        self._combined_matches_separate(
            f"SELECT MEASURE({PREAUTH_RAISED}) AS pa, MEASURE({CLAIM_RAISED}) AS cl, "
            f"MEASURE({SETTLED}) AS st FROM {VIEW}",
            {"pa": f"SELECT MEASURE({PREAUTH_RAISED}) FROM {VIEW}",
             "cl": f"SELECT MEASURE({CLAIM_RAISED}) FROM {VIEW}",
             "st": f"SELECT MEASURE({SETTLED}) FROM {VIEW}"})

    def test_two_branches_grouped_by_a_dimension(self):
        """Grouping is where a real fan-out would show up per-row, not just in the total."""
        if not _cube_up():
            print("      (Cube unreachable — live multi-fact check not run)")
            return
        combined = {r["policy_provider_name"]: r for r in _query(
            f"SELECT policy_provider_name, MEASURE({PREAUTH_TAT}) AS pa, "
            f"MEASURE({CLAIM_TAT}) AS cl FROM {VIEW} GROUP BY 1")}
        pa = {r["policy_provider_name"]: list(r.values())[1] for r in _query(
            f"SELECT policy_provider_name, MEASURE({PREAUTH_TAT}) FROM {VIEW} GROUP BY 1")}
        cl = {r["policy_provider_name"]: list(r.values())[1] for r in _query(
            f"SELECT policy_provider_name, MEASURE({CLAIM_TAT}) FROM {VIEW} GROUP BY 1")}

        assert combined, "no rows came back — the grouped check proved nothing"
        for provider, row in combined.items():
            assert _num(row["pa"]) == _num(pa[provider]), f"{provider} pre-auth TAT differs"
            assert _num(row["cl"]) == _num(cl[provider]), f"{provider} claim TAT differs"
