from __future__ import annotations

import pytest

from scripts.run_tender_v2_eval import (
    analyze_scenario,
    evaluate_ground_truth,
    scenario_ids,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_id", scenario_ids())
async def test_tender_v2_ground_truth(scenario_id: str) -> None:
    analysis = await analyze_scenario(scenario_id)
    evaluation = evaluate_ground_truth(scenario_id, analysis)
    assert evaluation["passed"], evaluation["checks"]


@pytest.mark.asyncio
async def test_tender_v2_has_one_machine_json_and_human_report_per_scenario() -> None:
    for scenario_id in scenario_ids():
        analysis = await analyze_scenario(scenario_id)
        assert analysis["machine_json"]["protocol_version"] == "2.0"
        assert analysis["machine_json"]["bid_decision"] in {
            "bid",
            "no_bid",
            "human_review",
        }
        assert analysis["human_report"]


def test_tender_v2_scenarios_are_independent() -> None:
    from pathlib import Path
    import json

    root = Path(__file__).parents[1] / "fixtures" / "tender_v2"
    material_ids: dict[str, set[str]] = {}
    for scenario_id in scenario_ids():
        directory = root / scenario_id
        scenario = json.loads((directory / "scenario.json").read_text(encoding="utf-8"))
        assert scenario["ground_truth_file"] not in scenario["visible_files"]
        assert all((directory / name).is_file() for name in scenario["visible_files"])
        bidder = json.loads(
            (directory / scenario["bidder_file"]).read_text(encoding="utf-8")
        )
        material_ids[scenario_id] = {
            item["material_id"] for item in bidder["materials"]
        }
    assert all(material_ids.values())
    assert not (material_ids["A_normal_bid"] & material_ids["B_no_bid"])
    assert not (material_ids["A_normal_bid"] & material_ids["C_human_review"])
    assert not (material_ids["A_normal_bid"] & material_ids["D_conflict"])
