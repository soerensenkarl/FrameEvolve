# From the IRC to a small set of checks for a soundly framed timber house

Joe, 2026-11-20. Source: the 2021 IRC chapters 3, 5, 6, 8 and 9. How the verifier was checked against the IRC, the
trial runs and their results are in `journal_joe.md`. The checks live in `frameevolve/verifier/code.py`, `physical.py`
and `analysis.py`; each limit names its IRC section.

**Idea:** the IRC has hundreds of structural provisions, but most are restatements of a handful of physical requirements, applied member by member and tabulated for convenience. Like dimensionality reduction, we keep those few underlying requirements (the "principles"). For each one we write one or two checkable rules, and we keep a map from every kept IRC provision to the rule that covers it. Then nothing is silently dropped, and every rule is explainable by pointing at the code.

Some subsection numbers below are not printed in our scraped copy of Chapters 5 and 8. They were matched to the 2021 IRC numbering by their wording.

---

## Step 1: filter to timber houses and material-independent rules

### Kept

| Chapter | Section | Why kept |
|---|---|---|
| 3 | **R301 Design criteria**: load path (R301.1), wind / seismic / snow (R301.2), story height (R301.3), dead, live and roof loads (R301.4–R301.6), deflection (R301.7) | Material-independent: the loads and limits every rule uses |
| 3 | R317 Protection of wood against decay; R318 Termites | Timber-specific, but about materials and treatment, not geometry. Listed as out of scope |
| 5 | **R502 Wood floor framing** | Timber |
| 5 | R503 Floor sheathing | Timber; only as "panels assumed" (backing, bracing) |
| 6 | **R602 Wood wall framing** (incl. R602.10 wall bracing) | Timber |
| 6 | R604 Wood structural panels | Timber; only as the assumed sheathing for bracing |
| 8 | **R802 Wood roof framing** | Timber |
| 8 | R803 Roof sheathing | Timber; only as "panels assumed" |

### Dropped

| Chapter | Sections | Why dropped |
|---|---|---|
| 3 | R302–R316, R319–R327 (fire separation, light and ventilation, room sizes, glazing, egress, guards, alarms, sprinklers, flood, storm shelters, solar…) | Not structural framing |
| 5 | R504 treated wood floors on the ground, R505 cold-formed steel, R506 concrete slabs, R507 decks | Other materials, or outside the house frame |
| 6 | R603 cold-formed steel, R605 particleboard, R606–R608 masonry and concrete, R609 windows and doors, R610 SIPs | Other materials or products |
| 8 | R804 cold-formed steel, R805 ceiling finishes, R806 ventilation, R807 attic access | Other material or not structural |
| 9 | All (roof coverings, reroofing) | Roof covering, not framing |
| 4 | Foundations (not in our files) | Out of scope: the frame starts at the sill plate |

**What's left:** R301 plus R502, R602 and R802. That's roughly 60 structural provisions and about 25 span and size tables.

---

## Step 2: the principles behind those provisions

Almost every kept provision is an instance of one of eight requirements.

| # | Principle | In plain terms | Typical IRC provisions |
|---|---|---|---|
| P1 | **Continuous load path** | Every load has an unbroken chain of members down to the foundation, each bearing fully on the next | R301.1, R502.4, R502.6, R602.3, R602.7 (jacks), R602.9, R802.6 |
| P2 | **Member capacity** | Each member is big enough for its span and load, and stiff enough not to sag | R301.4–R301.7, R502.3.1, R502.5, R602.3(5), R602.7, R802.4.1, R802.5.1 |
| P3 | **Openings are bridged** | Where an opening cuts a member, the load goes around it: headers, jacks and kings in walls; doubled headers and trimmers in floors and roofs | R602.7, R602.7.5, R502.10, R802.9 |
| P4 | **Lateral resistance** | The house resists racking from wind: enough braced wall in each direction, well distributed, connected to the floors | R301.2.1, R602.10, R602.10.8, R502.2.1 |
| P5 | **Roof triangulation** | Rafters can't spread the walls: ties low in the roof, a ridge deep enough, hips and valleys as real members, a beam where the roof is too flat | R802.3, R802.4.2–R802.4.6, R802.5.2 |
| P6 | **Member stability** | Thin, deep or tall members are held against rolling over and buckling: blocking, bridging, height limits | R502.7, R502.7.1, R602.3(5) heights, R802.8 |
| P7 | **Framing continuity and alignment** | Plates are doubled and spliced so walls act as one; framing lands over studs; laps and splices are long enough | R602.3.2, R602.3.3, R502.6.1, R802.5.2.1 |
| P8 | **Section integrity** | Cuts (notches, holes, birdsmouths) don't remove too much of a member | R502.8, R602.6, R602.6.1, R802.7 |
| (P9) | *Connections and anchorage* | Nails, straps, hangers, anchor bolts, uplift ties | Table R602.3(1), R802.11, R602.11, R403.1.6 |
| (P10) | *Durability* | Decay and termite protection | R317, R318 |

We can't check P9 and P10 from member geometry; the frame model has no fasteners, hardware or materials. The report states them as assumptions: "connections per Table R602.3(1); uplift ties where Table R802.11 requires them".

**The main compression is inside P2.** The span tables (floor joists, rafters, ceiling joists, headers, studs: several hundred cells) are a single bending-and-deflection calculation evaluated at fixed loads and lumber grades. One capacity rule with NDS values reproduces them. Our hand checks agree with the tables: for a 2x10 floor joist at 16", the calculation gives 15'-4" and the table 15'-5". So the checker keeps the tables as the spot-check and the calculation as the rule, and it then also covers members the tables don't list, such as beams and girders.

---

## Step 3: representative rules (16)

Each rule is a test on member geometry and the contact graph. **H** means hard (code-required, unsafe if missed) and **S** means soft (quality or partly visible). "Before" is the verifier on `main` before this work (commit `f5cb88a`); "Now" is what it does after the `irc-verifier` branch.

| # | Rule (what the checker tests) | Principle | H/S | Main IRC source | Before | Now |
|---|---|---|---|---|---|---|
| 1 | **Load path.** Every member has a chain of bearing contacts to the foundation; nothing floats or clashes | P1 | H | R301.1 | ✔ | unchanged |
| 2 | **Bearing.** Every joist, rafter and beam end bears at least 1 1/2" on wood. A bearing wall above a floor sits within one joist depth of the support below | P1 | H | R502.6, R802.6, R502.4 | partly (rafter seats skipped) | **done:** rafter seats bear 1 1/2" (branch `irc-inputs-and-checks`) |
| 3 | **Continuous studs.** Studs run in one piece from bottom plate to top plate; cripple walls use studs at least as large as those above | P1 | H | R602.3, R602.9 | partly | unchanged |
| 4 | **Member capacity.** Every joist, rafter, ceiling joist, beam and header carries its share of dead + live + snow load: span within the IRC table, or NDS stress check where no table applies. Crushing across the grain is an NDS check the IRC doesn't require for prescriptive framing | P2 | H (crushing S) | R502.3.1, R802.4.1, R802.5.1, R602.7, R301.4–R301.6 | ✔ (snow load inconsistent; crushing hard) | **crushing made soft** (team decision); rafter spans from the 20 psf dead-load column to match the analysis's 15 psf (E5); beams in walls on the 50 psf column |
| 5 | **Studs by load.** Stud size, spacing and height match the floors they carry; story height is at most 11'-7". Gable-end studs that carry the rake rafter count as bearing (10 ft limit) | P2, P6 | H | Table R602.3(5), R301.3 | ✔ (story height missing) | **story height done** (new `story` check, `tests/test_irc.py`); gable studs confirmed as real faults |
| 6 | **Deflection.** Sag within L/360 floors, L/240 ceilings, L/180 roofs | P2 | S | R301.7 | ✔ | unchanged |
| 7 | **Wall openings.** Each opening in a bearing wall has a header sized by table (exterior or interior walls; 0, 1 or 2 floors above; the design snow column), the required jack studs and the required king studs | P3 | H | R602.7(1), R602.7(2), Table R602.7.5 | partly (errors E1–E4; kings soft) | **done:** 50 psf column, single-ply rows, two-floor rows, interior table, kings hard |
| 8 | **Floor and roof openings.** Every opening has header and trimmer joists; doubled when the header spans over 4 ft | P3 | H | R502.10, R802.9 | missing | **done for floors** (new `floor opening` check); roofs: no house has a roof opening yet, so not added |
| 9 | **Wall bracing.** Each storey has enough braced wall length in each direction for the design wind; panels at least 48" long, within 10 ft of each end of a braced wall line, at most 20 ft apart | P4 | H | R602.10 | substitute (SDPWS racking) | **done:** IRC prescriptive bracing, Method CS-WSP at 120 mph, replaces the SDPWS check |
| 10 | **Rafter ties.** Every rafter pair is tied in the lower third of the roof height by ceiling joists or ties continuous across the house (laps of at least 3"); otherwise the ridge is a beam | P5 | H | R802.5.2 | ✔ | **raised-tie span reduction done** (Table R802.4.1(9)) |
| 11 | **Ridge, hips, valleys.** As deep as the rafter cut; under 3:12 they are beams. (The 2" thickness rule is always met: every member is 1 1/2" thick) | P5 | H | R802.3, R802.4.3, R802.4.4 | ✔ | unchanged |
| 12 | **Restraint.** Joist and rafter ends are held by a rim, blocking or header; bridging where joists are deep | P6 | S→H | R502.7, R502.7.1, R802.8 | ✔ soft | unchanged (still soft) |
| 13 | **Top plates.** A double top plate has its end joints at least 24" apart. On a single top plate, joists and rafters land within 1" of a stud; blocking (pieces under 36") is exempt | P7 | H | R602.3.2, R602.3.3 | partly (in-line only; blocking flagged) | **done:** new `splice` check (tested on a hand-built wall: joints 12" apart fail, 24" pass); blocking exempt |
| 14 | **Cantilevers.** Floor joists cantilever no more than their nominal depth; rafter tails no more than 24" | P1, P2 | H | R502.3.3, R802.7.1.1 | too strict (2") | **done:** floor joists up to their nominal depth; notched rafter tails up to 24" (a tail is the part past the bearing at the lower end, 6" or more) |
| 15 | **Cuts.** Notches and holes in joists, rafters, studs and top plates within the IRC fractions. A rafter notched over its bearing with a tail keeps 3 1/2" (no 1/4 limit) | P8 | H | R502.8, R802.7, R602.6, R602.6.1 | ✔ (birdsmouths over-flagged; top plates, holes missing) | **birdsmouth fixed; top plates done** (a cut over half the width is a soft fault, "needs a 16 ga tie"); holes out of scope until modelled |
| 16 | **Uplift demand.** Rafters whose uplift exceeds 200 lb are flagged "connector required" | P9 | S | R802.11 | missing | **done:** soft `uplift`, Table R802.11 at 120 mph, exposure B |

**Effect on the hand-written grammars (hard faults, h000–h019):**
- Careful grammar: 8,005 → 6,687.
- Bare-bones seed: 15,464 → 15,833.

The gap between the bare-bones and careful grammars grew from 1.9x to 2.4x. Details in `journal_joe.md`.

**Coverage check:** every kept provision in Step 1 maps to one of these 16 rules, or to P9/P10 stated as assumptions. A teammate can test the reduction by picking any R502, R602 or R802 provision and finding its rule.

Kept outside the IRC score, as buildability (still in the verifier, reported separately): stock length, members in openings, sheathing backing and opening heads and sills, insulation depth, panel size, weight and count, cuttable pieces, erection order, cost.

---

## Open decisions

Settled 2026-11-24: Cambridge is 40 psf ground snow and 120 mph ultimate wind speed (780 CMR 10th edition, Table R301.2(2); confirm against the official text for a permit). Bracing is the IRC prescriptive method (R602.10, Method CS-WSP). Rafter spans use the 20 psf dead-load column.

1. **Restraint (rule 12):** hard or soft.
2. **Crushing (rule 4):** soft (as now) or hard.
3. **Reference grammar:** the hand-written "careful" grammar uses advanced-framing practice (single-ply headers, single top plates), which the IRC's prescriptive tables only partly allow. Make it IRC-prescriptive, or treat those parts as engineered?

## Still to do
- Rule 8: roof openings, once the houses have skylights or roof openings.
- Rule 9: the CS-WSP corner conditions (R602.10.7) and interior braced wall lines are not checked.
- Rule 15: holes. Out of scope until the model has holes.
- Unit tests for the rafter-tail and top-plate-cut checks.
