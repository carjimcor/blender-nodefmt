# SPDX-License-Identifier: GPL-3.0-or-later
"""Reroute labels as Blender draws them (pure Python; text widths from Blender's font if it is
there, else an estimate).

Blender draws a reroute's label centred above its dot, and since Blender 5 it draws the label
of a labelled reroute, greyed, on every reroute after it on the same wire (reroute auto labels):
a label is shown once per reroute of its wire, not once. Rule NF041 keeps all of them clear of
each other, of nodes and of wires. Coordinates are node units, y down.
"""
FONT_SIZE = 11      # Blender's widget text size (points): a label's text, in node units at any UI scale
CHAR_W = 5.8        # average width of a character, when Blender's font is not available
ABOVE = 5.0         # the text's box ends this far above the dot ...
HEIGHT = 12.0       # ... and is this tall
PAD = 2.0           # and this much wider than the text on each side

_widths = {}


def text_width(text):
    """Width of a label's text in node units (Blender's UI font at FONT_SIZE, else an estimate)."""
    w = _widths.get(text)
    if w is None:
        try:
            import blf
            blf.size(0, FONT_SIZE)
            w = float(blf.dimensions(0, text)[0])
        except Exception:
            w = CHAR_W * len(text)
        _widths[text] = w
    return w


def box(p, w):
    """The box (x0, y0, x1, y1) of a label of text width w drawn above point p."""
    return (p[0] - w / 2 - PAD, p[1] - ABOVE - HEIGHT, p[0] + w / 2 + PAD, p[1] - ABOVE)


def overlap(a, b):
    """True if boxes a and b overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def hits(b, p, q):
    """True if the horizontal or vertical segment p-q passes through box b."""
    x0, x1 = sorted((p[0], q[0]))
    y0, y1 = sorted((p[1], q[1]))
    return x0 < b[2] and x1 > b[0] and y0 < b[3] and y1 > b[1]


def shown(t, own):
    """The labels Blender shows on the reroutes of reroute tree t (routes.Tree): {point: (text,
    inherited)}. own: {point: text} of its labelled reroutes; a label also shows, greyed, on every
    reroute after it on the wire, up to the next labelled reroute."""
    from .routes import reroute_points
    pts = set(reroute_points(t))
    out = {}
    todo = [(t.root, None)]
    seen = set()
    while todo:
        p, text = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        if p in pts:
            if p in own:
                text = own[p]
                out[p] = (text, False)
            elif text is not None:
                out[p] = (text, True)
        for c in t.children.get(p, ()):
            todo.append((c, text))
    return out


def faults(labels, nodes, segments):
    """Where shown labels collide: [(index in labels, what)], what being 'label' (another
    label), 'node' or 'wire'. labels: [(point, text, copy)]; nodes: [(x0, y0, x1, y1)];
    segments: [(p, q)] of the wires. For a greyed copy, a wire that leaves its dot is not
    counted: where the wire turns upwards it runs through the copy, which Blender draws on every
    reroute of the wire. A labelled reroute can be chosen, so there it counts."""
    boxes = [box(l[0], text_width(l[1])) for l in labels]
    out = []
    for k, b in enumerate(boxes):
        if any(overlap(b, o) for j, o in enumerate(boxes) if j != k):
            out.append((k, 'label'))
        if any(overlap(b, n) for n in nodes):
            out.append((k, 'node'))
        p, copy = labels[k][0], labels[k][2] if len(labels[k]) > 2 else True
        if any(hits(b, s, e) and not (copy and (near(p, s) or near(p, e))) for s, e in segments):
            out.append((k, 'wire'))
    return out


def near(p, q):
    """True if points p and q are the same point (within a tenth of a unit)."""
    return abs(p[0] - q[0]) < 0.1 and abs(p[1] - q[1]) < 0.1
