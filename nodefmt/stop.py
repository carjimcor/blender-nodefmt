# SPDX-License-Identifier: GPL-3.0-or-later
"""Stopping a computation that runs in a worker thread (api._in_thread).

A sort computes the copy plan and the layout in a worker thread, so Blender stays responsive and
Esc works however long they take. Esc cannot interrupt the thread, so it asks it to stop: the
layout search calls check() before every layout it tries (search._evaluate), which raises Stopped
in a thread that was asked. Elsewhere (the main thread, the offline tools) check() does nothing.
"""

import threading


class Stopped(Exception):
    """The worker thread was asked to stop."""


_ASKED = set()  # idents of the worker threads asked to stop


def ask(ident):
    """Ask the thread with this ident to stop at its next check()."""
    _ASKED.add(ident)


def done(ident):
    """The thread with this ident has ended: forget that it was asked (idents are reused)."""
    _ASKED.discard(ident)


def check():
    """Raise Stopped if the current thread was asked to stop (cheap enough for hot loops)."""
    if _ASKED and threading.get_ident() in _ASKED:
        raise Stopped
