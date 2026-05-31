from __future__ import annotations
from typing import Optional


class StoryTemplates:

    @classmethod
    def build_main_menu(cls, has_active_game: bool = False) -> str:
        lines = ["CYOA 互动小说"]
        lines.append("1. 开始游戏 - 选择并开始一个互动故事")
        lines.append("2. 故事列表 - 浏览所有可用故事")
        lines.append("3. 导入故事 - 从 URL / 文件导入新故事")
        lines.append("4. 存档管理 - 查看 / 加载 / 删除存档")
        lines.append("5. 仓库管理 - 添加 / 更新 / 删除故事仓库")
        lines.append("6. 删除故事 - 删除已导入的故事")
        if has_active_game:
            lines.append("7. 继续游戏 - 继续当前进行中的故事")
            lines.append("8. 退出游戏 - 退出当前故事（自动存档）")
        lines.append("回复编号或关键词选择操作")
        return "\n".join(lines)

    @classmethod
    def build_category_menu(cls) -> str:
        return cls._simple_menu("选择故事分类", [
            ("1", "仓库故事", "来自已配置的故事仓库"),
            ("2", "导入故事", "通过 URL 或文件导入的故事"),
        ])

    @classmethod
    def build_story_list(cls, stories: list, category_name: str = "故事") -> str:
        if not stories:
            return f"暂无{category_name}"

        lines = [f"{category_name}列表 ({len(stories)})", "-" * 20]
        for i, s in enumerate(stories, 1):
            title = s.get("title", s["id"])
            source = f"[{s.get('repo_name', '导入')}]"
            lines.append(f"{i}. {title} {source}")
            lines.append(f"   ID: {s['id']}")
        lines.append("回复编号选择故事，或输入故事 ID")
        return "\n".join(lines)

    @classmethod
    def build_game_text(cls, text: str, choices: Optional[list] = None,
                        story_title: str = "") -> str:
        choices = choices or []
        lines = []
        if story_title:
            lines.append(f"[{story_title}]")
        if text:
            lines.append(text)
        for c in choices:
            idx = c.get("index", 0) + 1
            ct = c.get("text", "?")
            lines.append(f"  {idx}. {ct}")
        return "\n".join(lines)

    @classmethod
    def build_game_end(cls, text: str, story_title: str = "") -> str:
        title = f"[{story_title}] " if story_title else ""
        return f"{title}故事结束\n{text or '故事已结束。'}\n进度已自动保存。"

    @classmethod
    def build_save_list(cls, saves: list) -> str:
        if not saves:
            return "暂无存档"

        lines = [f"存档列表 ({len(saves)})", "-" * 20]
        for i, sv in enumerate(saves, 1):
            lines.append(f"{i}. {sv.get('story_id', '?')} | 槽位{sv.get('saved_slot', 1)} | {cls._fmt_ts(sv.get('saved_at', 0))}")
        lines.append("回复编号加载存档")
        return "\n".join(lines)

    @classmethod
    def build_import_menu(cls) -> str:
        return cls._simple_menu("导入故事", [
            ("1", "URL 导入", "输入 .ink.json 文件链接"),
            ("2", "文件导入", "直接发送 .ink.json 文件"),
            ("3", "粘贴导入", "直接发送 JSON 内容"),
        ]) + "\n提示：部分平台不支持文件发送，可使用 Dashboard 上传。"

    @classmethod
    def build_import_confirm(cls, story_id: str, title: str = "") -> str:
        name = title or story_id
        return f"导入成功\n{name}\nID: {story_id}\n输入 /cyoa 开始游戏"

    @classmethod
    def build_import_fail(cls, reason: str) -> str:
        return f"导入失败\n{reason}"

    @classmethod
    def build_repo_menu(cls) -> str:
        return cls._simple_menu("仓库管理", [
            ("1", "查看仓库", "列出所有已配置的仓库"),
            ("2", "添加仓库", "添加新的故事仓库"),
            ("3", "更新仓库", "更新仓库索引"),
            ("4", "删除仓库", "移除仓库配置"),
        ])

    @classmethod
    def build_repo_list(cls, repos: list) -> str:
        if not repos:
            return "暂无仓库。请在菜单中选择「添加仓库」。"

        lines = [f"仓库列表 ({len(repos)})", "-" * 20]
        for r in repos:
            lines.append(f"  {r.get('name', '?')} ({r.get('story_count', 0)} 个故事)")
            lines.append(f"    {r.get('url', '')}")
        return "\n".join(lines)

    @classmethod
    def build_delete_menu(cls, stories: list) -> str:
        if not stories:
            return "没有可删除的导入故事"

        lines = ["选择要删除的故事"]
        for i, s in enumerate(stories, 1):
            lines.append(f"{i}. {s.get('title', s['id'])} (ID: {s['id']})")
        lines.append("回复编号删除")
        return "\n".join(lines)

    @classmethod
    def build_status_msg(cls, msg: str) -> str:
        return msg

    @classmethod
    def _simple_menu(cls, title: str, items: list) -> str:
        lines = [title]
        for num, label, desc in items:
            lines.append(f"{num}. {label} - {desc}")
        lines.append("回复编号选择操作")
        return "\n".join(lines)

    @staticmethod
    def _fmt_ts(ts) -> str:
        if not ts:
            return ""
        import time as _t
        try:
            diff = _t.time() - ts
            if diff < 60:
                return "刚刚"
            if diff < 3600:
                return f"{int(diff // 60)} 分钟前"
            if diff < 86400:
                return f"{int(diff // 3600)} 小时前"
            if diff < 604800:
                return f"{int(diff // 86400)} 天前"
            import datetime
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts)
