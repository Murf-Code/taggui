"""Shared order for tag and image-edit history, so Ctrl+Z undoes whatever
was done last and Ctrl+Y redoes whatever was undone last."""
import itertools

_counter = itertools.count(1)
_listeners = []


def next_seq() -> int:
    return next(_counter)


def on_new_edit(callback):
    """`callback(source)` runs when a new edit is made ('tags' or 'image')."""
    _listeners.append(callback)


def new_edit(source: str):
    for callback in _listeners:
        callback(source)
