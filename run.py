# run.py - Entry point for the server
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import eventlet
eventlet.monkey_patch(all=True)

from server import app, socketio
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[+] Starting server on http://0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
