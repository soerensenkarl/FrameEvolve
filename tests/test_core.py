"""The builder: placing members, the contact graph, how rules fire; and the seed grammar on the dataset."""
import pytest

from frameevolve import houses
from frameevolve.builder import build
from frameevolve.graph import GROUND, build_graph
from frameevolve.verifier import verify

from conftest import SEED, box_house


def test_place_turns_the_section_by_its_short_side(wall_state):
    s = wall_state
    stud = s.place("2x4", 16, 17.5, 1.5, 95.625)
    plate = s.place("2x4", 0, 240, 0, 1.5)
    header = s.place("2x8", 40, 80, 82.5, 89.75)
    assert stud.box.size == pytest.approx((1.5, 3.5, 94.125))
    assert plate.box.size == pytest.approx((240, 3.5, 1.5))
    assert header.box.size == pytest.approx((40, 1.5, 7.25))
    assert stud.box.lo[1] == pytest.approx(0)   # flush with the outer face, framing inward
    with pytest.raises(ValueError):
        s.place("2x4", 0, 40, 0, 2)


def test_graph_bearing_and_clash(wall_state):
    s = wall_state
    plate = s.place("2x4", 0, 240, 0, 1.5)
    stud = s.place("2x4", 16, 17.5, 1.5, 95.625)
    clash = s.place("2x4", 16.5, 18, 1.5, 95.625)
    g = build_graph([plate, stud, clash])
    assert GROUND in g.bears[plate.id] and plate.id in g.bears[stud.id]
    assert {stud.id, plate.id, clash.id} <= g.grounded()
    assert len(g.clashes) == 1


def test_rules_fire_once_per_match_when_their_condition_holds(tmp_path):
    """A rule fires on each match once; a condition that becomes true later still fires it on a later pass."""
    g = tmp_path / "g.py"
    g.write_text(
        "from frameevolve.builder import rule\n"
        "@rule(1, match='wall')\n"
        "def plate(s, w):\n    s.place('2x4', 0, w.length, 0, 1.5)\n"
        "@rule(0, match='member', when=lambda s, m: m.rule == 'plate')\n"
        "def stud_on_plate(s, m):\n    s.place('2x4', 16, 17.5, 1.5, 95.625)\n")
    house = box_house()
    frame = build(g, house)
    assert not frame.errors
    assert sum(m.rule == "plate" for m in frame.members) == 4
    assert sum(m.rule == "stud_on_plate" for m in frame.members) == 4    # once per plate, on pass 2
    assert {s["pass"] for s in frame.steps if s["rule"] == "stud_on_plate"} == {2}
    assert frame.steps[0]["match"] == "wall 1w0" and frame.steps[0]["surface"] == "1w0"


def test_rule_errors_are_reported_with_line(tmp_path):
    g = tmp_path / "bad.py"
    g.write_text("from frameevolve.builder import rule\n\n@rule(1, match='wall')\ndef boom(s, w):\n    s.place('2x4', 0, 10, 0, 10)\n")
    frame = build(g, houses.generate(0))
    assert frame.errors and "boom" in frame.errors[0] and "line 5" in frame.errors[0]


PHYSICAL = {"rule error", "clash", "floating", "too long", "opening", "assembly"}


@pytest.mark.parametrize("seed", range(8))
def test_seed_grammar_frames_generated_houses_as_panels(seed):
    """The seed frames every house with nothing physically wrong (the code and the saw still find things for the
    search to fix), builds its walls and floors as panels that go up bottom first, and wastes no negative timber."""
    house = houses.generate(seed)
    frame = build(SEED, house)
    report = verify(house, frame)
    assert not [f.message for f in report.faults if f.check in PHYSICAL], house.id
    walls_floors = {x.id for x in house.walls} | {f.id for f in house.floors if f.role == "floor"}
    assert all(m.panel for m in frame.members if m.surface in walls_floors)
    assert report.metrics["waste_ft"] >= 0


def test_minimal_grammar_has_the_expected_hard_faults(minimal0):
    """The minimal grammar knows nothing about corners or openings, and the verifier says so; its plates are
    longer than any stock, and the waste still comes out at or above zero."""
    house, frame = minimal0
    r = verify(house, frame)
    hard = {f.check for f in r.faults if f.hard}
    assert {"clash", "too long", "opening", "backing", "head", "sill", "span"} <= hard
    assert max(m.length for m in frame.members) == max(w.length for w in house.walls) > 240
    assert r.metrics["waste_ft"] >= 0
    text = r.text()
    for check in hard:   # the text report names every hard check that occurs
        assert f"HARD {check} " in text
    assert "No faults." not in text
