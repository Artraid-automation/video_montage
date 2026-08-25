#!/usr/bin/env python3
"""
CodexBridge - local Resolve bridge for the AI video pipeline.

Run from DaVinci Resolve: Workspace > Scripts > CodexBridge.
The HTTP listener runs on a worker thread; every Resolve API call is marshalled
back into Fusion's UI dispatcher so PyRemoteObject stays valid.
"""

import json
import threading
import traceback
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HOST = "127.0.0.1"
PORT = 9876
VERSION = "0.2.0"

resolve_api = globals().get("resolve")
if resolve_api is None:
    app_api = globals().get("app")
    if app_api is not None:
        resolve_api = app_api.GetResolve()
if resolve_api is None:
    raise RuntimeError("Resolve did not inject its scripting API object")

bmd_api = globals().get("bmd")
if bmd_api is None:
    import DaVinciResolveScript as bmd_api

# Resolve exposes the live UI manager only in a Fusion scripting context on
# some builds. Probe the current context first; if needed, switch pages
# programmatically, acquire the manager, and restore the user's page.
def find_ui_manager():
    candidates = (
        ("fu", globals().get("fu")),
        ("fusion", globals().get("fusion")),
        ("resolve.Fusion", resolve_api.Fusion()),
        ("bmd.scriptapp", bmd_api.scriptapp("Fusion")),
    )
    for source, candidate in candidates:
        if candidate is None:
            continue
        manager = getattr(candidate, "UIManager", None)
        if manager is not None:
            return candidate, manager, source
    return None, None, None


original_page = resolve_api.GetCurrentPage()
fusion_api, ui, ui_source = find_ui_manager()
if ui is None:
    resolve_api.OpenPage("fusion")
    import time
    time.sleep(1.5)
    fusion_api, ui, ui_source = find_ui_manager()
if ui is None:
    raise RuntimeError(
        "Resolve exposed no Fusion UIManager even after opening the Fusion page"
    )

# Validate while still in the Workspace script callback.
project_manager = resolve_api.GetProjectManager()
if project_manager is None:
    raise RuntimeError("Resolve API is present but GetProjectManager() failed")
startup_project = project_manager.GetCurrentProject()
startup_name = startup_project.GetName() if startup_project is not None else "(no project)"

dispatcher = bmd_api.UIDispatcher(ui)
window = dispatcher.AddWindow(
    {
        "ID": "CodexBridge",
        "WindowTitle": "AI Codex Bridge",
        "Geometry": [120, 120, 460, 150],
    },
    ui.VGroup([
        ui.Label({
            "ID": "Status",
            "Text": "AI Codex Bridge is running on 127.0.0.1:9876",
            "Alignment": {"AlignCenter": True},
        }),
        ui.Label({
            "ID": "Project",
            "Text": "Project: " + str(startup_name),
            "Alignment": {"AlignCenter": True},
        }),
        ui.Button({"ID": "Stop", "Text": "Stop bridge"}),
    ]),
)

_pending = {}
_pending_lock = threading.Lock()
server = None


def safe(call):
    try:
        return call()
    except Exception:
        return None


def project_context():
    pm = resolve_api.GetProjectManager()
    if pm is None:
        raise RuntimeError("No project manager")
    project = pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("No project open")
    return pm, project


def route_status(_args):
    pm = resolve_api.GetProjectManager()
    project = pm.GetCurrentProject() if pm is not None else None
    return {
        "connected": True,
        "apiReady": pm is not None,
        "bridgeVersion": VERSION,
        "bridge": "CodexBridge",
        "uiSource": ui_source,
        "product": safe(lambda: resolve_api.GetProductName()),
        "version": safe(lambda: resolve_api.GetVersionString()),
        "project": safe(lambda: project.GetName()) if project is not None else None,
    }


def route_project(_args):
    _pm, project = project_context()
    keys = (
        "timelineResolutionWidth",
        "timelineResolutionHeight",
        "timelineFrameRate",
        "timelinePlaybackFrameRate",
        "colorScienceMode",
    )
    settings = {}
    for key in keys:
        value = safe(lambda key=key: project.GetSetting(key))
        if value not in (None, ""):
            settings[key] = value
    return {
        "name": safe(lambda: project.GetName()),
        "timelineCount": safe(lambda: project.GetTimelineCount()),
        "settings": settings,
    }


def route_page(_args):
    return {"page": resolve_api.GetCurrentPage()}


def route_timeline(_args):
    _pm, project = project_context()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No timeline open")
    video_tracks = safe(lambda: timeline.GetTrackCount("video")) or 0
    audio_tracks = safe(lambda: timeline.GetTrackCount("audio")) or 0
    return {
        "name": safe(lambda: timeline.GetName()),
        "startFrame": safe(lambda: timeline.GetStartFrame()),
        "endFrame": safe(lambda: timeline.GetEndFrame()),
        "currentTimecode": safe(lambda: timeline.GetCurrentTimecode()),
        "videoTrackCount": video_tracks,
        "audioTrackCount": audio_tracks,
    }


ROUTES = {
    ("GET", "/status"): route_status,
    ("GET", "/project"): route_project,
    ("GET", "/page"): route_page,
    ("GET", "/timeline"): route_timeline,
}


class Ticket:
    def __init__(self, handler, args):
        self.handler = handler
        self.args = args
        self.done = threading.Event()
        self.result = None
        self.error = None


def dispatch_to_resolve(handler, args):
    request_id = uuid.uuid4().hex
    ticket = Ticket(handler, args)
    with _pending_lock:
        _pending[request_id] = ticket
    window.QueueEvent("BridgeRequest", {"request_id": request_id})
    if not ticket.done.wait(20):
        with _pending_lock:
            _pending.pop(request_id, None)
        raise TimeoutError("Resolve UI dispatcher did not process the request")
    if ticket.error:
        raise RuntimeError(ticket.error)
    return ticket.result


def on_bridge_request(event):
    request_id = event.get("request_id")
    with _pending_lock:
        ticket = _pending.pop(request_id, None)
    if ticket is None:
        return
    try:
        ticket.result = ticket.handler(ticket.args)
    except Exception:
        ticket.error = traceback.format_exc()
    finally:
        ticket.done.set()


def stop_bridge(_event=None):
    if server is not None:
        threading.Thread(target=server.shutdown, daemon=True).start()
    dispatcher.ExitLoop()


window.On.CodexBridge.BridgeRequest = on_bridge_request
window.On.CodexBridge.Close = stop_bridge
window.On.Stop.Click = stop_bridge


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def respond(self, status, data):
        raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        handler = ROUTES.get(("GET", path))
        if handler is None:
            self.respond(404, {"error": "Unsupported endpoint: " + path})
            return
        try:
            result = dispatch_to_resolve(handler, parse_qs(parsed.query))
            self.respond(200, result)
        except Exception:
            self.respond(500, {"error": traceback.format_exc()})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/bridge/shutdown":
            self.respond(200, {"success": True})
            window.QueueEvent("BridgeStop", {})
            return
        self.respond(404, {"error": "Unsupported endpoint: " + path})


window.On.CodexBridge.BridgeStop = stop_bridge

# Stop the legacy bridge if it owns the port.
try:
    import urllib.request
    request = urllib.request.Request(
        "http://127.0.0.1:9876/bridge/shutdown",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=2).read()
except Exception:
    pass

import time
time.sleep(1.0)
server = ThreadingHTTPServer((HOST, PORT), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

window.Show()
if original_page and original_page != "fusion":
    resolve_api.OpenPage(original_page)
dispatcher.RunLoop()
window.Hide()
server.server_close()
