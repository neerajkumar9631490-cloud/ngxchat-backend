import os
import random
import string
import time
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config["SECRET_KEY"] = "darkweb-chat-secret-2024"

# -------------------- CORS headers --------------------
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    return response

@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    response = app.make_default_options_response()
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    return response
# -----------------------------------------------------

# ... (the rest of your data structures, endpoints, and socketio code remains identical) ...
# ==================== Data Structures ====================
connected_users = {}        # sid -> {"username": str, "room": str, "joined_at": int}
user_sids = {}              # username -> set(sid)   for multi-tab
rooms = {}                  # room_name -> set(sid)
typing_per_room = {}        # room_name -> {sid: username}
admin_rooms = set()         # sids of admin pages

GLOBAL_ROOM = "global"
rooms[GLOBAL_ROOM] = set()

def timestamp():
    return int(time.time() * 1000)

def generate_room_code(length=6):
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if code not in rooms:
            return code

def broadcast_room_user_list(room_name):
    if room_name not in rooms:
        return
    unique_users = list({connected_users[sid]["username"] for sid in rooms[room_name] if sid in connected_users})
    socketio.emit("user_list", {
        "users": unique_users,
        "count": len(unique_users)
    }, room=room_name)

def broadcast_system_message(room_name, text, msg_type=""):
    socketio.emit("system_message", {
        "text": text,
        "type": msg_type,
        "timestamp": timestamp(),
    }, room=room_name)

def remove_user_from_room(sid):
    if sid not in connected_users:
        return
    username = connected_users[sid]["username"]
    old_room = connected_users[sid]["room"]

    if old_room in rooms and sid in rooms[old_room]:
        rooms[old_room].discard(sid)
        leave_room(old_room, sid)

        if username in user_sids and len(user_sids[username]) == 1:
            broadcast_system_message(old_room, f"{username} left the channel.", "leave")
        broadcast_room_user_list(old_room)

        if old_room != GLOBAL_ROOM and len(rooms[old_room]) == 0:
            del rooms[old_room]
            if old_room in typing_per_room:
                del typing_per_room[old_room]

    if old_room in typing_per_room:
        typing_per_room[old_room].pop(sid, None)
        typing_list = list({typing_per_room[old_room][s] for s in typing_per_room[old_room]})
        socketio.emit("typing_update", {"users": typing_list}, room=old_room)

def add_user_to_room(sid, new_room):
    if sid not in connected_users:
        return
    username = connected_users[sid]["username"]
    if new_room not in rooms:
        rooms[new_room] = set()
    rooms[new_room].add(sid)
    connected_users[sid]["room"] = new_room
    join_room(new_room, sid)

    if username in user_sids and len(user_sids[username]) == 1:
        broadcast_system_message(new_room, f"{username} joined the channel.", "join")
    broadcast_room_user_list(new_room)

def switch_user_room(sid, new_room):
    if sid not in connected_users:
        return False
    old_room = connected_users[sid]["room"]
    if old_room == new_room:
        return True
    remove_user_from_room(sid)
    add_user_to_room(sid, new_room)
    return True

def get_user_room(sid):
    if sid in connected_users:
        return connected_users[sid]["room"]
    return None

def update_typing_status(sid, is_typing):
    if sid not in connected_users:
        return
    room = get_user_room(sid)
    if not room:
        return
    username = connected_users[sid]["username"]
    if room not in typing_per_room:
        typing_per_room[room] = {}
    if is_typing:
        typing_per_room[room][sid] = username
    else:
        typing_per_room[room].pop(sid, None)
    typing_users_list = list({typing_per_room[room][s] for s in typing_per_room[room]})
    socketio.emit("typing_update", {"users": typing_users_list}, room=room)

# ==================== REST API Endpoints ====================
@app.route('/ping')
def ping():
    return jsonify({
        "status": "ok",
        "path": os.path.dirname(os.path.abspath(__file__))
    })

@app.route('/api/online')
def api_online():
    unique_usernames = list({data["username"] for data in connected_users.values()})
    return jsonify({"users": unique_usernames})

# ==================== Admin Monitoring Helpers ====================
def emit_admin_log(message, log_type="info", user_count=None, latency=None):
    data = {"message": message, "type": log_type}
    if user_count is not None:
        data["userCount"] = user_count
    if latency is not None:
        data["latency"] = latency
    for sid in admin_rooms:
        socketio.emit("admin_log", data, room=sid)

# ==================== Socket.IO Events ====================
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    logger=True,
    engineio_logger=True,
)

@socketio.on("connect")
def handle_connect():
    sid = request.sid
    print(f"[+] Connected: {sid}")
    emit_admin_log(f"New client connected: {sid}", "info")

@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    if sid in connected_users:
        username = connected_users[sid]["username"]
        room = get_user_room(sid)

        if room and room in typing_per_room:
            typing_per_room[room].pop(sid, None)
            typing_list = list({typing_per_room[room][s] for s in typing_per_room[room]})
            socketio.emit("typing_update", {"users": typing_list}, room=room)

        remove_user_from_room(sid)

        if username in user_sids:
            user_sids[username].discard(sid)
            if len(user_sids[username]) == 0:
                del user_sids[username]

        del connected_users[sid]
        unique_users = len({data["username"] for data in connected_users.values()})
        emit_admin_log(f"User '{username}' disconnected. (Total online: {unique_users})", "warn", user_count=unique_users)
        print(f"[-] {username} disconnected")
    elif sid in admin_rooms:
        admin_rooms.discard(sid)
        emit_admin_log("Admin monitoring disconnected", "warn")

@socketio.on("admin_join")
def handle_admin_join():
    sid = request.sid
    admin_rooms.add(sid)
    unique_users = len({data["username"] for data in connected_users.values()})
    emit_admin_log(f"Admin panel connected. Active users: {unique_users}", "success", user_count=unique_users)
    print(f"[ADMIN] Monitoring connected from {sid}")

@socketio.on("admin_ping")
def handle_admin_ping(data):
    sid = request.sid
    socketio.emit("admin_pong", {"time": data["time"]}, room=sid)

@socketio.on("join")
def handle_join(data):
    sid = request.sid
    username = data.get("username", "").strip()
    if not username or len(username) > 20:
        emit("join_error", {"message": "Invalid username"})
        return

    connected_users[sid] = {
        "username": username,
        "joined_at": timestamp(),
        "room": GLOBAL_ROOM
    }
    if username not in user_sids:
        user_sids[username] = set()
    user_sids[username].add(sid)

    rooms[GLOBAL_ROOM].add(sid)
    join_room(GLOBAL_ROOM, sid)

    if len(user_sids[username]) == 1:
        broadcast_system_message(GLOBAL_ROOM, f"{username} joined the chat.", "join")
    broadcast_room_user_list(GLOBAL_ROOM)

    unique_users = len({data["username"] for data in connected_users.values()})
    emit_admin_log(f"User '{username}' joined the chat. (Total online: {unique_users})", "event", user_count=unique_users)

    emit("join_success", {"username": username})
    print(f"[+] {username} joined (global), total tabs: {len(user_sids[username])}")

@socketio.on("message")
def handle_message(data):
    sid = request.sid
    if sid not in connected_users:
        return
    text = data.get("text", "").strip()
    if not text:
        return
    username = connected_users[sid]["username"]
    room = get_user_room(sid)
    if not room:
        return
    socketio.emit("message", {
        "username": username,
        "text": text,
        "timestamp": timestamp(),
    }, room=room)
    short_text = text[:50] + ("..." if len(text) > 50 else "")
    emit_admin_log(f"Message from '{username}': {short_text}", "info")

@socketio.on("typing")
def handle_typing(data):
    sid = request.sid
    if sid not in connected_users:
        return
    is_typing = data.get("typing", False)
    update_typing_status(sid, is_typing)
    username = connected_users[sid]["username"]
    if is_typing:
        emit_admin_log(f"User '{username}' is typing...", "info")

@socketio.on("create_room")
def handle_create_room():
    sid = request.sid
    if sid not in connected_users:
        return
    room_code = generate_room_code()
    switch_user_room(sid, room_code)
    emit("room_created", {"room_code": room_code})
    socketio.emit("system_message", {
        "text": f"Private room created. Share code: {room_code}",
        "type": "",
        "timestamp": timestamp()
    }, room=room_code)
    emit_admin_log(f"User '{connected_users[sid]['username']}' created private room: {room_code}", "event")

@socketio.on("join_room")
def handle_join_room(data):
    sid = request.sid
    if sid not in connected_users:
        return
    room_code = data.get("room", "").strip().upper()
    if not room_code:
        emit("room_error", {"message": "Invalid room code"})
        return
    if room_code not in rooms:
        emit("room_error", {"message": "Room not found"})
        return
    switch_user_room(sid, room_code)
    emit("room_joined", {"room_code": room_code})
    emit_admin_log(f"User '{connected_users[sid]['username']}' joined private room: {room_code}", "event")

@socketio.on("join_global")
def handle_join_global():
    sid = request.sid
    if sid not in connected_users:
        return
    if get_user_room(sid) == GLOBAL_ROOM:
        emit("room_joined", {"room_code": None})
        return
    switch_user_room(sid, GLOBAL_ROOM)
    emit("room_joined", {"room_code": None})
    emit_admin_log(f"User '{connected_users[sid]['username']}' returned to global chat", "event")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[+] Starting Darknet server on http://0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port)
