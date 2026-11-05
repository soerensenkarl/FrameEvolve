from pathlib import Path

import pytest

from frameevolve import houses, surface
from frameevolve.builder import State, build
from frameevolve.verifier import verify
from frameevolve.model import House
from frameevolve.graph import GROUND, build_graph

ROOT = Path(__file__).resolve().parents[1]


def box_house():
    """Four walls, one storey, 20 x 13'-4"."""
    house = House("t", [])
    houses.ring(house, 1, 240, 160, 0.0, 97.125)
    house.link()
    return house


def wall_state():
    house = box_house()
    s = State(house)
    s.surface = house.walls[0]   # along +x, inward +y
    return s


def test_place_turns_the_section_by_its_short_side():
    s = wall_state()
    stud = s.place("2x4", 16, 17.5, 1.5, 95.625)
    plate = s.place("2x4", 0, 240, 0, 1.5)
    header = s.place("2x8", 40, 80, 82.5, 89.75)
    assert stud.box.size == pytest.approx((1.5, 3.5, 94.125))
    assert plate.box.size == pytest.approx((240, 3.5, 1.5))
    assert header.box.size == pytest.approx((40, 1.5, 7.25))
    assert stud.box.lo[1] == pytest.approx(0)   # flush with the outer face, framing inward
    with pytest.raises(ValueError):
        s.place("2x4", 0, 40, 0, 2)


def test_graph_bearing_and_clash():
    s = wall_state()
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
    assert frame.steps[0]["match"] == "wall 1w0"


def test_seed_grammar_frames_generated_houses_cleanly():
    """The seed grammar frames multi-storey houses with no errors and no hard faults."""
    for seed in range(4):
        house = houses.generate(seed)
        frame = build(ROOT / "grammars/seed.py", house)
        report = verify(house, frame)
        assert not frame.errors, frame.errors
        assert report.hard == 0, [f.message for f in report.faults][:3]


def test_minimal_grammar_leaves_faults():
    house = houses.generate(0)
    frame = build(ROOT / "grammars/minimal.py", house)
    assert build_graph(frame.members).clashes
    assert [gp for w in house.walls for gp in surface.gaps(w, frame.members)]


def test_rule_errors_are_reported_with_line(tmp_path):
    g = tmp_path / "bad.py"
    g.write_text("from frameevolve.builder import rule\n\n@rule(1, match='wall')\ndef boom(s, w):\n    s.place('2x4', 0, 10, 0, 10)\n")
    frame = build(g, houses.generate(0))
    assert frame.errors and "boom" in frame.errors[0] and "line 5" in frame.errors[0]
