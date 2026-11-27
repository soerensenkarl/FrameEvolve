# Lab journal: Joe

Decisions, what was built, what runs taught. Newest at the bottom. Only Joe and Joe's Claude write here.

## 2026-11-20: the verifier against the 2021 IRC (branch `irc-verifier`)

Working on: the verifier's IRC checks (`frameevolve/verifier/code.py`, with small changes in `physical.py`,
`analysis.py`, `report.py`). Kenny is welcome to build on this branch.

- Audit. The verifier was read check by check against IRC chapters 3, 5, 6 and 8. Most limits match the tables.
  Five errors were found, four in the header tables: single-ply headers under a floor need 3 jacks (we allowed 2);
  walls under two floors used the one-floor rows; interior walls used the exterior table; headers used the
  30 psf snow column while rafters used 50 psf (Cambridge is 40). The fifth, rafter spans read at 10 psf dead
  load while the analysis uses 15, is still open.
- Reduction. The kept provisions (R301, R502, R602, R802) come down to 8 principles and 16 checkable rules,
  each mapped to its sections: `irc_rules.md`. Nails, hardware, foundations and seismic are stated as assumptions.
- Changed in the verifier:
  - headers: the 50 psf column, single-ply and two-floor rows, the interior table (R602.7(1), (2)); too few kings
    is now hard (R602.7.5);
  - floor joists may cantilever up to their nominal depth (was 2", R502.3.3); a notched rafter tail keeps 3 1/2"
    rather than 1/4 of its depth, and cantilevers at most 24" (R802.7.1.1);
  - in-line framing skips blocking: pieces under 36", by length, not label (R602.3.2 covers rafters and joists);
  - crushing is soft: an NDS check the IRC does not require for prescriptive framing (team to confirm);
  - new checks: `floor opening` (header and trimmer joists, doubled over 4 ft, R502.10), `splice` (double top
    plate joints 24" apart, R602.3.2), `story` (11'-7" floor to floor, R301.3); a top plate cut over half its
    width is a soft notch (needs a 16 ga tie, R602.6.1).
  - `tests/test_irc.py`: splices and story height on a hand-built wall.
- Bug caught on the way: a rafter's "tail" was taken as the longer side of its bearing, which for a rafter is the
  run up to the ridge, so the first 24" rule flagged 911 rafters "cantilevering" up to 15 ft. A tail is now the
  part past the bearing at the rafter's lower end, 6" or more.
- Not changed, after reading the IRC text: stair trimmers in the in-line check (trimmers are joists); gable
  studs over 10 ft (the rake rafter bears on them, so they are bearing studs); studs a fraction over 10 ft
  (height is plate to plate).

Hard faults over h000–h019, the same frames for each verifier:

| grammar | before | after |
|---|---|---|
| minimal | 8,882 | 8,882 |
| seed | 15,464 | 15,833 |
| advanced | 8,005 | 6,687 |

- advanced: 373 legal birdsmouths and 8 legal floor cantilevers no longer flagged; crushing (1,134) now soft.
  seed: 107 stair openings with no header or trimmer joists, 62 more undersized headers. The gap between the two
  grew from 1.9x to 2.4x.
- What is left on advanced is mostly real by the IRC's letter and comes from three choices in the grammar:
  single-ply headers on one jack, joists and rafters landing 1 1/2" beside the studs on a single top plate, and
  balloon-framed gable studs about 12'-9" tall.
- Verifier time unchanged: about 2.8 s per advanced house, 1.4 s per seed house, on one core.

Open, for the team: design ground snow and wind speed (115 mph in `analysis.py`, about 128 mph for the kings);
R602.10 prescriptive bracing or the SDPWS check with verified values; crushing and restraint hard or soft;
whether `advanced` should follow the IRC tables; `minimal` scores better than `seed` because it places fewer
members. Next: rafter seat bearing, the raised-tie span reduction, roof openings, uplift, then bracing.

## 2026-11-24: the IRC checks on real houses (branch `irc-real-houses`)

Ran the verifier on the 100 Cambridge houses `python -m frameevolve.dataset 600 100` chose on this machine, with
the three hand-written grammars (2 min for all 300 frames, 8 at a time; no crash). Every flagged IRC check was
read on examples against the code text.

| grammar | hard faults, 100 real houses | a house | a generated house (h000-h019) |
|---|---|---|---|
| minimal | 69,572 | 696 | 444 |
| seed | 99,421 | 994 | 792 |
| advanced | 54,186 | 542 | 334 |

- One misfire, fixed: every flat roof was a hard `ridge` fault ("0.0:12 ... must be designed beams", R802.4.4).
  The rule is for ridges, hips and valleys, and a flat or shed roof has none; it now applies only to a roof plane
  with a seam. advanced 106 -> 34, seed 129 -> 17; what is left are low-slope roofs that do meet at a ridge or hip.
- Read and kept as real:
  - `thrust` on low-slope roofs (877 on advanced, 49 houses): rafters at 1.7 to 3.4:12 leaning on a ridge with
    nothing tying them. Shed rafters resting on the high wall are already exempt.
  - `studs` (3,558): on three-storey houses the ground storey's 2x4 walls carry two floors, which Table
    R602.3(5) does not allow, and 2x6 at 24" must be 16". The generated houses never asked this; real ones do.
  - `story` (63, 21 houses): walls of 11'-10" to 14'-1" in the detailed houses (detail.py's storey heights or
    walls up to a flat roof). The message now says "floor to the top of its walls" for a top storey.
  - `floor opening`: advanced 0, seed 501 (stair openings without headers and trimmers), as on the generated set.
- The grammar's, not the verifier's: `notch` (3,051 on advanced: rafters cut through where roofs meet at odd
  angles), `floating` (2,803) and `rule error` (445). advanced cannot frame much of the real geometry yet.
- The gap between seed and advanced narrows on real houses, 1.8x against 2.4x, and `minimal` still scores better
  than `seed`.
- For Karl, from running the dataset here: 160 of 600 valid (his run: 361); failing `meeting` 295 (the check in
  progress) and 133 crashes, mostly a StopIteration at model.py:319, a few shapely TopologyExceptions.
