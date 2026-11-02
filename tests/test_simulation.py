"""End-to-end: the outage simulation never drops below the reserve floor,
and the demo Q&A is grounded in fake fleet state. Plus HTTP smoke tests."""
import json
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from tesla_power_share.config import Settings, VehicleConfig
from tesla_power_share.power import VehicleState
from tesla_power_share.server import make_handler
from tesla_power_share.service import PowerShareService
from tesla_power_share.simulator import demo_vehicles, run_demo, simulate_outage


def _settings(**kw):
    return Settings(vehicles=[VehicleConfig("Model Y", "VINY", 75.0),
                              VehicleConfig("Model 3", "VIN3", 57.0)],
                    ai_mode="never", **kw)


def test_outage_simulation_never_below_reserve():
    """Core invariant: every hour line stays at/above the 20% floor."""
    lines = simulate_outage(demo_vehicles()[0], outage_hours=6.0, reserve_soc=20.0)
    for line in lines:
        m = re.search(r"car at (\d+)%", line)
        if m:
            assert int(m.group(1)) >= 20
    assert any("Outage covered" in l or "held at its 20% floor" in l for l in lines)


def test_demo_qa_grounded_and_reserve_change_persists():
    results = run_demo(_settings())
    answers = [a for _, a, _ in results]
    assert any("Model Y" in a and "82%" in a for a in answers)
    assert any("30%" in a for a in answers)  # reserve question answered
    final_log = results[-1][2]
    assert ("discharge_set_reserve", "30") in final_log


def _service(**kw):
    states = [VehicleState("Model Y", "VINY", 82, 75.0),
              VehicleState("Model 3", "VIN3", 47, 57.0)]
    return PowerShareService(_settings(**kw), state_provider=lambda: states)


def test_http_chat_roundtrip():
    service = _service()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"model": "tesla-power-share", "messages": [
            {"role": "user", "content": "how long can my Model Y power my home?"}]}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                     data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        assert "Model Y" in data["choices"][0]["message"]["content"]

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models",
                                    timeout=10) as resp:
            models = json.loads(resp.read())
        assert models["data"][0]["id"] == "tesla-power-share"

        body = json.dumps({"input": "hello fleet"}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/embeddings",
                                     data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            emb = json.loads(resp.read())
        assert len(emb["data"][0]["embedding"]) == 384
    finally:
        httpd.shutdown()


def test_http_auth_required_when_key_set():
    service = _service(server_api_key="secret")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/models",
            headers={"Authorization": "Bearer secret"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
    finally:
        httpd.shutdown()
