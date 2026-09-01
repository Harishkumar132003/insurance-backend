"""Result-set comparison. Pure — no Cube, no OpenAI."""
from decimal import Decimal

from app.services.hybrid.compare import (
    Outcome,
    column_signature,
    compare,
    normalize_cell,
    score,
    to_column_major,
)


class TestNormalizeCell:
    def test_numeric_forms_collapse(self):
        # The gold file is hand-written ("29"); the driver returns Decimal('29.00').
        assert normalize_cell(Decimal("29.00")) == normalize_cell(29) == normalize_cell("29")
        assert normalize_cell(1.2) == normalize_cell(Decimal("1.20")) == normalize_cell("1.2000")

    def test_rounds_to_scale(self):
        assert normalize_cell(Decimal("1.005")) == normalize_cell(Decimal("1.00"))

    def test_null_and_empty_are_the_same_absence(self):
        assert normalize_cell(None) == normalize_cell("") == normalize_cell("   ") == ""

    def test_bools_collapse_to_digits(self):
        assert normalize_cell(True) == "1"
        assert normalize_cell(False) == "0"

    def test_bool_is_not_treated_as_int(self):
        # bool subclasses int; without an explicit branch True would round to "1" via
        # the Decimal path and False to "0" — same answer here, but the branch order
        # matters if scale ever changes.
        assert normalize_cell(True) != normalize_cell(1.5)

    def test_text_passes_through_stripped(self):
        assert normalize_cell("  CANCELLED ") == "CANCELLED"


class TestColumnSignature:
    def test_order_matters_when_ordered(self):
        assert column_signature(["A", "B"], ordered=True) != column_signature(["B", "A"], ordered=True)

    def test_order_ignored_when_unordered(self):
        assert column_signature(["A", "B"], ordered=False) == column_signature(["B", "A"], ordered=False)

    def test_separator_prevents_collision(self):
        # "AB" + "" must not hash the same as "A" + "B".
        assert column_signature(["AB", ""]) != column_signature(["A", "B"])


class TestCompare:
    def test_exact_match_is_right(self):
        outcome, _ = compare([{"cnt": ["29"]}], ["cnt"], [{"cnt": 29}])
        assert outcome is Outcome.RIGHT

    def test_column_name_is_irrelevant(self):
        # Cube returns measure(view.total_preauth_count); humanize() rewrites it.
        outcome, _ = compare([{"cnt": ["29"]}],
                             ["measure(preauth_tat_workflow.total_preauth_count)"],
                             [{"measure(preauth_tat_workflow.total_preauth_count)": 29}])
        assert outcome is Outcome.RIGHT

    def test_wrong_number_is_wrong(self):
        outcome, detail = compare([{"cnt": ["29"]}], ["cnt"], [{"cnt": 31}])
        assert outcome is Outcome.WRONG
        assert detail["actual_row_count"] == 1

    def test_falls_through_to_a_later_accepted_answer(self):
        # First answer is genuinely wrong; the second is right. Any match wins.
        gold = [{"cnt": ["31"]}, {"cnt": ["29"]}]
        outcome, detail = compare(gold, ["cnt"], [{"cnt": 29}])
        assert outcome is Outcome.RIGHT
        assert detail["matched_answer"] == 1

    def test_first_matching_answer_is_reported(self):
        gold = [{"cnt": ["29"]}, {"cnt": ["29"], "name": ["Apollo"]}]
        outcome, detail = compare(gold, ["cnt", "name"], [{"cnt": 29, "name": "Apollo"}])
        assert outcome is Outcome.RIGHT
        assert detail["matched_answer"] == 0   # gold[0] matches as a subset

    def test_gold_subset_matches(self):
        # The author cared about the count, not the identifying columns Cube adds.
        outcome, _ = compare([{"cnt": ["29"]}], ["uhid", "cnt"],
                             [{"uhid": "260029370955", "cnt": 29}])
        assert outcome is Outcome.RIGHT

    def test_row_order_ignored_by_default(self):
        outcome, _ = compare([{"n": ["A", "B"]}], ["n"], [{"n": "B"}, {"n": "A"}])
        assert outcome is Outcome.RIGHT

    def test_row_order_enforced_when_ordered(self):
        # A Top-N answer in the wrong order is a wrong answer.
        outcome, _ = compare([{"n": ["A", "B"]}], ["n"], [{"n": "B"}, {"n": "A"}],
                             ordered=True)
        assert outcome is Outcome.WRONG

    def test_empty_gold_matches_empty_result(self):
        outcome, _ = compare([{}], ["cnt"], [])
        assert outcome is Outcome.RIGHT

    def test_empty_result_against_real_gold_is_wrong(self):
        outcome, _ = compare([{"cnt": ["29"]}], ["cnt"], [])
        assert outcome is Outcome.WRONG

    def test_missing_gold_is_failed_not_wrong(self):
        outcome, detail = compare([], ["cnt"], [{"cnt": 29}])
        assert outcome is Outcome.FAILED
        assert "no gold answer" in detail["why"]


class TestScore:
    def test_rates_separate_correctness_from_runnability(self):
        out = score([
            (Outcome.RIGHT, {}), (Outcome.RIGHT, {}),
            (Outcome.WRONG, {}),
            (Outcome.FAILED, {}),
        ])
        assert out["right"] == 2 and out["wrong"] == 1 and out["failed"] == 1
        assert out["accuracy"] == 0.5          # 2/4
        assert out["exec_rate"] == 0.75        # (2+1)/4

    def test_empty_run_does_not_divide_by_zero(self):
        assert score([])["accuracy"] == 0.0


class TestToColumnMajor:
    def test_preserves_row_order_and_normalizes(self):
        assert to_column_major(["a"], [{"a": Decimal("1.10")}, {"a": None}]) == {"a": ["1.1", ""]}
