from __future__ import annotations
from typing import Any, Optional

CALLBACK_PREFIX = "cyoa:"
BUTTON_PLATFORMS = {"telegram", "yunhu", "yunhu_user", "qqbot"}


class PlatformButtons:
    @staticmethod
    def supports_buttons(platform: str) -> bool:
        return platform in BUTTON_PLATFORMS

    async def send(self, adapter: Any, platform: str, target_type: str, target_id: str, text: str, choices: list[dict]):
        built = self._build(adapter, platform, target_type, target_id, choices)
        if not built:
            return False
        try:
            await built.Text(text)
            return True
        except Exception:
            return False

    def _build(self, adapter, platform, target_type, target_id, choices):
        if platform in ("telegram",):
            return self._tg(adapter, target_type, target_id, choices)
        elif platform in ("yunhu", "yunhu_user"):
            return self._yh(adapter, target_type, target_id, choices)
        elif platform in ("qqbot",):
            return self._qq(adapter, target_type, target_id, choices)
        return None

    def _tg(self, ad, tt, tid, choices):
        rows = []
        row = []
        for c in choices:
            cb = f"{CALLBACK_PREFIX}{c.get('index', '')}"
            row.append({"text": c.get("text", "?"), "callback_data": cb})
            if len(row) >= 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return ad.Send.To(tt, tid).Keyboard(rows)

    def _yh(self, ad, tt, tid, choices):
        rows = []
        row = []
        for c in choices:
            cb = f"{CALLBACK_PREFIX}{c.get('index', '')}"
            row.append({"text": c.get("text", "?"), "actionType": 3, "value": cb})
            if len(row) >= 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return ad.Send.To(tt, tid).Buttons(rows)

    def _qq(self, ad, tt, tid, choices):
        rows = []
        for i, c in enumerate(choices):
            cb = f"{CALLBACK_PREFIX}{c.get('index', '')}"
            rows.append({"rows": [{"buttons": [{
                "id": f"cyoa_{i}",
                "render_data": {"label": c.get("text", "?"), "visited_label": c.get("text", "?")},
                "action": {"type": 2, "permission": {"type": 2}, "data": cb},
            }]}]})
        return ad.Send.To(tt, tid).Keyboard({"content": rows})

    def parse_callback(self, event) -> Optional[int]:
        try:
            platform = ""
            if hasattr(event, "get_platform"):
                platform = event.get_platform()
            detail_type = ""
            if hasattr(event, "get"):
                detail_type = event.get("detail_type", "")

            raw = ""
            if platform == "telegram" or detail_type == "telegram_callback_query":
                if hasattr(event, "get_callback_data"):
                    raw = event.get_callback_data()
                elif hasattr(event, "get"):
                    raw = event.get("telegram_callback_data", "")
            elif detail_type in ("yunhu_button_click", "yunhu_user_button_click"):
                if hasattr(event, "get"):
                    raw = event.get("yunhu_button", {}).get("value", "")
            elif detail_type == "qqbot_interaction":
                if hasattr(event, "get"):
                    raw = event.get("qqbot_interaction_data", {}).get("value", "")

            if raw and raw.startswith(CALLBACK_PREFIX):
                return int(raw[len(CALLBACK_PREFIX):])
        except (ValueError, Exception):
            pass
        return None
