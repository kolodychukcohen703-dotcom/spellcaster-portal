
import os
import uuid
from typing import Dict, Optional

from flask import Blueprint, render_template, request
from flask_socketio import SocketIO, emit

from .world_engine import Engine


def init_world_chatbot(app, socketio: SocketIO, url_prefix: str = "/world") -> Blueprint:
    """Attach the Sentinel World Chatbot under a URL prefix and register Socket.IO handlers."""

    bp = Blueprint(
        "world_chatbot",
        __name__,
        template_folder="templates",
        static_folder="static",
        url_prefix=url_prefix,
    )

    engine = Engine()

    # Simple per-session user registry
    users: Dict[str, Dict] = {}

    @bp.get("/")
    def index():
        return render_template("index.html", title="Sentinel World Chatbot")

    # Namespace for world chat (so it doesn't collide with any future socket events)
    NAMESPACE = "/world"

    @socketio.on("connect", namespace=NAMESPACE)
    def on_connect():
        sid = request.sid
        users[sid] = {"name": f"Guest-{sid[:4]}"}
        emit(
            "msg",
            {
                "user": "System",
                "body": f"Connected as {users[sid]['name']}. Type !help for commands.",
                "kind": "system",
                "ts": engine.now_ms(),
            },
        )
        emit("state", engine.state_payload(user=users[sid]["name"]))
        socketio.emit("user_count", {"count": len(users)}, namespace=NAMESPACE)

    @socketio.on("disconnect", namespace=NAMESPACE)
    def on_disconnect():
        users.pop(request.sid, None)
        socketio.emit("user_count", {"count": len(users)}, namespace=NAMESPACE)

    @socketio.on("chat", namespace=NAMESPACE)
    def on_chat(payload):
        sid = request.sid
        name = users.get(sid, {}).get("name", "Guest")
        body = (payload.get("body") or "").rstrip()
        if not body:
            return

        if body.startswith("!") or engine.wizard_active(sid):
            msgs, state_changed = engine.handle_input(
                sid=sid,
                user=name,
                text=body,
                online_users=[u["name"] for u in users.values()],
            )
            for m in msgs:
                emit("msg", {**m, "ts": engine.now_ms()})
            if state_changed:
                emit("state", engine.state_payload(user=name))
            return

        socketio.emit(
            "msg",
            {"user": name, "body": body, "kind": "chat", "ts": engine.now_ms()},
            namespace=NAMESPACE,
        )

    @socketio.on("set_name", namespace=NAMESPACE)
    def on_set_name(payload):
        sid = request.sid
        new = (payload.get("name") or "").strip()
        if not new:
            emit(
                "msg",
                {"user": "System", "body": "Name cannot be blank.", "kind": "system", "ts": engine.now_ms()},
            )
            return
        new = new[:24]
        old = users.get(sid, {}).get("name", "Guest")
        users[sid] = {"name": new}
        socketio.emit(
            "msg",
            {"user": "System", "body": f"{old} is now {new}.", "kind": "system", "ts": engine.now_ms()},
            namespace=NAMESPACE,
        )
        socketio.emit("user_count", {"count": len(users)}, namespace=NAMESPACE)
        emit("state", engine.state_payload(user=new))

    app.register_blueprint(bp)
    return bp
