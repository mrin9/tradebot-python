import socketio

# Shared Socket.IO Server Instance
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
