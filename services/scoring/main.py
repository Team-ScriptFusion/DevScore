"""Orchestrates vi-building, split assignment, fitting, WVR application,
and validation for the scoring service's Flask routes."""

from inter_rater import compute_inter_rater
from split import assign_split
from validation import compute_validation
from vi_builder import build_category_vi, build_code_quality_vi
from weight_fitting import cross_validate, fit_weights
from wvr_calculator import compute_wvr


def run_build_vi(skill_rows: list, summary, range_hint: dict) -> dict:
    return {
        "vi_by_category": build_category_vi(skill_rows),
        "code_quality_vi": build_code_quality_vi(summary, range_hint),
    }


def run_assign_split(user_ids: list, train_fraction: float, seed: int, existing: dict = None) -> dict:
    return assign_split(user_ids, train_fraction, seed, existing or {})


def run_fit(training_rows: list, categories: list, weights_version: str) -> dict:
    weights = fit_weights(training_rows, categories)
    cv_score = cross_validate(training_rows, categories)
    return {
        "status": "completed",
        "weights_version": weights_version,
        "weights": [{"category": category, "weight": weight} for category, weight in weights.items()],
        "cv_score": cv_score,
    }


def run_wvr(weights_list: list, vi_by_category: dict, code_quality_vi: float) -> float:
    weights = {item["category"]: item["weight"] for item in weights_list}
    return compute_wvr(weights, vi_by_category, code_quality_vi)


def run_validate(test_rows: list, weights_list: list, expert_pairs: list = None) -> dict:
    weights = {item["category"]: item["weight"] for item in weights_list}
    result = compute_validation(test_rows, weights)
    if expert_pairs:
        result["inter_rater"] = compute_inter_rater(expert_pairs)
    return result
