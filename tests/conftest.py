"""Shared fixtures. Frames are built once per session: a seed build takes seconds."""
from pathlib import Path

import pytest

from frameevolve import houses
from frameevolve.builder import State, build
from frameevolve.model import House, Wall

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "grammars/seed.py"
ADVANCED = ROOT / "grammars/advanced.py"   # the hand-written reference: a realistic frame to test the verifier on
MINIMAL = ROOT / "grammars/minimal.py"


def box_house() -> House:
    """Four walls, one storey, 20 x 13'-4"."""
    pts = [(0.0, 0.0), (240.0, 0.0), (240.0, 160.0), (0.0, 160.0)]
    return House("t", [Wall(f"1w{i}", pts[i], pts[(i + 1) % 4], 97.125) for i in range(4)])


@pytest.fixture
def wall_state() -> State:
    """A fresh state on the first wall of the box house (along +x, inward +y)."""
    house = box_house()
    s = State(house)
    s.surface = house.walls[0]
    return s


@pytest.fixture
def toy_state():
    """A fresh state on the toy house, with the house: (house, state)."""
    house = houses.toy()
    return house, State(house)


@pytest.fixture(scope="session")
def minimal0():
    """House h000 framed by the minimal grammar: (house, frame)."""
    house = houses.generate(0)
    return house, build(MINIMAL, house)


@pytest.fixture(scope="session")
def seeded():
    """House h001, a two-storey box, framed by the reference grammar: (house, frame)."""
    house = houses.generate(1)
    return house, build(ADVANCED, house)


@pytest.fixture(scope="session")
def toy_seeded():
    """The toy house framed by the reference grammar: (house, frame)."""
    house = houses.toy()
    return house, build(ADVANCED, house)
