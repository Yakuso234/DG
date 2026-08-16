"""S5 A2A 边界：5a 内存 transport（必须），5b HTTP 跨进程（尽力而为）。"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from b_langgraph.a2a_agent import (
    AGENT_NAME,
    build_agent_card,
    build_http_app,
    send_message_in_memory,
)


@pytest.mark.scenario("S5a")
def test_s5a_agent_card_and_message_send_roundtrip() -> None:
    card = build_agent_card()
    assert card.name == AGENT_NAME
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"

    structured = send_message_in_memory("investigate T-1001")
    # 收到可 JSON 解析的结构化响应。
    json.loads(json.dumps(structured))
    assert structured["action"] == "restart_pipeline"
    assert structured["ticket_id"] == "T-1001"
    assert structured["risk"] == "high"


@pytest.mark.scenario("S5b")
def test_s5b_http_cross_process_roundtrip() -> None:
    """尽力而为：把同一 Agent 以 HTTP 暴露到本机端口，用官方客户端往返一次。"""
    import asyncio

    import uvicorn
    from a2a.client import create_client
    from a2a.types import SendMessageConfiguration, SendMessageRequest

    from b_langgraph.a2a_agent import new_user_message

    # 找一个空闲端口。
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    url = f"http://127.0.0.1:{port}"
    card = build_agent_card(url=url)
    app = build_http_app(card)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # 等待服务器就绪（轮询端口连通）。
    deadline = time.monotonic() + 15
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            if time.monotonic() > deadline:
                server.should_exit = True
                raise RuntimeError("uvicorn 未能及时就绪")
            time.sleep(0.1)

    try:
        async def _roundtrip():
            client = await create_client(url)
            try:
                request = SendMessageRequest(
                    message=new_user_message("investigate T-1001"),
                    configuration=SendMessageConfiguration(),
                )
                responses = [sr async for sr in client.send_message(request)]
            finally:
                await client.close()
            assert len(responses) == 1
            sr = responses[0]
            assert sr.HasField("message")
            data_parts = [
                p for p in sr.message.parts if p.HasField("data")
            ]
            assert data_parts, "no structured data part"
            from google.protobuf import json_format

            return json.loads(json.dumps(json_format.MessageToDict(data_parts[0].data)))

        structured = asyncio.run(_roundtrip())
        assert structured["action"] == "restart_pipeline"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
