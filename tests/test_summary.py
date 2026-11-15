"""The model may phrase the facts but never add a number to them."""

import httpx

from app.summary import Summariser, keyword_tags, numbers_are_supported

FACTS = {"given": 38, "scheduled": 45, "percent": 84}


def fake_gemini(text: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "k"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_supported_numbers_pass():
    assert numbers_are_supported("He took 38 of 45 doses (84%).", FACTS)
    assert not numbers_are_supported("He took 40 of 45 doses.", FACTS)


def test_model_text_is_used_when_it_checks_out():
    summariser = Summariser("k", client=fake_gemini("He was given 38 of 45 doses, 84%."))
    result = summariser.write("the family", FACTS, "fallback")
    assert result == {"text": "He was given 38 of 45 doses, 84%.", "source": "gemini"}


def test_model_text_with_an_invented_number_is_rejected():
    summariser = Summariser("k", client=fake_gemini("He missed 12 doses and needs 2 more tablets."))
    assert summariser.write("the family", FACTS, "fallback") == {"text": "fallback", "source": "template"}


def test_model_failure_falls_back():
    def broken(request):
        return httpx.Response(503)

    summariser = Summariser("k", client=httpx.Client(transport=httpx.MockTransport(broken)))
    assert summariser.write("x", FACTS, "fallback")["source"] == "template"


def test_model_tags_are_limited_to_the_allowed_list():
    summariser = Summariser("k", client=fake_gemini('["tremor", "stroke", "fall"]'))
    assert summariser.suggest_tags("anything") == ["tremor", "fall"]


def test_keyword_tags_without_a_model():
    assert keyword_tags("Slipped near the bed, a bit confused") == ["confusion", "fall"]


def test_brevo_mailer_sends_over_https():
    from app.mailer import BrevoMailer

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["api-key"]
        seen["body"] = request.read().decode()
        return httpx.Response(201, json={"messageId": "x"})

    mailer = BrevoMailer("k", "orbit@example.com", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert mailer.send(["a@example.com"], "Hi\nBcc: x@example.com", "body") == (True, "")
    assert seen["key"] == "k" and "Bcc: x" in seen["body"] and "\\n" not in seen["body"].split("subject")[1][:40]


def test_identical_facts_call_gemini_once():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "38 of 45."}]}}]})

    summariser = Summariser("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    summariser.write("x", FACTS, "fallback")
    summariser.write("x", FACTS, "fallback")
    assert len(calls) == 1
