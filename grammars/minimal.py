"""The near-empty starting grammar: plates and studs only. Knows nothing about corners or openings. Inches."""
from frameevolve.builder import rule

T = 1.5


@rule(10)
def plates(s):
    if not s.once():
        return
    L, H = s.wall.length, s.wall.height
    s.place("2x4", 0, L, 0, T, role="bottom plate")
    s.place("2x4", 0, L, H - T, H, role="top plate")


@rule(20)
def studs(s):
    """Studs every 16", skipped where they would cross an opening."""
    if not s.once():
        return
    L, H = s.wall.length, s.wall.height
    u = 0.0
    while u + T <= L:
        if s.free(u, u + T, T, H - T):
            s.place("2x4", u, u + T, T, H - T, role="stud")
        u += 16
