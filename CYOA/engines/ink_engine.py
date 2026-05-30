from __future__ import annotations
import re
from typing import Optional

try:
    from inkpython import Story
    HAS_INK = True
except ImportError:
    HAS_INK = False

_RE_TAG = re.compile(r'<[^>]+>')


class InkEngine:
    def __init__(self, ink_json: str, state: Optional[str] = None):
        if not HAS_INK:
            raise RuntimeError("inkpython required. pip install inkpython")
        self._story = Story(ink_json)
        self._text: str = ""
        self._ended: bool = False
        self._image: Optional[str] = None
        self._last_choice_text: str = ""

        if state:
            try:
                self._story.state.LoadJson(state)
            except Exception:
                pass

        self._step()

    def _step(self):
        parts = []
        while self._story.canContinue:
            t = self._story.Continue()
            if t:
                parts.append(_RE_TAG.sub("", t))
            if self._story.currentChoices:
                break

        tags = getattr(self._story, "currentTags", None) or []
        self._image = None
        for tag in tags:
            if tag.startswith("image:"):
                self._image = tag[6:].strip()

        self._text = "\n".join(parts) if parts else _RE_TAG.sub("", getattr(self._story, "currentText", None) or "")

        if not self._story.currentChoices and not self._story.canContinue:
            self._ended = True

    @property
    def is_ended(self) -> bool:
        return self._ended

    @property
    def text(self) -> str:
        return self._text or ""

    @property
    def image(self) -> Optional[str]:
        return self._image

    @property
    def choices(self) -> list[dict]:
        result = []
        for c in (getattr(self._story, "currentChoices", None) or []):
            ct = c.text if hasattr(c, "text") else ""
            result.append({
                "index": c.index,
                "text": _RE_TAG.sub("", ct),
            })
        return result

    @property
    def variables(self) -> dict:
        vs = getattr(self._story, "variablesState", None)
        if vs:
            try:
                return {k: v for k, v in vs.__dict__.items() if not k.startswith("_")}
            except Exception:
                pass
        return {}

    @property
    def tags(self) -> list[str]:
        return list(getattr(self._story, "currentTags", None) or [])

    def choose(self, index: int):
        choices = self.choices
        if 0 <= index < len(choices):
            self._last_choice_text = choices[index]["text"]
        self._story.ChooseChoiceIndex(index)
        if self._story.canContinue:
            t = _RE_TAG.sub("", self._story.Continue() or "")
            if t and t.strip() and not t.strip() == self._last_choice_text:
                self._text = t
        self._step()

    def save_state(self) -> str:
        try:
            return self._story.state.ToJson()
        except Exception:
            return ""

    def load_state(self, state: str):
        try:
            self._story.state.LoadJson(state)
            self._ended = False
            self._step()
        except Exception:
            pass
