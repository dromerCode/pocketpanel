from fastapi import WebSocket


async def until_disconnect(ws: WebSocket):
    while True:
        if (await ws.receive())["type"] == "websocket.disconnect":
            return
