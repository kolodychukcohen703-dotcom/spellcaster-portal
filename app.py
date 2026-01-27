
import os
from flask_socketio import SocketIO

# Import the Spellcaster Portal Flask app (routes/templates/etc.)
from spellcaster_portal import app as app  # noqa

# Add Socket.IO (needed for the World Chatbot)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=os.getenv("SOCKETIO_ASYNC", "eventlet"))

# Mount the World Chatbot under /world
from world_chatbot.blueprint import init_world_chatbot  # noqa
init_world_chatbot(app, socketio, url_prefix="/world")

# Convenience redirect
@app.get("/world_chatbot")
def _world_chatbot_redirect():
    from flask import redirect
    return redirect("/world/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
