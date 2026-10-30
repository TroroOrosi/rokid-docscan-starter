"""Offline wire checks: phone-local HTTP only, never a Work/account connection."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from app import work_mcp


KEY = "offline-test-key-do-not-echo"
JOB = "work-test"
SOURCE = "page-1"


def png():
    stream = io.BytesIO()
    Image.new("RGB", (12, 9), "white").save(stream, format="PNG")
    return stream.getvalue()


def request(method, params=None, *, rid=1):
    value = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        value["params"] = params
    return value


def wire(server, *messages):
    data = b"".join(json.dumps(item).encode() + b"\n" for item in messages)
    output = io.BytesIO()
    server.serve(io.BytesIO(data), output)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def initialize(server, version="2025-11-25"):
    replies = wire(server, request("initialize", {
        "protocolVersion": version, "capabilities": {},
        "clientInfo": {"name": "offline-test", "version": "1"},
    }), {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return replies[0]


@contextmanager
def phone(routes):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.reply()

        def do_POST(self):
            self.reply()

        def reply(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.command, self.path, self.headers.get("Authorization"), data))
            status, headers, body = (routes(self.command, self.path, data) if callable(routes)
                                     else routes.get((self.command, self.path), (404, {}, b"missing")))
            if isinstance(body, dict):
                body = json.dumps(body).encode()
                headers = {"Content-Type": "application/json", **headers}
            self.send_response(status)
            for name, value in {"Content-Length": str(len(body)), **headers}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield work_mcp.LocalWorkClient(port=httpd.server_port, api_key=KEY), calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def routes_for_image(data=None):
    data = data or png()
    digest = hashlib.sha256(data).hexdigest()
    capture = {"session_id": "1", "capture_id": SOURCE, "generation": 2,
               "page_turn": 1, "revision": 1, "rotation": 0, "source_sha256": digest}
    manifest = {"job_id": JOB, "generation": 2, "manifest_sha256": "a" * 64,
                "sources": [{"source_id": SOURCE, "mime_type": "image/png", "sha256": digest,
                             "bytes": len(data), "page_number": 1}],
                "model_selection_verified": False, "visual_reading_verified": False}
    quality = {"schema": 1, "capture": capture, "inspection_manifest_sha256": "b" * 64,
               "images": [{"image_id": "tile-1", "mime_type": "image/png", "sha256": digest,
                           "scale": "native", "box_upright_pixels": [0, 0, 12, 9]}]}
    root = f"/v1/work/jobs/{JOB}"
    return {
        ("GET", "/v1/work/jobs?cursor=0&limit=20"): (200, {}, {"jobs": [manifest], "next_cursor": None}),
        ("GET", root): (200, {}, manifest),
        ("GET", f"{root}/sources/{SOURCE}/quality"): (200, {}, quality),
        ("GET", f"{root}/sources/{SOURCE}/quality/images/tile-1"):
            (200, {"Content-Type": "image/png", "X-Work-Source-SHA256": digest,
                   "X-Work-Source-Receipt": "receipt-test"}, data),
        ("GET", f"{root}/sources/{SOURCE}"):
            (200, {"Content-Type": "image/png", "X-Work-Source-SHA256": digest,
                   "X-Work-Source-Receipt": "original-receipt"}, data),
    }


def call(server, name, arguments, rid=3):
    return wire(server, request("tools/call", {"name": name, "arguments": arguments}, rid=rid))[0]


def test_initialize_tools_and_ping_are_mcp_and_mutations_are_not_read_only():
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        reply = initialize(server)
        assert reply["result"]["protocolVersion"] == "2025-11-25"
        assert reply["result"]["capabilities"] == {"tools": {"listChanged": False}}
        assert "events" not in reply["result"]["capabilities"]
        tools = wire(server, request("tools/list"))[0]["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        assert by_name["rokid_view_image"]["annotations"]["readOnlyHint"] is True
        assert by_name["rokid_submit_quality"]["annotations"]["readOnlyHint"] is False
        assert by_name["rokid_submit_answers"]["annotations"]["readOnlyHint"] is False
        assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)
        assert wire(server, request("ping"))[0]["result"] == {}
        assert calls == []


def test_png_is_exact_image_content_with_source_bound_delivery_receipt(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://unreachable.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "http://unreachable.invalid")
    with phone(routes_for_image()) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        reply = call(server, "rokid_view_image", {"job_id": JOB, "source_id": SOURCE, "image_id": "tile-1"})
        result = reply["result"]
        image = next(item for item in result["content"] if item["type"] == "image")
        assert base64.b64decode(image["data"], validate=True) == png()
        assert image["mimeType"] == "image/png"
        metadata = json.loads(result["content"][0]["text"])
        assert metadata["image_receipt"] == {"image_id": "tile-1", "sha256": hashlib.sha256(png()).hexdigest(),
                                             "receipt": "receipt-test"}
        assert metadata["source_sha256"] == hashlib.sha256(png()).hexdigest()
        assert metadata["visual_reading_verified"] is False
        assert metadata["scale"] == "native"
        assert KEY not in json.dumps(reply)
        assert all(item[2] == "Bearer " + KEY for item in calls)


@pytest.mark.parametrize("arguments", [
    {"job_id": JOB, "source_id": SOURCE, "image_id": "tile-1", "url": "https://example.com"},
    {"job_id": "../x", "source_id": SOURCE, "image_id": "tile-1"},
    {"job_id": JOB, "source_id": SOURCE, "image_id": False},
    {"job_id": JOB, "source_id": SOURCE},
])
def test_strict_tool_arguments_never_reach_http(arguments):
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, "rokid_view_image", arguments)["result"]
        assert result["isError"] is True
        assert calls == []


@pytest.mark.parametrize("name,arguments", [
    ("rokid_list_jobs", {"cursor": True}),
    ("rokid_list_jobs", {"cursor": "0"}),
    ("rokid_list_jobs", {"cursor": 0.0}),
    ("rokid_list_jobs", {"limit": False}),
    ("rokid_list_jobs", {"limit": 0}),
    ("rokid_list_jobs", {"limit": 101}),
    ("rokid_get_job", {"job_id": 1}),
    ("rokid_get_job", {"job_id": JOB + "\n"}),
    ("rokid_submit_quality", {"job_id": JOB, "source_id": SOURCE, "response": [], "image_receipts": []}),
])
def test_strict_tool_primitives_and_quality_containers_never_reach_http(name, arguments):
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, name, arguments)["result"]
        assert json.loads(result["content"][0]["text"]) == {"error": "invalid_tool_arguments"}
        assert result["isError"] is True and calls == []


def _answer_arguments():
    return {"job_id": JOB, "manifest_sha256": "a" * 64, "generation": 2, "conversation_id": "chat",
            "source_receipts": [{"source_id": SOURCE, "sha256": "b" * 64, "receipt": "test-receipt"}],
            "result": {"questions": []}}


@pytest.mark.parametrize("field,value", [
    ("response", []), ("response", [["approved", True]]),
    ("image_receipts", {}), ("image_receipts", []),
    ("image_receipts", [[["image_id", "tile-1"], ["sha256", "d" * 64], ["receipt", "test-receipt"]]]),
])
def test_quality_objects_and_receipt_objects_are_not_coerced(field, value):
    arguments = {"job_id": JOB, "source_id": SOURCE, "response": {"observed": True},
                  "image_receipts": [{"image_id": "tile-1", "sha256": "d" * 64, "receipt": "test-receipt"}],
                  field: value}
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, "rokid_submit_quality", arguments)["result"]
        assert json.loads(result["content"][0]["text"]) == {"error": "invalid_tool_arguments"}
        assert result["isError"] is True and calls == []


@pytest.mark.parametrize("field,value", [
    ("generation", True), ("generation", "2"), ("generation", 2.0),
    ("conversation_id", 1), ("result", []), ("result", [["questions", []]]),
    ("source_receipts", []), ("source_receipts", {}),
    ("source_receipts", [[["source_id", SOURCE], ["sha256", "b" * 64], ["receipt", "test-receipt"]]]),
    ("source_receipts", [{"source_id": SOURCE, "sha256": "b" * 64 + "\n", "receipt": "test-receipt"}]),
    ("source_receipts", [{"source_id": SOURCE, "sha256": "b" * 64, "receipt": "test-receipt\n"}]),
    ("source_receipts", [{"source_id": SOURCE, "sha256": "b" * 64, "receipt": 123}]),
    ("source_receipts", [{"source_id": SOURCE, "sha256": "b" * 64, "receipt": "ok", "extra": 1}]),
])
def test_strict_answer_receipts_reject_coercion_before_any_http(field, value):
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        arguments = {**_answer_arguments(), field: value}
        result = call(server, "rokid_submit_answers", arguments)["result"]
        assert json.loads(result["content"][0]["text"]) == {"error": "invalid_tool_arguments"}
        assert result["isError"] is True and calls == []


@pytest.mark.parametrize("images", [
    [], {}, [[["image_id", "tile-1"], ["sha256", "d" * 64], ["receipt", "test-receipt"]]],
    [{"image_id": "tile-1", "sha256": "d" * 64, "receipt": "ok", "extra": 1}],
])
def test_tile_receipts_retain_strict_container_and_nested_extra_rules(images):
    arguments = _answer_arguments()
    arguments["source_receipts"] = [{"source_id": SOURCE, "sha256": "b" * 64,
        "delivery": "native_tiles", "inspection_manifest_sha256": "c" * 64, "image_receipts": images}]
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, "rokid_submit_answers", arguments)["result"]
        assert json.loads(result["content"][0]["text"]) == {"error": "invalid_tool_arguments"}
        assert result["isError"] is True and calls == []


def test_native_tile_receipts_keep_their_exact_schema_and_serialized_fields():
    arguments = _answer_arguments()
    arguments["source_receipts"] = [{"source_id": SOURCE, "sha256": "b" * 64,
        "delivery": "native_tiles", "inspection_manifest_sha256": "c" * 64,
        "image_receipts": [{"image_id": "tile-1", "sha256": "d" * 64, "receipt": "tile-receipt"}]}]
    routes = routes_for_image()
    routes["POST", f"/v1/work/jobs/{JOB}/result"] = 200, {}, {"accepted": True}
    with phone(routes) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        tools = wire(server, request("tools/list"))[0]["result"]["tools"]
        schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
        receipts = schemas["rokid_submit_answers"]["properties"]["source_receipts"]
        assert receipts["type"] == "array" and receipts["minItems"] == 1 and receipts["maxItems"] == 1000
        assert schemas["rokid_list_jobs"]["properties"]["limit"]["maximum"] == 100
        result = call(server, "rokid_submit_answers", arguments)["result"]
        assert result["isError"] is False
        posted = [json.loads(body) for method, _, _, body in calls if method == "POST"]
        assert posted == [{key: value for key, value in arguments.items() if key != "job_id"}]


def test_unknown_image_is_never_fetched():
    with phone(routes_for_image()) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, "rokid_view_image", {"job_id": JOB, "source_id": SOURCE, "image_id": "other"})
        assert result["result"]["isError"] is True
        assert not any("/images/" in item[1] for item in calls)


@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 429, 500])
def test_http_error_bodies_and_redirect_locations_are_never_disclosed(status):
    with phone({("GET", f"/v1/work/jobs/{JOB}"): (status, {"Location": "https://example.com/" + KEY},
                                                          (KEY + " private server exception").encode())}) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, "rokid_get_job", {"job_id": JOB})
        assert result["result"]["isError"] is True
        assert KEY not in json.dumps(result)
        assert "private server exception" not in json.dumps(result)
        assert len(calls) == 1


def test_uninitialized_and_malformed_wire_have_protocol_errors_without_echo():
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        assert wire(server, request("tools/list"))[0]["error"]["code"] == -32000
        output = io.BytesIO()
        server.serve(io.BytesIO(("{invalid " + KEY + "}\n").encode()), output)
        assert json.loads(output.getvalue())["error"]["code"] == -32700
        assert KEY.encode() not in output.getvalue()
        assert wire(server, [request("ping")])[0]["error"]["code"] == -32600
        assert calls == []


@pytest.mark.parametrize("version", ["2025-06-18", "2026-07-28", "future"])
def test_version_negotiation_never_advertises_unimplemented_protocols(version):
    with phone({}) as (client, _):
        reply = initialize(work_mcp.StdioServer(client), version)
        expected = version if version in work_mcp.SUPPORTED_PROTOCOL_VERSIONS else "2025-11-25"
        assert reply["result"]["protocolVersion"] == expected
        with pytest.raises(ValueError):
            work_mcp.StdioServer(client, protocol_versions=("2026-07-28",))


def test_initialized_notification_is_required_and_notifications_cannot_write():
    with phone({}) as (client, calls):
        server = work_mcp.StdioServer(client)
        first = request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                       "clientInfo": {"name": "test", "version": "1"}})
        assert "result" in wire(server, first)[0]
        assert wire(server, request("tools/list"))[0]["error"]["code"] == -32000
        assert wire(server, {"jsonrpc": "2.0", "method": "tools/call", "params": {
            "name": "rokid_submit_answers", "arguments": {}}}) == []
        assert wire(server, {"jsonrpc": "2.0", "method": "notifications/initialized",
                             "params": {"_meta": {"test": True}}}) == []
        assert wire(server, request("shutdown"))[0]["error"]["code"] == -32601
        assert calls == []


@pytest.mark.parametrize("headers,body", [
    ({"Content-Type": "application/json"}, b"[]"),
    ({"Content-Type": "text/html"}, b"<p>private</p>"),
    ({"Content-Type": "application/json"}, b'{"error":"' + KEY.encode() + b'"}'),
    ({"Content-Type": "application/json", "Content-Length": "200"}, b'{"partial":true}'),
    ({"Content-Type": "application/json", "Content-Length": str(work_mcp.MAX_JSON_BYTES + 1)}, b"{}"),
    ({"Content-Type": "application/json"}, b'{"nested":NaN}'),
])
def test_invalid_truncated_or_oversized_http_response_has_no_private_body(headers, body):
    with phone({("GET", f"/v1/work/jobs/{JOB}"): (200, headers, body)}) as (client, _):
        server = work_mcp.StdioServer(client)
        initialize(server)
        reply = call(server, "rokid_get_job", {"job_id": JOB})
        assert reply["result"]["isError"] is True
        assert KEY not in json.dumps(reply)
        assert "private" not in json.dumps(reply)


def test_transient_http_failure_does_not_cache_failure_or_retry_implicitly():
    attempts = 0
    routes = routes_for_image()

    def route(method, path, _):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return 503, {}, KEY.encode()
        return routes[method, path]

    with phone(route) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        assert call(server, "rokid_get_job", {"job_id": JOB})["result"]["isError"] is True
        assert len(calls) == 1
        assert call(server, "rokid_get_job", {"job_id": JOB})["result"]["isError"] is False
        assert len(calls) == 2


@pytest.mark.parametrize("status,body", [(500, b"private"), (200, b"{truncated")])
def test_write_failure_reports_uncertain_and_never_replays_the_post(status, body):
    routes = routes_for_image()
    routes["POST", f"/v1/work/jobs/{JOB}/result"] = status, {"Content-Type": "application/json"}, body
    with phone(routes) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        arguments = {"job_id": JOB, "manifest_sha256": "a" * 64, "generation": 2, "conversation_id": "chat",
                     "source_receipts": [{"source_id": SOURCE, "sha256": "b" * 64, "receipt": "test-receipt"}],
                     "result": {"questions": []}}
        reply = call(server, "rokid_submit_answers", arguments)
        assert "write_outcome_uncertain_query_job" in json.dumps(reply)
        assert sum(method == "POST" for method, *_ in calls) == 1
        assert "private" not in json.dumps(reply)


def test_small_original_is_exact_media_and_does_not_claim_visual_reading():
    with phone(routes_for_image()) as (client, _):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, "rokid_get_original", {"job_id": JOB, "source_id": SOURCE})["result"]
        assert base64.b64decode(result["content"][1]["data"]) == png()
        meta = json.loads(result["content"][0]["text"])
        assert meta["source_receipt"]["delivery"] == "original_bytes"
        assert meta["source_receipt"]["receipt"] == "original-receipt"
        assert meta["visual_reading_verified"] is False


@pytest.mark.parametrize("line", [b'{"jsonrpc":"2.0","id":1,"method":"ping"}', b"{", b"\xff\n",
                                    b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'{"x":1e999}\n'])
def test_truncated_or_non_json_input_has_a_bounded_parse_error(line):
    with phone({}) as (client, calls):
        output = io.BytesIO()
        work_mcp.StdioServer(client).serve(io.BytesIO(line), output)
        assert json.loads(output.getvalue())["error"]["code"] == -32700
        assert calls == []


def test_oversized_input_is_not_drained_or_interpreted_as_a_second_message(monkeypatch):
    monkeypatch.setattr(work_mcp, "MAX_REQUEST_BYTES", 40)
    with phone({}) as (client, calls):
        source = io.BytesIO(b" " * 100 + b"\n" + json.dumps(request("ping")).encode() + b"\n")
        output = io.BytesIO()
        assert work_mcp.StdioServer(client).serve(source, output) == 1
        assert len(output.getvalue().splitlines()) == 1
        assert source.tell() == 41
        assert calls == []


def test_entire_serialized_response_is_bounded_below_tunnel_ten_mib():
    with phone({}) as (client, _):
        server = work_mcp.StdioServer(client)
        output = io.BytesIO()
        huge = {"jsonrpc": "2.0", "id": 1, "result": {"content": [
            {"type": "text", "text": "é" * (work_mcp.TUNNEL_MAX_BYTES // 2)}]}}
        assert server._write(output, huge)
        encoded = output.getvalue()
        assert len(encoded) + work_mcp.TUNNEL_METADATA_RESERVE < work_mcp.TUNNEL_MAX_BYTES
        assert json.loads(encoded)["error"]["code"] == -32000
        assert b"\xc3\xa9" not in encoded


def test_original_larger_than_media_budget_uses_tiles_without_original_get():
    routes = routes_for_image()
    root = f"/v1/work/jobs/{JOB}"
    routes["GET", root][2]["sources"][0]["bytes"] = 15 * 1024 * 1024
    with phone(routes) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        error = call(server, "rokid_get_original", {"job_id": JOB, "source_id": SOURCE})
        assert "original_too_large_use_native_tiles" in json.dumps(error)
        image = call(server, "rokid_view_image", {"job_id": JOB, "source_id": SOURCE, "image_id": "tile-1"})
        assert base64.b64decode(image["result"]["content"][1]["data"]) == png()
        assert not any(item[1] == f"{root}/sources/{SOURCE}" for item in calls)


@pytest.mark.parametrize("change", ["body", "hash", "mime", "receipt"])
def test_invalid_media_is_never_returned_as_an_image(change):
    routes = routes_for_image()
    path = f"/v1/work/jobs/{JOB}/sources/{SOURCE}/quality/images/tile-1"
    status, headers, data = routes["GET", path]
    if change == "body":
        data += b"changed"
    if change == "hash":
        headers["X-Work-Source-SHA256"] = "c" * 64
    if change == "mime":
        headers["Content-Type"] = "text/plain"
    if change == "receipt":
        headers["X-Work-Source-Receipt"] = "invalid receipt"
    routes["GET", path] = status, headers, data
    with phone(routes) as (client, _):
        server = work_mcp.StdioServer(client)
        initialize(server)
        result = call(server, "rokid_view_image", {"job_id": JOB, "source_id": SOURCE, "image_id": "tile-1"})["result"]
        assert result["isError"] is True
        assert all(item["type"] == "text" for item in result["content"])


@pytest.mark.parametrize("port", [0, -1, 65536, True, "8000", 8000.0])
def test_loopback_configuration_cannot_accept_remote_hosts_or_invalid_ports(port):
    with pytest.raises(ValueError):
        work_mcp.LocalWorkClient(port=port, api_key=KEY)
    with pytest.raises(TypeError):
        work_mcp.LocalWorkClient(host="example.com", api_key=KEY)


def test_secret_redaction_also_covers_escaped_json_and_request_ids():
    key = 'special"\\key'
    client = work_mcp.LocalWorkClient(api_key=key)
    server = work_mcp.StdioServer(client)
    output = io.BytesIO()
    server._write(output, {"jsonrpc": "2.0", "id": key, "result": {"value": key}})
    assert json.loads(output.getvalue()) == {"jsonrpc": "2.0", "id": None,
                                             "error": {"code": -32603, "message": "Redacted internal response"}}


def test_module_process_has_only_protocol_stdout_and_exits_at_eof():
    env = {key: value for key, value in os.environ.items() if not key.startswith("ROKID_WORK_MCP_")}
    env["ROKID_API_KEY"] = KEY
    result = subprocess.run([sys.executable, "-m", "app.work_mcp"],
                            input=json.dumps(request("ping")).encode() + b"\n", capture_output=True,
                            env=env, timeout=10, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)["result"] == {}
    assert result.stderr == b""
    env.pop("ROKID_API_KEY")
    result = subprocess.run([sys.executable, "-m", "app.work_mcp"], input=b"", capture_output=True,
                            env=env, timeout=10, check=False)
    assert result.returncode == 2
    assert result.stdout == b""
    assert KEY.encode() not in result.stderr


def test_wire_restarts_keep_real_phone_receipts_and_result_idempotency(tmp_path):
    from app.work_bridge import WorkConflict, WorkStore

    store = WorkStore(tmp_path, validated_profiles=("offline-fixture",))
    job = store.enqueue(session_id=1, conversation_key="session:1", stage="single",
                        sources=[{"source_id": SOURCE, "page_number": 1, "data": png(), "mime_type": "image/png"}],
                        system="write answers only", prompt="all questions", generation=3)
    root = f"/v1/work/jobs/{job['job_id']}"

    def route(method, path, data):
        try:
            if method == "GET" and path == root:
                return 200, {}, store.get(job["job_id"])
            if method == "GET" and path == f"{root}/sources/{SOURCE}/quality":
                return 200, {}, store.quality_request(job["job_id"], SOURCE)
            if method == "GET" and "/quality/images/" in path:
                image, meta = store.read_quality_image(job["job_id"], SOURCE, path.rsplit("/", 1)[1])
                return 200, {"Content-Type": "image/png", "X-Work-Source-SHA256": meta["sha256"],
                             "X-Work-Source-Receipt": meta["receipt"]}, image
            if method == "POST" and path == f"{root}/sources/{SOURCE}/quality":
                return 200, {}, store.submit_quality(job["job_id"], SOURCE, **json.loads(data))
            if method == "POST" and path == f"{root}/result":
                return 200, {}, store.submit_result(job["job_id"], **json.loads(data))
        except WorkConflict:
            return 409, {}, b"stale or missing evidence"
        return 404, {}, b"missing"

    with phone(route) as (client, calls):
        server = work_mcp.StdioServer(client)
        initialize(server)
        args = {"job_id": job["job_id"], "source_id": SOURCE}
        quality = json.loads(call(server, "rokid_get_quality", args)["result"]["content"][0]["text"])
        receipts = []
        for descriptor in quality["images"]:
            result = call(server, "rokid_view_image", {**args, "image_id": descriptor["image_id"]})["result"]
            meta = json.loads(result["content"][0]["text"])
            assert hashlib.sha256(base64.b64decode(result["content"][1]["data"])).hexdigest() == descriptor["sha256"]
            receipts.append(meta["image_receipt"])
        evidence = {"schema": 1, "source_sha256": quality["capture"]["source_sha256"], "rotation": 0,
                    "inventory_complete": True, "profile_id": "offline-fixture", "layout": "single",
                    "pages": [{"id": "paper", "paper_bounds": "pass", "occlusion": "pass", "regions": [
                        {"id": "text", "kind": "text", "source_detail": "pass", "exposure": "pass", "readability": "pass"}]}]}
        response = {"schema": 1, "capture": quality["capture"],
                    "inspected_image_ids": [part["image_id"] for part in quality["images"]], "evidence": evidence}
        admitted = call(server, "rokid_submit_quality", {**args, "response": response, "image_receipts": receipts})
        assert json.loads(admitted["result"]["content"][0]["text"])["decision"] == "eligible"
        source_receipt = {"source_id": SOURCE, "sha256": job["sources"][0]["sha256"], "delivery": "native_tiles",
                          "inspection_manifest_sha256": quality["inspection_manifest_sha256"], "image_receipts": receipts}
        answers = {"job_id": job["job_id"], "manifest_sha256": job["manifest_sha256"], "generation": 3,
                   "conversation_id": "work-chat-1", "source_receipts": [source_receipt],
                   "result": {"questions": [{"group": "第1問", "label": "問1", "pages": [1], "answer_no": [1],
                                              "status": "ready", "answer": "x=2", "missing_material": "", "diagrams": []}]}}
        server = work_mcp.StdioServer(client)
        initialize(server)
        incomplete = {**answers, "source_receipts": [{**source_receipt, "image_receipts": receipts[:-1]}]}
        assert call(server, "rokid_submit_answers", incomplete)["result"]["isError"] is True
        first = call(server, "rokid_submit_answers", answers)["result"]
        assert first["isError"] is False
        completed = json.loads(first["content"][0]["text"])
        assert completed["status"] == "completed"
        assert completed["visual_reading_verified"] is False
        assert completed["cloud_transport_connected"] is False
        store = WorkStore(tmp_path, validated_profiles=("offline-fixture",))
        server = work_mcp.StdioServer(client)
        initialize(server)
        assert call(server, "rokid_submit_answers", answers)["result"] == first
        changed = {**answers, "conversation_id": "different-chat"}
        assert call(server, "rokid_submit_answers", changed)["result"]["isError"] is True
        assert store.result(job["job_id"])["questions"][0]["answer"] == "x=2"
        assert not any(path == f"{root}/sources/{SOURCE}" for _, path, _, _ in calls)
