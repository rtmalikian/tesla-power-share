import math

from tesla_power_share.config import Settings, VehicleConfig
from tesla_power_share.power import VehicleState
from tesla_power_share.service import CAPABILITY_BLURB, PowerShareService


def make_service(ai_mode="never", llm=None):
    settings = Settings(vehicles=[VehicleConfig("Model Y", "VINY", 75.0),
                                  VehicleConfig("Model 3", "VIN3", 57.0)],
                        ai_mode=ai_mode)
    states = [VehicleState("Model Y", "VINY", 82, 75.0),
              VehicleState("Model 3", "VIN3", 47, 57.0)]
    service = PowerShareService(settings, state_provider=lambda: states,
                                llm_factory=(lambda: llm) if llm is not None else None)
    return service


def chat(service, text):
    body = {"model": "tesla-power-share",
            "messages": [{"role": "user", "content": text}]}
    return service.chat_completions(body)


def test_chat_shape():
    resp = chat(make_service(), "how long can my Model Y power my home?")
    assert resp["object"] == "chat.completion"
    msg = resp["choices"][0]["message"]
    assert msg["role"] == "assistant" and "Model Y" in msg["content"]
    assert resp["model"] == "tesla-power-share"


def test_runtime_answer_grounded_in_state():
    resp = chat(make_service(), "how long can my Model Y power my home?")
    content = resp["choices"][0]["message"]["content"]
    assert "82%" in content and "20%" in content  # reserve floor stated


def test_outage_plan_shortfall_or_cover():
    resp = chat(make_service(), "plan for a 6-hour outage")
    assert "6.0" in resp["choices"][0]["message"]["content"] or \
        "hours" in resp["choices"][0]["message"]["content"]


def test_set_reserve_updates_and_logs():
    service = make_service()
    resp = chat(service, "set my reserve to 30%")
    assert "30%" in resp["choices"][0]["message"]["content"]
    assert service.settings.reserve_soc == 30.0
    assert ("discharge_set_reserve", "30") in service.command_log


def test_set_reserve_out_of_range_rejected():
    service = make_service()
    chat(service, "set my reserve to 95%")
    assert service.settings.reserve_soc == 20.0


def test_models_shape():
    models = make_service().models_list()
    assert models["object"] == "list"
    assert models["data"][0]["id"] == "tesla-power-share"


def test_embeddings_shape_and_determinism():
    service = make_service()
    r1 = service.embeddings({"input": "outage plan model y"})
    r2 = service.embeddings({"input": "outage plan model y"})
    vec = r1["data"][0]["embedding"]
    assert len(vec) == 384
    assert vec == r2["data"][0]["embedding"]
    assert abs(math.sqrt(sum(x * x for x in vec)) - 1.0) < 1e-6


def test_embeddings_batch():
    r = make_service().embeddings({"input": ["one", "two"]})
    assert len(r["data"]) == 2 and r["data"][1]["index"] == 1


class FakeLlm:
    def __init__(self, reply):
        self.reply = reply
        self.seen_brief = ""

    def chat(self, brief, user_message):
        self.seen_brief = brief
        return self.reply


def test_llm_fallback_answer_gets_brief():
    llm = FakeLlm("The Model Y is your fuller car tonight.")
    service = make_service(ai_mode="auto", llm=llm)
    resp = chat(service, "Tell me a pirate tale about my automobiles")
    assert resp["choices"][0]["message"]["content"].startswith("The Model Y")
    assert "82%" in llm.seen_brief


def test_llm_command_block_previewed_after_validation():
    llm = FakeLlm('```json\n{"command": "discharge_start", "vehicle": "Model Y"}\n```')
    service = make_service(ai_mode="auto", llm=llm)
    resp = chat(service, "get the Y powering the house please")
    assert ("discharge_start", "Model Y") in service.command_log
    assert "discharge_start" in resp["choices"][0]["message"]["content"]


def test_llm_disallowed_command_rejected():
    llm = FakeLlm('```json\n{"command": "open_frunk", "vehicle": "Model Y"}\n```')
    service = make_service(ai_mode="auto", llm=llm)
    chat(service, "pop the frunk")
    assert service.command_log == []


def test_llm_never_mode_uses_capability_blurb():
    resp = chat(make_service(ai_mode="never"), "tell me a poem about my cars")
    assert resp["choices"][0]["message"]["content"] == CAPABILITY_BLURB


def test_no_cars_message():
    settings = Settings(vehicles=[], ai_mode="never")
    service = PowerShareService(settings, state_provider=lambda: [])
    resp = chat(service, "how long can my car power my home?")
    assert "setup" in resp["choices"][0]["message"]["content"]
