from __future__ import annotations
from typing import Dict, Optional

PRIMARY = "#8b5cf6"
PRIMARY_BG = "rgba(139, 92, 246, 0.06)"
SECONDARY = "#666"
BORDER = "rgba(0, 0, 0, 0.06)"
TAG_BG = "rgba(0,0,0,0.04)"


class StoryTemplates:

    @classmethod
    def build_main_menu(cls, has_active_game: bool = False) -> Dict[str, str]:
        items = [
            ("1", "开始游戏", "选择并开始一个互动故事"),
            ("2", "故事列表", "浏览所有可用故事"),
            ("3", "导入故事", "从 URL / 文件导入新故事"),
            ("4", "存档管理", "查看 / 加载 / 删除存档"),
            ("5", "仓库管理", "添加 / 更新 / 删除故事仓库"),
            ("6", "删除故事", "删除已导入的故事"),
        ]
        if has_active_game:
            items.append(("7", "继续游戏", "继续当前进行中的故事"))
            items.append(("8", "退出游戏", "退出当前故事（自动存档）"))

        items_html = "".join(
            f'<div style="font-size:13px;margin-bottom:6px;">'
            f'<span style="color:{PRIMARY};font-weight:bold;margin-right:8px;">{num}.</span>'
            f'<span style="font-weight:bold;">{label}</span>'
            f' <span style="font-size:11px;color:{SECONDARY};">- {desc}</span></div>'
            for num, label, desc in items
        )

        md_lines = ["**CYOA 互动小说**\n"]
        for num, label, desc in items:
            md_lines.append(f"{num}. **{label}** - {desc}")
        md_lines.append("\n回复编号或关键词选择操作")

        text_lines = ["CYOA 互动小说"]
        for num, label, desc in items:
            text_lines.append(f"{num}. {label} - {desc}")
        text_lines.append("回复编号或关键词选择操作")

        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:{PRIMARY};font-size:16px;font-weight:bold;margin-bottom:10px;">'
                f'CYOA 互动小说</div>'
                f'{items_html}'
                f'<div style="font-size:11px;color:{SECONDARY};margin-top:10px;">'
                f'回复编号或关键词选择操作 | 也可 /cyoa &lt;故事ID&gt; 快速开始</div>'
                f'</div>'
            ),
            "markdown": "\n".join(md_lines),
            "text": "\n".join(text_lines),
        }

    @classmethod
    def build_category_menu(cls) -> Dict[str, str]:
        items = [
            ("1", "仓库故事", "来自已配置的故事仓库"),
            ("2", "导入故事", "通过 URL 或文件导入的故事"),
        ]
        return cls._simple_menu("选择故事分类", items)

    @classmethod
    def build_story_list(cls, stories: list, category_name: str = "故事") -> Dict[str, str]:
        if not stories:
            nope = f"暂无{category_name}"
            return {"html": nope, "markdown": nope, "text": nope}

        rows_html = []
        for i, s in enumerate(stories, 1):
            title = s.get("title", s["id"])
            author = s.get("author", "")
            version = s.get("version", "")
            desc = s.get("description", "")
            source = s.get("repo_name", "")
            source_badge = (
                f'<span style="font-size:10px;background:{PRIMARY_BG};'
                f'color:{PRIMARY};padding:1px 5px;border-radius:3px;margin-right:4px;">'
                f'{source}</span>' if source else ""
            )
            desc_line = (
                f'<div style="font-size:11px;color:{SECONDARY};margin-top:2px;">{desc[:80]}</div>'
                if desc else ""
            )
            rows_html.append(
                f'<div style="padding:8px;margin-bottom:6px;background:{PRIMARY_BG};border-radius:6px;">'
                f'<div style="font-size:14px;">'
                f'<span style="color:{PRIMARY};font-weight:bold;margin-right:4px;">{i}.</span>'
                f'{source_badge}'
                f'<span style="font-weight:bold;">{title}</span></div>'
                f'<div style="font-size:11px;color:{SECONDARY};">'
                f'ID: {s["id"]}'
                f'{f" | 作者: {author}" if author else ""}'
                f'{f" | v{version}" if version else ""}</div>'
                f'{desc_line}</div>'
            )

        md_lines = [f"**{category_name}列表** ({len(stories)})\n"]
        for i, s in enumerate(stories, 1):
            title = s.get("title", s["id"])
            source = f"[{s['repo_name']}]" if s.get("repo_name") else "[导入]"
            author = s.get("author", "")
            md_lines.append(f"{i}. **{title}** {source} `ID:{s['id']}`")
            if author:
                md_lines[-1] += f" | {author}"

        text_lines = [f"{category_name}列表 ({len(stories)})", "-" * 20]
        for i, s in enumerate(stories, 1):
            title = s.get("title", s["id"])
            source = f"[{s.get('repo_name', '导入')}]"
            text_lines.append(f"{i}. {title} {source}")
            text_lines.append(f"   ID: {s['id']}")

        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:{PRIMARY};font-size:15px;font-weight:bold;margin-bottom:10px;">'
                f'{category_name}列表 ({len(stories)})</div>'
                f'{"".join(rows_html)}'
                f'<div style="font-size:11px;color:{SECONDARY};margin-top:8px;">'
                f'回复编号选择故事，或输入故事 ID</div></div>'
            ),
            "markdown": "\n".join(md_lines) + "\n\n回复编号选择故事，或输入故事 ID",
            "text": "\n".join(text_lines) + "\n回复编号选择故事，或输入故事 ID",
        }

    @classmethod
    def build_game_text(cls, text: str, choices: Optional[list] = None,
                        story_title: str = "") -> Dict[str, str]:
        choices = choices or []

        choices_html = ""
        choices_md = []
        choices_text = []
        for c in choices:
            idx = c.get("index", 0) + 1
            ct = c.get("text", "?")
            choices_html += (
                f'<div style="padding:4px 8px;margin-bottom:4px;background:{PRIMARY_BG};'
                f'border-radius:4px;font-size:13px;">'
                f'<span style="color:{PRIMARY};font-weight:bold;margin-right:6px;">{idx}.</span>'
                f'{ct}</div>'
            )
            choices_md.append(f"{idx}. {ct}")
            choices_text.append(f"  {idx}. {ct}")

        title_badge = ""
        if story_title:
            title_badge = (
                f'<div style="font-size:11px;color:{PRIMARY};margin-bottom:6px;">'
                f'{story_title}</div>'
            )

        html = (
            f'<div style="padding:12px;border-radius:8px;">'
            f'{title_badge}'
            f'<div style="font-size:14px;line-height:1.6;margin-bottom:10px;">{text}</div>'
            f'{choices_html}'
            f'<div style="font-size:10px;color:{SECONDARY};margin-top:6px;">'
            f'回复编号或选项文字做出选择</div></div>'
        ) if text or choices else ""

        md = ""
        if story_title:
            md += f"**{story_title}**\n\n"
        if text:
            md += f"{text}\n\n"
        if choices_md:
            md += "\n".join(choices_md) + "\n\n回复编号做出选择"

        text_content = ""
        if story_title:
            text_content += f"[{story_title}]\n"
        if text:
            text_content += f"{text}\n"
        if choices_text:
            text_content += "\n".join(choices_text)

        return {"html": html, "markdown": md, "text": text_content}

    @classmethod
    def build_game_end(cls, text: str, story_title: str = "") -> Dict[str, str]:
        title = f"[{story_title}] " if story_title else ""
        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="font-size:11px;color:{PRIMARY};margin-bottom:6px;">故事结束</div>'
                f'<div style="font-size:14px;line-height:1.6;">{text or "故事已结束。"}</div>'
                f'<div style="font-size:11px;color:{SECONDARY};margin-top:8px;">'
                f'进度已自动保存。输入 /cyoa 查看主菜单。</div></div>'
            ),
            "markdown": f"**故事结束**\n\n{text or '故事已结束。'}\n\n进度已自动保存。",
            "text": f"{title}故事结束\n{text or '故事已结束。'}\n进度已自动保存。",
        }

    @classmethod
    def build_save_list(cls, saves: list) -> Dict[str, str]:
        if not saves:
            nope = "暂无存档"
            return {"html": nope, "markdown": nope, "text": nope}

        rows_html = []
        for i, sv in enumerate(saves, 1):
            story = sv.get("story_id", "?")
            slot = sv.get("saved_slot", 1)
            ts = sv.get("saved_at", 0)
            time_str = cls._fmt_ts(ts)
            rows_html.append(
                f'<div style="padding:8px;margin-bottom:6px;background:{PRIMARY_BG};border-radius:6px;">'
                f'<div style="font-size:13px;">'
                f'<span style="color:{PRIMARY};font-weight:bold;">{i}.</span>'
                f' {story} | 槽位 {slot}</div>'
                f'<div style="font-size:11px;color:{SECONDARY};">{time_str}</div></div>'
            )

        md_lines = [f"**存档列表** ({len(saves)})\n"]
        for i, sv in enumerate(saves, 1):
            md_lines.append(
                f"{i}. `{sv.get('story_id', '?')}` 槽位{sv.get('saved_slot', 1)} - {cls._fmt_ts(sv.get('saved_at', 0))}"
            )

        text_lines = [f"存档列表 ({len(saves)})", "-" * 20]
        for i, sv in enumerate(saves, 1):
            text_lines.append(f"{i}. {sv.get('story_id', '?')} | 槽位{sv.get('saved_slot', 1)} | {cls._fmt_ts(sv.get('saved_at', 0))}")

        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:{PRIMARY};font-size:15px;font-weight:bold;margin-bottom:10px;">'
                f'存档列表 ({len(saves)})</div>'
                f'{"".join(rows_html)}'
                f'<div style="font-size:11px;color:{SECONDARY};margin-top:8px;">'
                f'回复编号加载存档</div></div>'
            ),
            "markdown": "\n".join(md_lines) + "\n\n回复编号加载存档",
            "text": "\n".join(text_lines) + "\n回复编号加载存档",
        }

    @classmethod
    def build_import_menu(cls) -> Dict[str, str]:
        items = [
            ("1", "URL 导入", "输入 .ink.json 文件链接"),
            ("2", "文件导入", "直接发送 .ink.json 文件（部分平台可能不支持）"),
            ("3", "粘贴导入", "直接发送 JSON 内容"),
        ]
        tmpl = cls._simple_menu("导入故事", items)
        hint = "\n提示：部分平台不支持文件发送，可使用 Dashboard 上传。"
        tmpl["text"] += hint
        tmpl["markdown"] += hint
        return tmpl

    @classmethod
    def build_import_confirm(cls, story_id: str, title: str = "") -> Dict[str, str]:
        name = title or story_id
        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:{PRIMARY};font-size:15px;font-weight:bold;margin-bottom:8px;">导入成功</div>'
                f'<div style="padding:8px;background:{PRIMARY_BG};border-radius:6px;">'
                f'<div style="font-size:14px;font-weight:bold;">{name}</div>'
                f'<div style="font-size:12px;color:{SECONDARY};">ID: {story_id}</div></div>'
                f'<div style="font-size:12px;color:{SECONDARY};margin-top:8px;">'
                f'回复编号选择故事开始，或输入 /cyoa 进入主菜单</div></div>'
            ),
            "markdown": f"**导入成功**\n**{name}** `ID:{story_id}`\n\n输入 /cyoa 开始游戏",
            "text": f"导入成功\n{name}\nID: {story_id}\n输入 /cyoa 开始游戏",
        }

    @classmethod
    def build_import_fail(cls, reason: str) -> Dict[str, str]:
        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:#e74c3c;font-size:15px;font-weight:bold;">导入失败</div>'
                f'<div style="font-size:13px;color:{SECONDARY};margin-top:6px;">{reason}</div></div>'
            ),
            "markdown": f"**导入失败**\n{reason}",
            "text": f"导入失败\n{reason}",
        }

    @classmethod
    def build_repo_menu(cls) -> Dict[str, str]:
        items = [
            ("1", "查看仓库", "列出所有已配置的仓库"),
            ("2", "添加仓库", "添加新的故事仓库"),
            ("3", "更新仓库", "更新仓库索引"),
            ("4", "删除仓库", "移除仓库配置"),
        ]
        return cls._simple_menu("仓库管理", items)

    @classmethod
    def build_repo_list(cls, repos: list) -> Dict[str, str]:
        if not repos:
            nope = "暂无仓库。请在菜单中选择「添加仓库」。"
            return {"html": nope, "markdown": nope, "text": nope}

        rows_html = []
        for r in repos:
            name = r.get("name", "?")
            count = r.get("story_count", 0)
            url = r.get("url", "")
            rows_html.append(
                f'<div style="padding:8px;margin-bottom:6px;background:{PRIMARY_BG};border-radius:6px;">'
                f'<div style="font-size:14px;">'
                f'<span style="color:{PRIMARY};font-weight:bold;">{name}</span>'
                f' <span style="font-size:11px;color:{SECONDARY};">({count} 个故事)</span></div>'
                f'<div style="font-size:11px;color:{SECONDARY};word-break:break-all;">{url}</div></div>'
            )

        md_lines = [f"**仓库列表** ({len(repos)})", ""]
        for r in repos:
            md_lines.append(f"- **{r.get('name', '?')}** ({r.get('story_count', 0)} 故事) `{r.get('url', '')}`")

        text_lines = [f"仓库列表 ({len(repos)})", "-" * 20]
        for r in repos:
            text_lines.append(f"  {r.get('name', '?')} ({r.get('story_count', 0)} 故事)")
            text_lines.append(f"    {r.get('url', '')}")

        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:{PRIMARY};font-size:15px;font-weight:bold;margin-bottom:10px;">'
                f'仓库列表 ({len(repos)})</div>'
                f'{"".join(rows_html)}</div>'
            ),
            "markdown": "\n".join(md_lines),
            "text": "\n".join(text_lines),
        }

    @classmethod
    def build_delete_menu(cls, stories: list) -> Dict[str, str]:
        if not stories:
            nope = "没有可删除的导入故事"
            return {"html": nope, "markdown": nope, "text": nope}

        rows_html = []
        for i, s in enumerate(stories, 1):
            title = s.get("title", s["id"])
            rows_html.append(
                f'<div style="padding:6px;margin-bottom:4px;background:{PRIMARY_BG};border-radius:4px;">'
                f'<span style="color:{PRIMARY};font-weight:bold;margin-right:4px;">{i}.</span>'
                f'{title} <span style="font-size:11px;color:{SECONDARY};">(ID: {s["id"]})</span></div>'
            )

        md_lines = [f"**选择要删除的故事**\n"]
        for i, s in enumerate(stories, 1):
            md_lines.append(f"{i}. {s.get('title', s['id'])} `ID:{s['id']}`")

        text_lines = ["选择要删除的故事"]
        for i, s in enumerate(stories, 1):
            text_lines.append(f"{i}. {s.get('title', s['id'])} (ID: {s['id']})")

        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:{PRIMARY};font-size:15px;font-weight:bold;margin-bottom:10px;">'
                f'选择要删除的故事</div>'
                f'{"".join(rows_html)}'
                f'<div style="font-size:11px;color:{SECONDARY};margin-top:8px;">'
                f'回复编号删除（仅限导入的故事）</div></div>'
            ),
            "markdown": "\n".join(md_lines) + "\n\n回复编号删除",
            "text": "\n".join(text_lines) + "\n回复编号删除",
        }

    @classmethod
    def build_status_msg(cls, msg: str) -> Dict[str, str]:
        return {
            "html": (
                f'<div style="padding:8px 12px;border-radius:6px;">'
                f'<span style="color:{PRIMARY};">{msg}</span></div>'
            ),
            "markdown": msg,
            "text": msg,
        }

    @classmethod
    def _simple_menu(cls, title: str, items: list) -> Dict[str, str]:
        items_html = "".join(
            f'<div style="font-size:13px;margin-bottom:6px;">'
            f'<span style="color:{PRIMARY};font-weight:bold;margin-right:8px;">{num}.</span>'
            f'<span style="font-weight:bold;">{label}</span>'
            f' <span style="font-size:11px;color:{SECONDARY};">- {desc}</span></div>'
            for num, label, desc in items
        )

        md_lines = [f"**{title}**\n"]
        for num, label, desc in items:
            md_lines.append(f"{num}. **{label}** - {desc}")
        md_lines.append("\n回复编号选择操作")

        text_lines = [title]
        for num, label, desc in items:
            text_lines.append(f"{num}. {label} - {desc}")
        text_lines.append("回复编号选择操作")

        return {
            "html": (
                f'<div style="padding:12px;border-radius:8px;">'
                f'<div style="color:{PRIMARY};font-size:15px;font-weight:bold;margin-bottom:10px;">'
                f'{title}</div>'
                f'{items_html}'
                f'<div style="font-size:11px;color:{SECONDARY};margin-top:8px;">回复编号选择操作</div>'
                f'</div>'
            ),
            "markdown": "\n".join(md_lines),
            "text": "\n".join(text_lines),
        }

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
