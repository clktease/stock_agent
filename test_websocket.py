#!/usr/bin/env python3
"""Quick WebSocket smoke test – sends one query and prints all events."""
import asyncio, json
import websockets

async def test():
    uri = "ws://localhost:8000/ws"
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as ws:
        print("Connected! Sending test query...")
        await ws.send(json.dumps({"query": "What is AAPL current price?"}))

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "thinking":
                    print("  [thinking] Agent started...")
                elif t == "tool_call":
                    print(f"  [TOOL CALL] layer={msg['layer']} | tool={msg['tool']} | summary={msg.get('summary','')}")
                elif t == "tool_done":
                    print(f"  [TOOL DONE] elapsed={msg['elapsed_ms']}ms")
                elif t == "response":
                    content = msg['content'][:200].replace('\n', ' ')
                    print(f"  [RESPONSE] {content}...")
                elif t == "done":
                    print(f"  [DONE] Total elapsed: {msg['elapsed']}s")
                    break
                elif t == "error":
                    print(f"  [ERROR] {msg['message']}")
                    break
            except asyncio.TimeoutError:
                print("  [TIMEOUT] No response after 60s")
                break

asyncio.run(test())
