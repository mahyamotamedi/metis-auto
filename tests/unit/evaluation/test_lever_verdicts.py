"""The framework's rules applied to the pipelines' lever results (cache, context,
routing): the saving with its interval and provenance, the Persian slice, the
quality side as measured / not measured with the reason, and the plan's decision
rule per step. Only what the result file holds is used; nothing is guessed, so a
rule whose evidence is not in the file says so. SYNTHETIC results as plain
mappings (the pipelines' ``LeverResult`` JSON); no files, no network."""

from __future__ import annotations

import json

import pytest

from metis_auto.evaluation.reporting import lever_verdicts as lv


def result(
    *,
    step="context",
    version="context.syn",
    baseline="as_logged",
    saving="2",
    base="100",
    ci=(0.01, 0.03),
    state="unmeasured",
    evidence="simulation",
    n_requests=1000,
    fa=True,
    price="prices-syn",
    **kw,
):
    slices = {
        "all": {"saving_share": 0.02, "n_requests": n_requests},
        "llm_only": {"saving_share": 0.02},
    }
    if fa:
        slices["lang:fa"] = {
            "baseline:total": "40",
            "saving:total": "1.2",
            "saving_share": 0.03,
            "n_requests": 300,
        }
    return {
        "lever_id": f"{version}.{baseline}",
        "step": step,
        "version": version,
        "n_requests": n_requests,
        "n_eligible": 500,
        "baseline": baseline,
        "baseline_cost": {"total": base},
        "saving": {"total": saving},
        "ci_low": ci[0],
        "ci_high": ci[1],
        "slices": slices,
        "evidence_class": evidence,
        "correctness_state": state,
        "assumptions": [],
        "overhead_ms_p50": 10.0,
        "overhead_ms_p95": 20.0,
        "manifest": {"price_version": price},
        **kw,
    }


def one(res, **kw):
    report = lv.evaluate_levers([res], **kw)
    (row,) = [r for s in report["steps"].values() for r in s["results"]]
    return row


def test_the_saving_share_is_the_total_saving_over_the_baseline_with_its_interval():
    row = one(result(saving="2", base="100", ci=(0.01, 0.03)))
    est = row["saving_share"]
    assert est["state"] == "measured" and est["value"] == pytest.approx(0.02)
    assert est["interval"] == [0.01, 0.03]
    assert est["n"] == 1000 and est["provenance"] == "simulated"


def test_no_interval_means_a_point_value_not_a_claim():
    row = one(result(ci=(None, None)))
    assert row["saving_share"]["interval"] is None
    assert row["saving_share"]["claims_allowed"] is False
    assert one(result())["saving_share"]["claims_allowed"] is True


def test_a_zero_or_unknown_baseline_gives_no_share_not_a_division():
    row = one(result(base="0", saving="0"))
    assert row["saving_share"]["state"] == "not_evaluated"
    assert row["saving_share"]["reason"] == "baseline_cost_zero"


@pytest.mark.parametrize(
    "evidence, expected",
    [
        ("observed", "measured"),
        ("metadata-derived", "estimated"),
        ("heuristic", "estimated"),
        ("hypothetical reconstruction", "simulated"),
        ("simulation", "simulated"),
    ],
)
def test_the_evidence_class_maps_to_the_frameworks_provenance(evidence, expected):
    assert one(result(evidence=evidence))["saving_share"]["provenance"] == expected


def test_units_follow_the_baseline():
    assert one(result(baseline="as_logged"))["units"] == "recorded"
    assert one(result(baseline="todays_models"))["units"] == "repriced"
    assert one(result(baseline="premium_gpt_5_5"))["units"] == "estimate_only"


def test_the_persian_slice_is_reported_first_class_or_marked_missing():
    fa = one(result())["persian"]
    assert fa["state"] == "reported" and fa["saving_share"] == pytest.approx(0.03)
    assert fa["n_requests"] == 300
    gone = one(result(fa=False))["persian"]
    assert gone["state"] == "not_reported" and gone["saving_share"] is None


def test_quality_is_not_measured_unless_the_result_says_so():
    q = one(result(state="unmeasured"))["quality"]
    assert q == {
        "state": "not_measured",
        "reviewed": None,
        "reason": "correctness_unmeasured",
    }
    s = one(result(state="sampled:30"))["quality"]
    assert s["state"] == "sampled" and s["reviewed"] == 30
    m = one(result(state="measured"))["quality"]
    assert m["state"] == "measured"


def test_context_without_the_ablation_cannot_pass_and_says_tokens_only():
    rule = one(result(step="context", state="unmeasured"))["rule"]
    assert rule["outcome"] == "cannot_pass"
    assert rule["reason"] == "tokens_only_quality_not_measured"


def test_routing_without_labels_cannot_pass_and_says_cost_only():
    rule = one(result(step="routing", version="route.syn", state="unmeasured"))["rule"]
    assert rule["outcome"] == "cannot_pass"
    assert rule["reason"] == "cost_only_quality_not_proven"


def test_a_measured_context_result_still_needs_the_win_loss_rates_it_does_not_hold():
    rule = one(result(step="context", state="measured"))["rule"]
    assert rule["outcome"] == "not_evaluated"
    assert rule["reason"] == "quality_comparison_not_in_result"


def test_an_answer_cache_with_too_few_reviews_stays_a_candidate():
    res = result(step="cache", version="cache.popular_question.syn", state="sampled:30")
    rule = one(res)["rule"]
    assert rule["outcome"] == "candidate"
    assert rule["reason"] == "reviewed_30_below_300"
    unreviewed = one(result(step="cache", version="cache.popular_question.syn"))["rule"]
    assert unreviewed["outcome"] == "candidate"
    assert unreviewed["reason"] == "no_hits_reviewed"


def test_enough_reviews_still_need_an_error_count_the_result_does_not_hold():
    res = result(
        step="cache", version="cache.popular_question.syn", state="sampled:300"
    )
    rule = one(res)["rule"]
    assert rule["outcome"] == "not_evaluated"
    assert rule["reason"] == "answer_error_rate_not_in_result"


def test_a_retrieval_cache_needs_an_agreement_the_result_does_not_hold():
    res = result(step="cache", version="retrieval_result_cache.ttl_1d")
    rule = one(res)["rule"]
    assert rule["outcome"] == "not_evaluated"
    assert rule["reason"] == "retrieval_agreement_not_in_result"


def test_an_unknown_cache_kind_is_not_guessed():
    rule = one(result(step="cache", version="cache.something_new"))["rule"]
    assert rule["outcome"] == "not_evaluated" and rule["reason"] == "cache_kind_unknown"


def test_the_minimum_reviews_and_the_cache_kinds_are_parameters():
    res = result(step="cache", version="cache.popular_question.syn", state="sampled:30")
    row = one(res, min_reviewed=20)
    assert row["rule"]["reason"] == "answer_error_rate_not_in_result"
    kinds = {"cache.custom": "retrieval"}
    other = result(step="cache", version="cache.custom.x")
    assert (
        one(other, cache_kinds=kinds)["rule"]["reason"]
        == "retrieval_agreement_not_in_result"
    )


def test_each_step_says_whether_any_version_can_be_picked():
    report = lv.evaluate_levers(
        [result(step="context"), result(step="routing", version="route.syn")]
    )
    assert report["steps"]["context"]["pickable"] == []
    assert report["steps"]["routing"]["pickable"] == []
    assert report["steps"]["context"]["picked"] is None
    assert report["steps"]["cache"]["results"] == []  # a step with no results is empty


def test_results_in_different_scopes_are_marked_not_comparable():
    a = result(version="context.a", n_requests=1000, price="p1")
    b = result(version="context.b", n_requests=2000, price="p1")
    c = result(version="context.c", n_requests=1000, price="p2")
    report = lv.evaluate_levers([a, b, c])
    groups = report["steps"]["context"]["comparable_groups"]
    assert len(groups) == 3  # no two share scope, price version and evidence class
    same = lv.evaluate_levers(
        [a, result(version="context.d", n_requests=1000, price="p1")]
    )
    assert len(same["steps"]["context"]["comparable_groups"]) == 1


def test_the_report_is_content_free_and_json_safe():
    report = lv.evaluate_levers([result(), result(step="routing", version="route.syn")])
    assert json.loads(json.dumps(report)) == report  # JSON-safe, nothing lost
    assert report["format"] == "lever-evaluation-v1"
    assert report["n_results"] == 2
    assert "decision_rules" in report and "context" in report["decision_rules"]


def test_the_markdown_names_every_step_and_says_quality_is_not_measured():
    md = lv.to_markdown(
        lv.evaluate_levers([result(), result(step="routing", version="route.syn")])
    )
    for needle in ("cache", "context", "routing", "not measured", "cannot_pass"):
        assert needle in md
    assert "simulation" in md.lower()


# --- the summary by pipeline (A, B, C) ----------------------------------------


def _by_pipeline():
    results = [
        result(
            step="cache",
            version="cache.popular_question.first_turn",
            state="sampled:30",
        ),
        result(
            step="cache",
            version="retrieval_result_cache.ttl_1d",
            saving="3",
            ci=(0.02, 0.04),
        ),
        result(
            step="cache",
            version="retrieval_result_cache.ttl_90d",
            saving="5",
            ci=(0.04, 0.06),
        ),
        result(step="cache", version="cache.session_memo_gate", fa=False),
        result(step="context", version="context.reranker_cut.observed_relevancy"),
        result(step="context", version="cross_turn_chunks.ptr8.k3", ci=(None, None)),
        result(step="routing", version="route.per_bot"),
        result(step="routing", version="route.knn.k5"),
        result(step="routing", version="route.small_classifier.rules"),
        result(step="routing", version="route.something_else"),
    ]
    return lv.evaluate_levers(results)["pipelines"]


def test_every_result_is_assigned_to_a_pipeline_or_marked_unassigned():
    p = _by_pipeline()
    assert set(p) == {"A", "B", "C", "unassigned"}
    assert p["A"]["cache"]["variants"] == 1 and p["A"]["routing"]["variants"] == 1
    assert p["B"]["cache"]["variants"] == 2 and p["B"]["context"]["variants"] == 1
    assert p["C"]["cache"]["variants"] == 1 and p["C"]["routing"]["variants"] == 1
    assert p["unassigned"]["routing"]["variants"] == 1


def test_the_headline_is_the_largest_as_logged_saving_and_is_not_a_pick():
    b = _by_pipeline()["B"]["cache"]
    assert b["headline"]["version"] == "retrieval_result_cache.ttl_90d"
    assert b["headline"]["saving_share"]["value"] == pytest.approx(0.05)
    assert b["headline"]["is_pick"] is False
    assert b["saving_range"] == [pytest.approx(0.03), pytest.approx(0.05)]


def test_a_pipeline_step_with_no_results_has_no_headline():
    p = _by_pipeline()
    assert p["A"]["context"]["variants"] == 1  # reranker cut
    assert p["C"]["context"]["variants"] == 0 and p["C"]["context"]["headline"] is None


def test_the_blocker_is_said_in_plain_words_for_every_reason():
    p = _by_pipeline()
    assert "quality ablation" in p["A"]["context"]["blocked_by"][0]
    assert "acceptable rate" in p["A"]["routing"]["blocked_by"][0]
    assert "agreement" in p["B"]["cache"]["blocked_by"][0]
    assert (
        "30" in p["A"]["cache"]["blocked_by"][0]
        and "300" in p["A"]["cache"]["blocked_by"][0]
    )
    assert p["A"]["cache"]["can_pass"] is False


def test_counts_of_missing_intervals_and_persian_slices_per_pipeline_step():
    b = _by_pipeline()["B"]
    assert b["context"]["without_interval"] == 1
    assert b["cache"]["without_interval"] == 0 and b["cache"]["persian_reported"] == 2
    c = _by_pipeline()["C"]["cache"]
    assert c["persian_reported"] == 0


def test_the_markdown_opens_with_the_pipeline_summary():
    report = lv.evaluate_levers(
        [
            result(step="cache", version="retrieval_result_cache.ttl_1d"),
            result(step="routing", version="route.per_bot"),
            result(step="routing", version="route.small_classifier.rules"),
        ]
    )
    md = lv.to_markdown(report)
    top = md.split("## cache")[0]
    for needle in ("Pipeline A", "Pipeline B", "Pipeline C", "blocked by"):
        assert needle in top
    assert md.index("Pipeline B") < md.index("## cache")


def test_intervals_are_counted_against_the_results_not_the_variants():
    b = _by_pipeline()["B"]["context"]
    assert b["results"] == 1 and b["without_interval"] == 1
    md = lv.to_markdown(
        lv.evaluate_levers(
            [
                result(
                    step="context", version="cross_turn_chunks.ptr8.k3", ci=(None, None)
                )
            ]
        )
    )
    assert "0 of 1 results" in md and "-" not in md.split("0 of 1 results")[1][:3]
