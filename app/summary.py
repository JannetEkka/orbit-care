"""Gemini writes words; code supplies every fact and checks the result.

The model is only asked to phrase facts that `rules.py` already computed. Its
text is rejected if it contains a number that is not in those facts, and a plain
template is used instead. The app works fully with no model at all.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

log = logging.getLogger("orbit.summary")

NOTE_TAGS = ("tremor", "confusion", "fall", "sleepy", "nausea", "pain", "not_eating", "calm")
_TAG_WORDS = {
    "tremor": ("tremor", "shak", "shiver"),
    "confusion": ("confus", "disorient", "forgot", "did not recogni", "didn't recogni"),
    "fall": ("fell", "fall", "slipped"),
    "sleepy": ("sleepy", "drows", "slept", "tired"),
    "nausea": ("nause", "vomit", "threw up"),
    "pain": ("pain", "ache", "hurt"),
    "not_eating": ("not eat", "no appetite", "refused food", "didn't eat", "did not eat"),
    "calm": ("calm", "good day", "cheerful", "smil"),
}
_NUMBER = re.compile(r"\d+(?:[.:]\d+)?")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_SUMMARY_CHARS = 900


def numbers_in(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def numbers_are_supported(text: str, facts: dict) -> bool:
    """True if every number in `text` also appears in the facts it was given."""
    return numbers_in(text) <= numbers_in(json.dumps(facts, ensure_ascii=False))


def keyword_tags(text: str) -> list[str]:
    lowered = text.lower()
    return [tag for tag, words in _TAG_WORDS.items() if any(w in lowered for w in words)]


class Summariser:
    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-3.1-flash-lite",
        client: httpx.Client | None = None,
        timeout: float = 8.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _generate(self, prompt: str) -> str | None:
        if not self.enabled:
            return None
        try:
            response = self._client.post(
                GEMINI_URL.format(model=self._model),
                headers={"x-goog-api-key": self._api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400},
                },
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            log.warning("Gemini call failed, using the template: %s", type(error).__name__)
            return None

    def write(self, audience: str, facts: dict, fallback: str) -> dict:
        """Phrase `facts` for `audience`. Returns {"text", "source"}."""
        prompt = (
            f"You write a short update for {audience} about an elderly person's care.\n"
            "Rules: use ONLY the facts in the JSON below. Do not add any number, medicine, "
            "diagnosis or medical advice that is not in the facts. Plain, warm, respectful "
            "English. At most 4 short sentences. No lists, no headings, no markdown.\n\n"
            f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}"
        )
        text = self._generate(prompt)
        if text and len(text) <= MAX_SUMMARY_CHARS and numbers_are_supported(text, facts):
            return {"text": text, "source": "gemini"}
        return {"text": fallback, "source": "template"}

    def suggest_tags(self, note: str) -> list[str]:
        """Tags for a free-text care note. The model proposes; only allowed tags pass."""
        prompt = (
            "A caregiver wrote this note about an elderly person. Reply with a JSON array "
            f"containing only the tags from this list that clearly apply: {list(NOTE_TAGS)}. "
            "Reply with the JSON array and nothing else.\n\nNOTE: " + note
        )
        text = self._generate(prompt)
        if text:
            match = re.search(r"\[.*?\]", text, flags=re.S)
            try:
                proposed = json.loads(match.group(0)) if match else []
            except ValueError:
                proposed = []
            tags = [t for t in NOTE_TAGS if t in proposed]
            if tags:
                return tags
        return keyword_tags(note)
