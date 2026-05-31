from __future__ import annotations
import re
import logging
from typing import Optional

try:
    from inkpython import Story
    HAS_INK = True
except ImportError:
    HAS_INK = False

_RE_TAG = re.compile(r'<[^>]+>')
_logger = logging.getLogger("CYOA.InkEngine")


class InkEngine:
    def __init__(self, ink_json: str, state: Optional[str] = None):
        if not HAS_INK:
            raise RuntimeError("inkpython required. pip install inkpython")
        self._story = Story(ink_json)
        self._text_raw: str = ""
        self._text_plain: str = ""
        self._ended: bool = False
        self._last_choice_text: str = ""
        self._error: Optional[str] = None

        if state:
            try:
                self._story.state.LoadJson(state)
            except Exception as e:
                _logger.warning(f"Failed to load ink state: {e}")

        try:
            self._story.onError = self._on_ink_error
        except Exception:
            pass

        self._step()

    def _on_ink_error(self, msg: str, error_type: str = ""):
        _logger.error(f"Ink error ({error_type}): {msg}")
        self._error = msg

    def _step(self):
        try:
            self._safe_step()
        except Exception as e:
            _logger.error(f"InkEngine step error: {e}")
            self._error = str(e)
            self._ended = True

    def _safe_step(self):
        parts_raw = []
        try:
            while self._story.canContinue:
                t = self._story.Continue()
                if t:
                    parts_raw.append(t)
                if self._story.currentChoices:
                    break
        except Exception as e:
            _logger.warning(f"Ink Continue error: {e}")

        self._text_raw = "\n".join(parts_raw) if parts_raw else getattr(self._story, "currentText", None) or ""
        self._text_plain = _RE_TAG.sub("", self._text_raw)

        if not self._story.currentChoices and not self._story.canContinue:
            self._ended = True

    @property
    def is_ended(self) -> bool:
        return self._ended

    @property
    def has_error(self) -> bool:
        return self._error is not None

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def text(self) -> str:
        return self._text_raw or ""

    @property
    def text_plain(self) -> str:
        return self._text_plain or ""

    @property
    def choices(self) -> list[dict]:
        result = []
        try:
            for c in (getattr(self._story, "currentChoices", None) or []):
                ct = c.text if hasattr(c, "text") else ""
                result.append({
                    "index": c.index,
                    "text": _RE_TAG.sub("", ct),
                    "text_raw": ct,
                })
        except Exception:
            pass
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

    def choose(self, index: int) -> bool:
        choices = self.choices
        if index < 0 or index >= len(choices):
            _logger.warning(f"Choice index {index} out of range (0-{len(choices)-1})")
            return False

        self._error = None
        self._last_choice_text = choices[index]["text"]

        try:
            self._story.ChooseChoiceIndex(index)
        except Exception as e:
            _logger.error(f"Ink ChooseChoiceIndex error: {e}")
            self._error = str(e)
            self._ended = True
            return False

        try:
            if self._story.canContinue:
                t = self._story.Continue() or ""
                if t and t.strip() and _RE_TAG.sub("", t).strip() != self._last_choice_text:
                    self._text_raw = t
                    self._text_plain = _RE_TAG.sub("", t)
        except Exception as e:
            _logger.warning(f"Ink Continue after choose error: {e}")

        self._step()
        return True

    def save_state(self) -> str:
        try:
            return self._story.state.ToJson()
        except Exception:
            return ""

    def load_state(self, state: str):
        try:
            self._story.state.LoadJson(state)
            self._ended = False
            self._error = None
            self._step()
        except Exception:
            pass
