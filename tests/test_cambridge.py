"""Real houses: a building model read as an envelope, detailed into a House, amended, and checked."""
import pytest

from frameevolve import envelope
from frameevolve.check import problems
from frameevolve.detail import detail

RECORD = {"condition_yearbuilt": "1920", "exterior_numstories": "2", "exterior_style": "COLONIAL"}


@pytest.fixture
def model(tmp_path):
    """A city model of a plain house, as the files come: 36 by 26 ft, walls 20 ft, a gable roof to 28 ft, in feet,
    turned 20 degrees and far from the origin."""
    import math
    c, s = math.cos(math.radians(20)), math.sin(math.radians(20))
    turn = lambda x, y, z: (1000 + x * c - y * s, 5000 + x * s + y * c, 40 + z)
    pts = [(0, 0, 0), (36, 0, 0), (36, 26, 0), (0, 26, 0), (0, 0, 20), (36, 0, 20), (36, 26, 20), (0, 26, 20), (0, 13, 28), (36, 13, 28)]
    faces = [(5, 6, 10, 9), (7, 8, 9, 10), (1, 2, 6, 5), (3, 4, 8, 7), (2, 3, 7, 10, 6), (4, 1, 5, 9, 8), (4, 3, 2, 1)]
    path = tmp_path / "house.obj"
    path.write_text("".join("v %f %f %f\n" % turn(*p) for p in pts) + "".join("f " + " ".join(map(str, f)) + "\n" for f in faces))
    return path


def test_a_model_is_read_square_and_detailed_into_a_valid_house(model):
    env = envelope.envelope(model)
    assert len(env.masses) == 1 and len(env.masses[0].faces) == 2
    x0, y0, x1, y1 = env.masses[0].shape.bounds
    assert (x1 - x0, y1 - y0) == pytest.approx((432, 312), abs=2)            # turned square: 36 by 26 ft
    house = detail(env, RECORD, 0, "t")
    assert len({w.base for w in house.walls}) == 2 and len(house.roofs) == 2
    assert any(o.kind == "stair" for f in house.floors for o in f.openings)
    assert any(o.kind == "door" for w in house.walls if w.role == "exterior" for o in w.openings)
    assert not problems(house)


def test_amendments_change_what_the_procedure_made_and_say_what_came_of_them(model):
    plain = detail(envelope.envelope(model), RECORD, 0, "t")
    amendments = [
        {"set": {"floors_ft": [3.0, 12.0], "attic": "ceiling", "span": "standard"}, "by": "test"},
        {"openings": {"side": "south", "storey": 1, "items": [{"at": 0.25, "kind": "window", "w": 30, "h": 54}, {"at": 0.6, "kind": "door"}]}},
        {"openings": {"side": "south", "storey": 2, "items": []}},
        {"wall": {"storey": 1, "from_ft": [10, 0], "to_ft": [10, 13], "bearing": False}},
        {"no_wall": {"storey": 2, "near_ft": [300, 300]}},
        {"nonsense": 1},
    ]
    house = detail(envelope.envelope(model), RECORD, 0, "t", amendments)
    results = [r for _, r in house.amended]
    assert house.foundation == 36.0 and sorted({w.base for w in house.walls}) == [0.0, 108.0]
    south = lambda k: [o.kind for w in house.walls if w.role == "exterior" and w.base == (k - 1) * 108 and w.normal[1] > 0.9 for o in w.openings]
    assert sorted(south(1)) == ["door", "window"] and south(2) == []
    assert results[1] == "2 of 2 placed" and results[2].startswith("applied")
    assert any(w.id.startswith("1px") and w.start == (120.0, 0.0) for w in house.walls)
    assert results[4].startswith("not applied") and results[5].startswith("not understood")
    assert plain.foundation != house.foundation
    assert not problems(house)
