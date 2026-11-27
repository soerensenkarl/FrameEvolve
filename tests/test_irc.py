"""IRC checks on hand-placed members: top-plate splices (R602.3.2) and story height (R301.3)."""
from frameevolve.builder import State
from frameevolve.model import Floor, Frame, House, Wall
from frameevolve.verifier import code
from frameevolve.verifier.site import Site


def wall_with_double_plate(lower_joint: float, upper_joint: float, height: float = 97.125) -> Site:
    """A 20 ft 2x4 box whose front wall has a double top plate, each ply in two pieces butted at the joints given
    (inches along the wall). 2x10 joists at 24" rest on the front and back walls."""
    pts = [(0.0, 0.0), (240.0, 0.0), (240.0, 180.0), (0.0, 180.0)]
    walls = [Wall(f"w{i}", pts[i], pts[(i + 1) % 4], height) for i in range(4)]
    house = House("t", walls, [Floor("f", pts, height + 9.25)])
    s = State(house)
    for w in (walls[0], walls[2]):
        s.surface = w
        s.place("2x4", 0, 240, 0, 1.5)                                   # bottom plate
        for u in [*range(0, 240, 24), 238.5]:
            s.place("2x4", u, u + 1.5, 1.5, height - 3.0)                # studs
        if w is walls[0]:
            for a, b in ((0, lower_joint), (lower_joint, 240)):
                s.place("2x4", a, b, height - 3.0, height - 1.5)         # lower top plate, two pieces
            for a, b in ((0, upper_joint), (upper_joint, 240)):
                s.place("2x4", a, b, height - 1.5, height)               # upper top plate, two pieces
        else:
            s.place("2x4", 0, 240, height - 3.0, height - 1.5)
            s.place("2x4", 0, 240, height - 1.5, height)
    s.surface = house.floors[0]
    for u in [*range(0, 240, 24), 238.5]:
        s.place("2x10", u, u + 1.5, 0, 180.0)
    return Site(house, Frame("t", "test", s.members("*")))


def test_top_plate_joints_closer_than_24_in_fail():
    faults = code.splices(wall_with_double_plate(120.0, 132.0))
    assert len(faults) == 1 and "12\"" in faults[0].message and faults[0].surface == "w0"


def test_top_plate_joints_24_in_apart_pass():
    assert not code.splices(wall_with_double_plate(120.0, 144.0))


def test_a_ten_foot_wall_under_a_floor_is_a_legal_story():
    assert not code.story_height(wall_with_double_plate(120.0, 144.0, height=120.0))


def test_a_twelve_foot_story_fails():
    faults = code.story_height(wall_with_double_plate(120.0, 144.0, height=135.0))
    assert faults and all(f.check == "story" for f in faults)


def test_a_braced_panel_beside_a_taller_opening_must_be_longer():
    """Table R602.10.5, Method CS-WSP: on a 10 ft wall, 30" beside a 48" window, 32" beside an 82" door; a 10 ft
    opening on an 8 ft wall's column is not permitted."""
    from frameevolve.model import Opening
    wall = Wall("w", (0.0, 0.0), (240.0, 0.0), 120.0,
                openings=[Opening("o1", "window", 40.0, 88.0, 36.0, 84.0), Opening("o2", "door", 140.0, 176.0, 0.0, 82.0)])
    assert code.panel_min(wall, 0.0, 40.0) == 30
    assert code.panel_min(wall, 88.0, 140.0) == 32
    assert code.panel_min(Wall("x", (0.0, 0.0), (96.0, 0.0), 96.0, openings=[Opening("o", "door", 0.0, 36.0, 0.0, 100.0)]),
                          36.0, 96.0) is None


def test_bracing_tables_interpolate():
    assert code._table(tuple(zip(code.BRACE_SPACINGS, code.BRACE_REQUIRED[0])), 25.0) == 4.25
    assert code._table(code.STORY_FACTOR, 7.0) == 0.90 and code._table(code.LINES_FACTOR, 7) == 1.60
