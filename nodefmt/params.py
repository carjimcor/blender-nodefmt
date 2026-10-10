# SPDX-License-Identifier: GPL-3.0-or-later
"""Tunable constants of the layout engine: spacing, budgets and cost weights (node units).

Modules read them as params.NAME at run time, so a test (or an A/B session with the user) can
change one number and run again. docs/ALGORITHM.md lists the cost weights with what each one does.
"""

# ---------------------------------------------------------------- spacing
GRID = 20.0         # Blender's node grid (only the frame and tree offsets use it now)
NODE_GAP = 20.0     # vertical space between two nodes of a column
LANE_GAP = 20.0     # vertical space around a routed lane (dummy)
ZONE_LANE_GAP = 34.0  # NF032: in a zone, between a lane and the first or last node of its column
                    # (the zone outline is a widget unit, 20, from the nodes: the lane runs clear of it)
COL_GAP = 60.0      # minimum horizontal space between columns
TRACK = 20.0        # spacing of the vertical routing tracks in a gap
EPS = 0.5           # links whose ends differ by no more than this are straight
OVERHANG = True     # the end of a side branch may stick out of its column
SATELLITES = True   # NF021: a big block with no inputs sits right before its consumer, reaching left

# ---------------------------------------------------------------- track order (columns.py)
EXACT_TRACKS = 8    # gaps with up to this many tracks are ordered exactly
TRACK_BUNDLE = 4.0  # a crossing inside a bundle (same source or destination node) counts this much
TRACK_TOUCH = 8.0   # a wire that runs into another wire's corner counts this much

# ---------------------------------------------------------------- search budgets (engine.py, search.py)
CANDIDATES = 3      # orders of the crossing reduction laid out in full (each with every placement)
SEEDS = 1           # runs with differently seeded orders and moves (1: one deterministic pass; thorough: 8)
SEED_ONLY = None    # tests: run this one seed only (None: all SEEDS)
SEARCH_SEED = 40    # layouts tried by the local search of each seed
SEARCH = 120        # layouts tried by the final local search of the best seed
SLIDE = 40          # layouts tried by the final slide pass
JITTER = 0.6        # seeds other than 0: random shift of an item's initial barycenter (in places)
ORDERS = ('cross', 'force')                # order generators: crossing reduction, force-directed
PLACERS = ('blocks', 'balanced', 'relax')  # placement methods tried for each order
# zone output height, tried for each order and placement of a zone (the cheapest wins):
#   'level'  level with the zone input (its top line)
#   'median' a soft pull (ZONE_LEVEL) to that line, plus the weighted median of what its links want
#   'mean'   the same with the weighted mean: the output sits between its inputs
ZONE_OUT = ('level', 'median', 'mean')
PORTS_ABOVE = True  # NF033: a wire into a zone may enter above the zone input (over its outputs)
LANE_SIDES = True   # NF033: the search may also put a lane right above or below the nodes of its columns
ZONE_LEVEL = 6.0    # weight of the soft pull of a free zone output to the zone input's line

# stability: a layout grown from the current order replaces the fresh one if it costs at most
# this fraction more (0.0: only if it is as good or better, the current layout as the tie-breaker;
# None: never, the layout depends on the graph only)
STABLE = 0.0

# ---------------------------------------------------------------- block placement (placement.py)
# how much taller the layout may get to make a link straight, by link priority (0: geometry flow)
ALIGN_LIMIT = {0: 400.0, 1: 300.0, 2: 200.0, 3: 120.0, 4: 80.0, 5: 60.0}
BUNDLE = 3          # this many parallel links between two nodes are lined up first
GRAVITY = 0.5       # 'blocks': pull of every block towards a common top line ('balanced': none)
BEND = 40.0         # compaction: price of a link that is not straight (it needs two reroutes)
SRC_SLOPE = 1.0     # compaction: plus this per unit of drop for a link from a source node
BEND_SLOPE = 0.2    # compaction: plus this per unit of drop for other links
SNAP = False        # compaction: keep the tops of blocks on the grid (off: the grid does not matter)
GRID_PRICE = 0.0    # compaction: price of a block off the grid (with SNAP)
ALIGN_BONUS = 0.0   # compaction: bonus for a node level with one in the next column (off)

# ---------------------------------------------------------------- relaxation (relax.py, force.py)
RELAX_ITERS = 30    # spring relaxation sweeps
STRAIGHTEN = 200.0  # after relaxing, links bent by up to this much are made straight if possible
FORCE_STEPS = 120   # force-directed ordering: simulation steps
FORCE_COOL = 0.97   # force-directed ordering: step size factor per step
FORCE_REPEL = 0.3   # force-directed ordering: strength of the repulsion between items
FORCE_JITTER = 40.0  # force-directed ordering: random shift of start heights (seeds other than 0)

# ---------------------------------------------------------------- layout cost (cost.py)
W_CROSS = 4.0          # per clean crossing (a horizontal and a vertical wire, away from bends and sockets);
                       # NF033: more than a bend
W_CROSS_BAD = 12.0     # per crossing near a bend, a reroute or a socket, or of a diagonal wire
W_CROSS_BUNDLE = 15.0  # extra per crossing of two wires that leave or enter the same node
W_OVERLAP = 40.0       # per pair of wires running on one line (or closer than COLLINEAR)
W_CLASH = 40.0         # per reroute at (nearly) the point of another, or on another wire
W_BEND = 3.0           # per link that is not straight (two reroutes)
W_JOG = 8.0            # extra per link that steps by less than JOG (looks like a mistake)
JOG = 30.0
W_VLEN = 0.004         # per unit of vertical run
W_SRC = 0.01           # per unit a source node's link drops or rises
W_GRID = 0.0           # per node off the grid (the grid does not matter: alignment comes first)
W_H = 0.01             # per unit of height
W_W = 0.005            # per unit of width
W_BORDER = 2.0         # per run on the top or bottom line of a zone's outline (NF032)
W_HLEN = 0.002         # per unit of horizontal wire (NF021: long wires across the tree cost)
NEAR_RR = 10.0         # a crossing this close to a bend is not clean
NEAR_SOCK = 20.0       # a crossing this close to a socket is not clean
COLLINEAR = 6.0        # wires closer than this on parallel lines count as collinear
RR_CLEAR = 10.0        # two reroutes closer than this look like one
ON_WIRE = 6.0          # a reroute this close to another wire looks like a junction on it
TOUCH = 4.0            # tidy: a wire this close to a node box is on its edge (never moved there)
CLEAR_NODE = 10.0      # NF032: a wire this close to a node's edge (outside it) runs along it
CLEAR_OUTLINE = 8.0    # NF032: a wire this close to a frame border or zone outline is on it
CLEAR_RUN = 40.0       # NF032: ... over more than this length (a wire crossing a border is fine)
FAR_BLOCK = 400.0      # NF021 check: a frame with no inputs this far before its consumer is far
FAR_RISE = 100.0       # NF021 check: a frame with nothing linked that could sit this much higher
W_LABEL = 6.0          # NF041: per reroute label (or greyed copy of one) over another label, a node or a wire
W_LABEL_BEND = 1.0     # NF041: extra per bend of a labelled wire (each bend shows the label twice more)
LABEL_CLEAR = 6.0      # NF041: room kept between a label's text and the nodes beside its track
