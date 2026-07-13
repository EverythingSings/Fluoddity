"""Shared parameter-lock widget wrappers (Step 11).

Collapses the open-coded "alt-click dance" that used to be repeated at every
lockable widget into two context managers. The old per-widget pattern was::

    pls = self.param_lock_service
    colors = pls.push_locked_style(name) if pls else 0
    label = pls.get_display_label(name, base) if pls else base
    _, val = imgui.slider_float(label, val, ...)
    if pls and pls.handle_alt_click(name):
        val = old_val            # discard the value change from the alt-click
    if pls:
        pls.pop_locked_style(colors)

which becomes::

    with lock_widget(pls, name, base) as w:
        _, val = imgui.slider_float(w.label, val, ...)
    if w.alt_clicked:
        val = old_val

`pls` may be None (feature not wired yet); the wrappers degrade to a no-op that
just yields the base label with ``alt_clicked == False``.

Combo widgets opened with ``imgui.begin_combo`` need different handling (the
alt-click must close the combo it just opened and skip its contents); use
``lock_begin_combo`` for those.
"""
from contextlib import contextmanager


class _LockWidget:
    """Handle yielded by lock_widget: exposes the display label + alt-click flag."""
    __slots__ = ('label', 'alt_clicked')

    def __init__(self, label: str):
        self.label = label
        self.alt_clicked = False


@contextmanager
def lock_widget(pls, param_name: str, base_label: str, *, defer_alt_click: bool = False):
    """Wrap a standard lockable widget (slider / slider_int / checkbox / combo).

    Pushes the locked style, yields a `_LockWidget` whose `.label` is the
    (possibly ``[L]``-prefixed) display label. After the ``with`` body renders
    the widget, checks for an alt-click on it: if intercepted, toggles the lock
    and sets ``.alt_clicked = True`` so the caller can discard the value change.
    Pops the style on exit.

    For ``imgui.combo`` (the one-call combo) this works directly. For
    ``imgui.begin_combo`` widgets, pass ``defer_alt_click=True`` and drive the
    alt-click via ``lock_begin_combo`` inside the body instead — begin_combo's
    open frame needs the combo-specific close-on-alt behaviour, and the exit
    handler must not double-toggle.
    """
    handle = _LockWidget(base_label)
    if pls is None:
        yield handle
        return

    colors = pls.push_locked_style(param_name)
    handle.label = pls.get_display_label(param_name, base_label)
    try:
        yield handle
        # Must run while this is still the "last item" (immediately after the widget).
        if not defer_alt_click:
            handle.alt_clicked = pls.handle_alt_click(param_name)
    finally:
        pls.pop_locked_style(colors)


def lock_begin_combo(pls, param_name: str, opened: bool) -> bool:
    """Alt-click handling for an ``imgui.begin_combo``.

    Call once right after ``begin_combo(...)``. When ``opened`` is True (combo
    is open, including the click-open frame), returns True if the open was an
    alt-click (lock toggled, combo already closed) — the caller must then skip
    rendering the combo contents and NOT call ``end_combo``. When ``opened`` is
    False, checks for an alt-click on the still-closed combo and toggles the
    lock; returns False (nothing to skip). Pair with
    ``lock_widget(..., defer_alt_click=True)`` for style + label.
    """
    if pls is None:
        return False
    if opened:
        return pls.begin_combo_alt_click(param_name)
    # Combo stayed closed: catch an alt-click on it (defensive; matches old logic).
    pls.handle_alt_click(param_name)
    return False
