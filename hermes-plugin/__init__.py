"""Hermes Connector companion plugin.

Connects this Hermes process to the single local broker and exposes browser
tools. Every call forwards the real Hermes profile, session, and task identity;
the paired extension executes it only in tabs the user attached to that scope.

Register surface follows Hermes v0.18 PluginContext (register_tool). If a future Hermes changes the
signature, adjust `register()` — everything else is plain stdlib.
"""

import json

from . import bridge_client

BRIDGE = None


def _res(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _schema(name, description, properties=None, required=None):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
    }


# ---- tool handlers (return JSON strings; never raise) -----------------------

def h_status(args, **_):
    if BRIDGE is None:
        return _res({"bridge": {"connected": False, "error": "plugin not registered"}})
    return _res({"bridge": BRIDGE.refresh_status()})


def _drive(action, timeout=30, **context):
    if BRIDGE is None:
        return _res({"ok": False, "error": "Connector plugin is not registered"})
    return _res(BRIDGE.request(
        action,
        timeout=timeout,
        session_id=context.get("session_id"),
        task_id=context.get("task_id"),
    ))


def h_open(args, **context):
    return _drive({"kind": "navigate", "url": args.get("url", "")}, **context)


def h_snapshot(args, **context):
    return _drive({"kind": "snapshot", "maxChars": args.get("max_chars")}, **context)


def h_read(args, **context):
    return _drive({"kind": "read_text", "maxChars": args.get("max_chars")}, **context)


def h_click(args, **context):
    return _drive({"kind": "click", "ref": args.get("ref")}, **context)


def h_type(args, **context):
    return _drive({"kind": "type", "ref": args.get("ref"), "text": args.get("text", ""),
                   "submit": bool(args.get("submit"))}, **context)


def h_screenshot(args, **context):
    return _drive({"kind": "screenshot"}, timeout=20, **context)


def h_scroll(args, **context):
    direction = (args.get("direction") or "").lower()
    action = {"kind": "scroll"}
    if direction in ("top", "bottom"):
        action["to"] = direction
    elif args.get("ref"):
        action["ref"] = args["ref"]
    else:
        px = args.get("pixels") or 600
        action["dy"] = -abs(px) if direction == "up" else abs(px)
    return _drive(action, **context)


def h_key(args, **context):
    return _drive({"kind": "key", "key": args.get("key", ""), "ref": args.get("ref")}, **context)


def h_hover(args, **context):
    return _drive({"kind": "hover", "ref": args.get("ref")}, **context)


def h_select(args, **context):
    return _drive({"kind": "select_option", "ref": args.get("ref"),
                   "value": args.get("value"), "label": args.get("label")}, **context)


def h_drag(args, **context):
    return _drive({"kind": "drag", "from": args.get("from"), "to": args.get("to")}, **context)


def h_find(args, **context):
    return _drive({"kind": "find", "text": args.get("text", "")}, **context)


def h_nav(args, **context):
    a = (args.get("action") or "reload").lower()
    if a not in ("back", "forward", "reload"):
        return _res({"ok": False, "error": "action must be back|forward|reload"})
    return _drive({"kind": a}, **context)


def h_tab(args, **context):
    a = (args.get("action") or "list").lower()
    kinds = {"new": "new_tab", "list": "list_tabs", "switch": "switch_tab", "close": "close_tab"}
    if a not in kinds:
        return _res({"ok": False, "error": "action must be new|list|switch|close"})
    action = {"kind": kinds[a]}
    if a == "new":
        action["url"] = args.get("url", "about:blank")
    if a in ("switch", "close") and args.get("index") is not None:
        action["index"] = args["index"]
    return _drive(action, **context)


def h_wait(args, **context):
    return _drive({"kind": "wait", "ms": args.get("ms", 1000)}, timeout=30, **context)


def h_current_url(args, **context):
    return _drive({"kind": "current_url"}, **context)


# ---- registration -----------------------------------------------------------

def register(ctx):
    global BRIDGE
    previous = BRIDGE
    if previous is not None:
        try:
            previous.stop()
        except Exception:
            pass
    BRIDGE = bridge_client.BridgeClient(profile_id=ctx.profile_name)
    BRIDGE.start()
    available = lambda: BRIDGE is not None

    tools = [
        ("bridge_status", _schema("bridge_status",
            "Show the Connector broker, paired Chrome instances, and exact session bindings."),
            h_status, None),
        ("bridge_open", _schema("bridge_open", "Navigate the paired browser to a URL.",
            {"url": {"type": "string"}}, ["url"]), h_open, available),
        ("bridge_snapshot", _schema("bridge_snapshot",
            "Get an accessibility snapshot of the current page with [ref_N] handles for elements.",
            {"max_chars": {"type": "integer"}}), h_snapshot, available),
        ("bridge_read", _schema("bridge_read", "Get the visible text of the current page.",
            {"max_chars": {"type": "integer"}}), h_read, available),
        ("bridge_click", _schema("bridge_click", "Click an element by its ref id from a snapshot.",
            {"ref": {"type": "string"}}, ["ref"]), h_click, available),
        ("bridge_type", _schema("bridge_type", "Type text into an element by its ref id.",
            {"ref": {"type": "string"}, "text": {"type": "string"}, "submit": {"type": "boolean"}},
            ["ref", "text"]), h_type, available),
        ("bridge_screenshot", _schema("bridge_screenshot", "Capture the visible tab as a PNG data URL."),
            h_screenshot, available),
        # --- human-like extras: scroll, keyboard, hover, selects, drag, find, history, tabs ---
        ("bridge_scroll", _schema("bridge_scroll",
            "Scroll the page like a mouse wheel: direction down/up, or to the very top/bottom, or bring a ref into view.",
            {"direction": {"type": "string", "enum": ["down", "up", "top", "bottom"]},
             "pixels": {"type": "integer", "description": "how far for up/down (default 600)"},
             "ref": {"type": "string", "description": "scroll this element into view instead"}}),
            h_scroll, available),
        ("bridge_key", _schema("bridge_key",
            "Press a key or combo on the page: 'Enter', 'Escape', 'Tab', 'ArrowDown', 'PageDown', 'Control+a', etc. Optional ref to target an element.",
            {"key": {"type": "string"}, "ref": {"type": "string"}}, ["key"]),
            h_key, available),
        ("bridge_hover", _schema("bridge_hover",
            "Hover the mouse over an element by ref (reveals dropdown menus / tooltips).",
            {"ref": {"type": "string"}}, ["ref"]), h_hover, available),
        ("bridge_select", _schema("bridge_select",
            "Choose an option in a dropdown <select> by ref, matching a value or a visible label.",
            {"ref": {"type": "string"}, "value": {"type": "string"}, "label": {"type": "string"}},
            ["ref"]), h_select, available),
        ("bridge_drag", _schema("bridge_drag", "Drag one element onto another (drag-and-drop), by refs.",
            {"from": {"type": "string"}, "to": {"type": "string"}}, ["from", "to"]),
            h_drag, available),
        ("bridge_find", _schema("bridge_find",
            "Find text on the current page and scroll to the first match; reports how many matches.",
            {"text": {"type": "string"}}, ["text"]), h_find, available),
        ("bridge_nav", _schema("bridge_nav", "Browser history: go back, forward, or reload the page.",
            {"action": {"type": "string", "enum": ["back", "forward", "reload"]}}, ["action"]),
            h_nav, available),
        ("bridge_tab", _schema("bridge_tab",
            "Manage tabs: 'list' the open tabs, open a 'new' one (url), 'switch' to a tab by index, or 'close' one.",
            {"action": {"type": "string", "enum": ["new", "list", "switch", "close"]},
             "url": {"type": "string"}, "index": {"type": "integer"}}, ["action"]),
            h_tab, available),
        ("bridge_wait", _schema("bridge_wait", "Wait a moment for the page to settle (milliseconds, max 15000).",
            {"ms": {"type": "integer"}}), h_wait, available),
        ("bridge_current_url", _schema("bridge_current_url", "Get the current tab's URL and title."),
            h_current_url, available),
    ]

    for name, schema, handler, check_fn in tools:
        ctx.register_tool(
            name=name,
            toolset="hermes-connector",
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            description=schema["description"],
        )
