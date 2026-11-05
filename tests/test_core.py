from pathlib import Path

import pytest

from frameevolve import houses, surface
from frameevolve.builder import State, build
from frameevolve.graph import GROUND, build_graph

ROOT = Path(__file__).resolve().parents[1]


def wall_state():
    house = houses.rectangle("t", 240, 160, 97.125)
    s = State(house)
    s.wall = house.walls[0]   # along +x, inward +y
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


def test_once_acts_once_per_key():
    s = wall_state()
    s._rule = "r"
    assert s.once("a") and not s.once("a") and s.once("b")


def test_seed_grammar_frames_generated_houses_cleanly():
    for seed in range(20):
        house = houses.generate(seed)
        frame = build(ROOT / "grammars/seed.py", house)
        g = build_graph(frame.members)
        assert not frame.errors, frame.errors
        assert not g.clashes, (house.id, g.clashes[:3])
        assert len(g.grounded()) == len(frame.members)
        assert not [gp for w in house.walls for gp in surface.gaps(w, frame.members)], house.id


def test_minimal_grammar_leaves_faults():
    house = houses.generate(0)
    frame = build(ROOT / "grammars/minimal.py", house)
    assert build_graph(frame.members).clashes
    assert [gp for w in house.walls for gp in surface.gaps(w, frame.members)]


def test_rule_errors_are_reported_with_line(tmp_path):
    g = tmp_path / "bad.py"
    g.write_text("from frameevolve.builder import rule\n\n@rule(1)\ndef boom(s):\n    s.place('2x4', 0, 10, 0, 10)\n")
    frame = build(g, houses.generate(0))
    assert frame.errors and "boom" in frame.errors[0] and "line 5" in frame.errors[0]
