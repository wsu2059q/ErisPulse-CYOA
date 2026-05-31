from __future__ import annotations
import asyncio
import json
import os
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from ErisPulse import sdk
from ErisPulse.Core.Bases import BaseModule
from ErisPulse.Core.Event import command, notice, message
from ErisPulse.loaders import ModuleLoadStrategy

from .engines.ink_engine import InkEngine, HAS_INK
from .models.session import GameSession
from .platform_buttons import PlatformButtons
from .story_repo import StoryRepo
from .templates import StoryTemplates


class Main(BaseModule):
    def __init__(self):
        self.sdk = sdk
        self.logger = sdk.logger.get_child("CYOA")
        try:
            self.config = self._cfg()
            self.logger.info(f"[DIAG] __init__: _cfg() OK, config={self.config}")
        except Exception as e:
            self.logger.error(f"[DIAG] __init__: _cfg() FAILED: {e}")
            self.config = {"default_timeout": 300, "max_saves": 5}
        try:
            self._repo = StoryRepo(sdk.storage, self.logger)
            self.logger.info(f"[DIAG] __init__: StoryRepo OK")
        except Exception as e:
            self.logger.error(f"[DIAG] __init__: StoryRepo FAILED: {e}")
            self._repo = None
        self._btn = PlatformButtons()
        self._engines: dict[str, InkEngine] = {}
        self._sessions: dict[str, GameSession] = {}
        self._locks: set[str] = set()
        self._btn_h = None
        self._msg_h = None
        self._file_import_pending: dict[str, float] = {}
        self.logger.info("[DIAG] __init__ complete")

    @staticmethod
    def get_load_strategy():
        return ModuleLoadStrategy(lazy_load=False, priority=30)

    def _cfg(self) -> dict:
        c = sdk.config.getConfig("CYOA")
        if not c:
            c = {"default_timeout": 300, "max_saves": 5}
            sdk.config.setConfig("CYOA", c, immediate=True)
        return c

    @property
    def _timeout(self) -> int:
        return self.config.get("default_timeout", 300)

    # ─── lifecycle ────────────────────────────────────────────────

    async def on_load(self, event):
        if not HAS_INK:
            self.logger.warning("inkpython not installed. pip install inkpython")

        try:
            @command("cyoa", aliases=["互动小说", "故事"], help="CYOA 互动小说")
            async def _cyoa(evt):
                await self._dispatch(evt)
            self.logger.info(f"[DIAG] command registered OK")
        except Exception as e:
            self.logger.error(f"[DIAG] command registration FAILED: {e}")

        try:
            self._btn_h = notice.on_notice(priority=0)(self._on_button)
            self.logger.info(f"[DIAG] notice handler registered OK (priority=0)")
        except Exception as e:
            self.logger.error(f"[DIAG] notice registration FAILED: {e}")

        try:
            self._msg_h = message.on_message(priority=0)(self._on_message)
            self.logger.info(f"[DIAG] message handler registered OK (priority=0)")
        except Exception as e:
            self.logger.error(f"[DIAG] message registration FAILED: {e}")

        self._cleanup_task = asyncio.ensure_future(self._idle_cleanup_loop())
        try:
            self._register_routes()
        except Exception as e:
            self.logger.error(f"[DIAG] route registration FAILED: {e}")

        try:
            self._register_dashboard_view()
        except Exception as e:
            self.logger.error(f"[DIAG] dashboard registration FAILED: {e}")

    async def on_unload(self, event):
        self._save_all()
        if hasattr(self, '_cleanup_task') and self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        if self._btn_h:
            try:
                notice.unregister(self._btn_h)
            except Exception:
                pass
        if self._msg_h:
            try:
                message.unregister(self._msg_h)
            except Exception:
                pass
        self._unregister_routes()
        if hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard:
            try:
                self.sdk.Dashboard.unregister_view("CYOA")
            except Exception:
                pass
        self.logger.info("CYOA unloaded")

    # ─── dispatch ─────────────────────────────────────────────────

    async def _dispatch(self, event):
        args = event.get_command_args() if hasattr(event, "get_command_args") else []
        if isinstance(args, str):
            args = args.split() if args else []
        if not args:
            return await self._interactive_menu(event)

        first = args[0]

        if first.startswith("http://") or first.startswith("https://"):
            return await self._quick_import(event, first)

        if len(args) == 1 and not first.isdigit():
            story_id = first
            resolves = self._resolve_story(story_id)
            if resolves:
                return await self._play_resolved(event, resolves)
            await self._send_templates(event, StoryTemplates.build_status_msg(f"未找到 '{story_id}'"))
            return

        await self._interactive_menu(event)

    # ─── interactive main menu ────────────────────────────────────

    async def _interactive_menu(self, event):
        _, key = self._find(event)
        has_game = key is not None

        items = [
            "开始游戏", "故事列表", "导入故事", "存档管理",
            "仓库管理", "删除故事",
        ]
        if has_game:
            items += ["继续游戏", "退出游戏"]

        idx = await event.choose("CYOA 互动小说 — 选择操作", items, timeout=60)
        if idx is None:
            return

        handlers = [
            self._menu_play, self._menu_list, self._menu_import,
            self._menu_save, self._menu_repo, self._menu_delete,
        ]
        if has_game:
            handlers += [self._menu_continue, self._menu_quit]

        if 0 <= idx < len(handlers):
            await handlers[idx](event)

    # ─── menu: play ───────────────────────────────────────────────

    async def _menu_play(self, event):
        _, active_key = self._find(event)
        if active_key and self._is_game_stuck(active_key):
            sid = self._sessions[active_key].story_id if active_key in self._sessions else "?"
            self._persist(active_key, 1)
            self._remove(active_key)
            await self._send_templates(event, StoryTemplates.build_status_msg(
                f"检测到游戏 '{sid}' 已卡死，已自动退出。"))
        elif active_key:
            s = self._sessions.get(active_key)
            sid = s.story_id if s else "?"
            return await self._send_templates(event, StoryTemplates.build_status_msg(
                f"你已在游戏 '{sid}' 中。\n请先退出（主菜单 → 退出游戏），再开始新游戏。"))

        cat_idx = await event.choose("选择故事分类:", ["仓库故事", "导入故事"], timeout=30)
        if cat_idx is None:
            return await self._send_templates(event, StoryTemplates.build_status_msg("已取消"))

        cat = "repo" if cat_idx == 0 else "imported"
        stories = self._get_stories_by_cat(cat)
        if not stories:
            return await self._send_templates(event, StoryTemplates.build_status_msg("该分类暂无故事"))

        opts = [f"{s.get('title', s['id'])} [{s.get('repo_name', '导入')}]" for s in stories]
        idx = await event.choose(f"选择故事 ({len(stories)} 个):", opts, timeout=30)
        if idx is None:
            return await self._send_templates(event, StoryTemplates.build_status_msg("已取消"))

        chosen = stories[idx]
        resolves = self._resolve_story(chosen["id"])
        if not resolves:
            return await self._send_templates(event, StoryTemplates.build_status_msg(
                f"未找到故事 '{chosen['id']}' 的数据，请检查故事是否已导入。"))
        await self._play_resolved(event, resolves)

    async def _play_resolved(self, event, resolves):
        _, active_key = self._find(event)
        if active_key and self._is_game_stuck(active_key):
            sid = self._sessions[active_key].story_id if active_key in self._sessions else "?"
            self._persist(active_key, 1)
            self._remove(active_key)
            await self._send_templates(event, StoryTemplates.build_status_msg(
                f"检测到游戏 '{sid}' 已卡死，已自动退出。"))
        elif active_key:
            s = self._sessions.get(active_key)
            sid = s.story_id if s else "?"
            return await self._send_templates(event, StoryTemplates.build_status_msg(
                f"你已在游戏 '{sid}' 中。请先退出当前游戏。"))

        if len(resolves) > 1:
            opts = [f"{r['title']} ({r['source']})" for r in resolves]
            idx = await event.choose("该故事有多个来源，选择哪一个？", opts, timeout=30)
            if idx is None:
                return await self._send_templates(event, StoryTemplates.build_status_msg("已取消"))
            ref = resolves[idx]["ref"]
        else:
            ref = resolves[0]["ref"]

        story_id = resolves[0]["title"] if resolves else "?"
        key = self._key(event, ref.split("|")[-1] if "|" in ref else ref)
        if key in self._sessions:
            return await self._send_templates(event, StoryTemplates.build_status_msg("已在游戏中。请先退出当前游戏。"))

        if not HAS_INK:
            return await self._send_templates(event, StoryTemplates.build_status_msg("inkpython 未安装。pip install inkpython"))

        ink_json = await self._find_story(event, ref)
        if not ink_json:
            return await self._send_templates(event, StoryTemplates.build_status_msg("故事文件丢失，请重新导入或更新仓库。"))

        await self._start_game(event, ref.split("|")[-1] if "|" in ref else ref, ink_json, key)

    # ─── menu: list ───────────────────────────────────────────────

    async def _menu_list(self, event):
        cat_idx = await event.choose("选择故事分类:", ["仓库故事", "导入故事"], timeout=30)
        if cat_idx is None:
            return
        cat = "repo" if cat_idx == 0 else "imported"
        stories = self._get_stories_by_cat(cat)
        cat_name = "仓库故事" if cat == "repo" else "导入故事"
        await self._send_templates(event, StoryTemplates.build_story_list(stories, cat_name))

    # ─── menu: import ─────────────────────────────────────────────

    async def _menu_import(self, event):
        idx = await event.choose("导入故事 — 选择方式:", [
            "URL 导入 — 输入 .ink.json 文件链接",
            "文件导入 — 发送 .ink.json 文件",
            "粘贴导入 — 直接发送 JSON 内容",
        ], timeout=30)
        if idx is None:
            return

        if idx == 0:
            await self._menu_import_url(event)
        elif idx == 1:
            await self._menu_import_file(event)
        elif idx == 2:
            await self._menu_import_paste(event)

    async def _menu_import_url(self, event):
        await self._send_templates(event, StoryTemplates.build_status_msg("请输入 .ink.json 文件 URL："))
        r = await event.wait_reply(timeout=60)
        if not r:
            return
        url = r.get_text().strip()
        if not url.startswith("http"):
            return await self._send_templates(event, StoryTemplates.build_import_fail("无效 URL"))

        await self._send_templates(event, StoryTemplates.build_status_msg("下载中..."))
        ok, sid, _, msg = await self._repo.import_story(url)
        if not ok:
            return await self._send_templates(event, StoryTemplates.build_import_fail(msg))
        await self._send_templates(event, StoryTemplates.build_import_confirm(sid))

    async def _menu_import_file(self, event):
        uid = self._uid(event)
        self._file_import_pending[uid] = time.time()
        await self._send_templates(event, StoryTemplates.build_status_msg(
            "请发送 .ink.json 文件。\n"
            "提示：部分平台不支持文件发送，可使用 Dashboard 上传。\n"
            "等待文件中（60秒超时）..."
        ))

    async def _menu_import_paste(self, event):
        await self._send_templates(event, StoryTemplates.build_status_msg("请直接发送 JSON 内容："))
        r = await event.wait_reply(timeout=60)
        if not r:
            return
        content = r.get_text().strip()
        if not content.startswith("{"):
            return await self._send_templates(event, StoryTemplates.build_import_fail("内容不是有效 JSON（需以 { 开头）"))

        ok, sid, msg = self._repo.import_from_content(content, source="paste")
        if not ok:
            return await self._send_templates(event, StoryTemplates.build_import_fail(msg))
        await self._send_templates(event, StoryTemplates.build_import_confirm(sid))

    async def _quick_import(self, event, url: str):
        await self._send_templates(event, StoryTemplates.build_status_msg("下载中..."))
        ok, sid, _, msg = await self._repo.import_story(url)
        if not ok:
            return await self._send_templates(event, StoryTemplates.build_import_fail(msg))
        await self._send_templates(event, StoryTemplates.build_import_confirm(sid))

    # ─── menu: save ───────────────────────────────────────────────

    async def _menu_save(self, event):
        uid = self._uid(event)
        gid = self._gid(event)
        all_saves = self._repo.list_saves()
        my_saves = [s for s in all_saves if s.get("user_id") == uid]
        if gid:
            my_saves = [s for s in my_saves if s.get("group_id") == gid or not s.get("group_id")]

        if not my_saves:
            return await self._send_templates(event, StoryTemplates.build_status_msg("暂无存档"))

        opts = [f"{sv.get('story_id', '?')} 槽位{sv.get('saved_slot', 1)}" for sv in my_saves]
        idx = await event.choose(f"存档列表 ({len(my_saves)})", opts, timeout=30)
        if idx is None:
            return

        sv = my_saves[idx]
        story_id = sv.get("story_id", "")
        if story_id:
            old_key = self._find(event)[1]
            if old_key:
                self._remove(old_key)
            ink_json = self._repo.get_imported(story_id)
            if not ink_json:
                for repo in self._repo.list_repos():
                    ink_json = self._repo.get_cached_story(repo["name"], story_id)
                    if ink_json:
                        break
            if ink_json:
                key = self._key(event, story_id)
                await self._start_game(event, story_id, ink_json, key, state=sv.get("ink_state"))
            else:
                await self._send_templates(event, StoryTemplates.build_status_msg("故事文件丢失，无法加载"))
        else:
            await self._send_templates(event, StoryTemplates.build_status_msg("存档数据异常"))

    # ─── menu: repo ───────────────────────────────────────────────

    async def _menu_repo(self, event):
        idx = await event.choose("仓库管理:", [
            "查看仓库", "添加仓库", "更新仓库", "删除仓库",
        ], timeout=30)
        if idx is None:
            return

        if idx == 0:
            repos = self._repo.list_repos()
            await self._send_templates(event, StoryTemplates.build_repo_list(repos))
        elif idx == 1:
            await self._send_templates(event, StoryTemplates.build_status_msg("请输入仓库名称："))
            rn = await event.wait_reply(timeout=30)
            if not rn:
                return
            name = rn.get_text().strip()
            await self._send_templates(event, StoryTemplates.build_status_msg("请输入仓库 URL："))
            ru = await event.wait_reply(timeout=30)
            if not ru:
                return
            url = ru.get_text().strip()
            ok, msg = self._repo.add_repo(name, url)
            if ok:
                await self._send_templates(event, StoryTemplates.build_status_msg(f"已添加 '{name}'。请更新仓库索引。"))
            else:
                await self._send_templates(event, StoryTemplates.build_status_msg(msg))
        elif idx == 2:
            repos = self._repo.list_repos()
            if not repos:
                return await self._send_templates(event, StoryTemplates.build_status_msg("暂无仓库"))
            if len(repos) == 1:
                ok, msg = await self._repo.update_repo(repos[0]["name"])
                await self._send_templates(event, StoryTemplates.build_status_msg(f"更新 '{repos[0]['name']}': {msg}"))
            else:
                opts = [r["name"] for r in repos] + ["全部"]
                idx2 = await event.choose("选择要更新的仓库：", opts, timeout=30)
                if idx2 is None:
                    return
                if idx2 == len(opts) - 1:
                    results = await self._repo.update_all()
                    lines = [f"{n}: {m}" for n, m in results.items()]
                    await self._send_templates(event, StoryTemplates.build_status_msg("\n".join(lines)))
                else:
                    ok, msg = await self._repo.update_repo(repos[idx2]["name"])
                    await self._send_templates(event, StoryTemplates.build_status_msg(f"更新 '{repos[idx2]['name']}': {msg}"))
        elif idx == 3:
            repos = self._repo.list_repos()
            if not repos:
                return await self._send_templates(event, StoryTemplates.build_status_msg("暂无仓库"))
            opts = [f"{r['name']} ({r.get('story_count', 0)} 故事)" for r in repos]
            idx2 = await event.choose("选择要删除的仓库：", opts, timeout=30)
            if idx2 is None:
                return
            ok, msg = self._repo.remove_repo(repos[idx2]["name"])
            await self._send_templates(event, StoryTemplates.build_status_msg(msg if not ok else f"已删除 '{repos[idx2]['name']}'"))

    # ─── menu: delete ─────────────────────────────────────────────

    async def _menu_delete(self, event):
        imported = self._repo.list_imported()
        if not imported:
            return await self._send_templates(event, StoryTemplates.build_status_msg("没有可删除的导入故事"))

        opts = [f"{s.get('title', s['id'])} (ID: {s['id']})" for s in imported]
        idx = await event.choose("选择要删除的故事:", opts, timeout=30)
        if idx is None:
            return

        target = imported[idx]
        ok = self._repo.delete_imported(target["id"])
        if ok:
            await self._send_templates(event, StoryTemplates.build_status_msg(f"已删除 '{target.get('title', target['id'])}'"))
        else:
            await self._send_templates(event, StoryTemplates.build_status_msg("删除失败"))

    # ─── menu: continue / quit ────────────────────────────────────

    async def _menu_continue(self, event):
        _, key = self._find(event)
        if not key:
            return await self._send_templates(event, StoryTemplates.build_status_msg("当前没有进行中的游戏"))
        eng = self._engines.get(key)
        if not eng:
            self._remove(key)
            return await self._send_templates(event, StoryTemplates.build_status_msg("游戏会话丢失，已清理。"))

        if eng.is_ended:
            end_tmpl = StoryTemplates.build_game_end(eng.text_plain, self._sessions[key].story_id)
            await self._send_templates(event, end_tmpl)
            self._persist(key, 1)
            self._remove(key)
            return

        if self._is_game_stuck(key):
            sid = self._sessions[key].story_id if key in self._sessions else "?"
            self._persist(key, 1)
            self._remove(key)
            return await self._send_templates(event, StoryTemplates.build_status_msg(
                f"游戏 '{sid}' 已卡死，已自动保存退出。"))

        if key in self._locks:
            return await self._send_templates(event, StoryTemplates.build_status_msg("游戏正在处理中，请稍候..."))

        if eng.has_error and not eng.text_plain and not eng.choices:
            self._persist(key, 1)
            self._remove(key)
            return await self._send_templates(event, StoryTemplates.build_status_msg(
                f"引擎错误: {eng.error}\n已自动保存退出。"))

        try:
            if not eng.text_plain and not eng.choices:
                eng._step()
                if not eng.text_plain and not eng.choices:
                    self._persist(key, 1)
                    self._remove(key)
                    return await self._send_templates(event, StoryTemplates.build_status_msg(
                        "当前节点无内容，已自动保存退出。"))

            plat = self._plat(event)
            if self._btn.supports_buttons(plat):
                if await self._try_btn(event, key):
                    if not eng.choices:
                        pass
                    else:
                        return
            await self._send_templates(event, StoryTemplates.build_game_text(
                eng.text_plain, eng.choices, self._sessions[key].story_id))
            if eng.choices:
                await self._loop(event, key)
        except Exception:
            pass

    async def _menu_quit(self, event, reply=None):
        _, key = self._find(event)
        if not key:
            return await self._send_templates(event, StoryTemplates.build_status_msg("当前没有进行中的游戏"))
        self._persist(key, 1)
        sid = self._sessions[key].story_id if key in self._sessions else "?"
        self._remove(key)
        await self._send_templates(event, StoryTemplates.build_status_msg(f"已退出 '{sid}'，进度已保存。"))

    # ─── auto file detection ──────────────────────────────────────

    async def _on_message(self, event):
        uid = self._uid(event)
        if uid not in self._file_import_pending:
            return
        pending_time = self._file_import_pending[uid]
        if time.time() - pending_time > 120:
            del self._file_import_pending[uid]
            return

        msg_segments = event.get_message() if hasattr(event, "get_message") else []
        for seg in msg_segments:
            seg_type = seg.get("type", "")
            seg_data = seg.get("data", {})

            if seg_type == "file":
                file_url = seg_data.get("file") or seg_data.get("url") or ""
                file_name = seg_data.get("file_name", "") or seg_data.get("name", "")
                if not file_url:
                    continue
                if not (file_name.endswith(".ink.json") or file_name.endswith(".json")):
                    continue

                del self._file_import_pending[uid]
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        async with session.get(file_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                ok, sid, msg = self._repo.import_from_bytes(data, file_name)
                                if ok:
                                    await self._send_templates(event, StoryTemplates.build_import_confirm(sid))
                                else:
                                    await self._send_templates(event, StoryTemplates.build_import_fail(msg))
                                return
                    await self._send_templates(event, StoryTemplates.build_import_fail("文件下载失败"))
                except Exception as e:
                    await self._send_templates(event, StoryTemplates.build_import_fail(f"导入失败: {e}"))
                return

    # ─── text send ─────────────────────────────────────────────────

    async def _send_templates(self, target, text: str):
        try:
            await target.reply(text)
        except Exception:
            pass

    async def _send_templates_adapter(self, adapter, platform: str, tt: str, tid: str,
                                       text: str, bot_id: str = None):
        send = adapter.Send
        if bot_id:
            send = send.Using(bot_id)
        try:
            await send.To(tt, tid).Text(text)
        except Exception:
            pass

    # ─── game engine ──────────────────────────────────────────────

    async def _start_game(self, event, story_id: str, ink_json: str, key: str, state: str = None):
        _, old_key = self._find(event)
        if old_key and old_key != key:
            self._persist(old_key, 1)
            old_sid = self._sessions[old_key].story_id if old_key in self._sessions else "?"
            self._remove(old_key)
            await self._send_templates(event, StoryTemplates.build_status_msg(
                f"已自动保存并退出 '{old_sid}'。"))

        saved = self._get_save(event, story_id) if not state else {"ink_state": state}
        ink_state = saved.get("ink_state") if saved else None

        try:
            engine = InkEngine(ink_json, ink_state)
        except Exception as e:
            self.logger.error(f"Ink init: {e}")
            return await self._send_templates(event, StoryTemplates.build_status_msg(f"加载失败: {e}"))

        if engine.has_error:
            self.logger.warning(f"Ink engine started with error: {engine.error}")

        session = GameSession(
            story_id=story_id,
            user_id=self._uid(event),
            group_id=self._gid(event),
            platform=self._plat(event),
        )
        self._sessions[key] = session
        self._engines[key] = engine

        try:
            if engine.is_ended:
                end_tmpl = StoryTemplates.build_game_end(engine.text_plain, story_id)
                await self._send_templates(event, end_tmpl)
                self._persist(key, 1)
                self._remove(key)
                return

            if not engine.text_plain and not engine.choices:
                engine._step()
                if engine.is_ended:
                    end_tmpl = StoryTemplates.build_game_end(engine.text_plain, story_id)
                    await self._send_templates(event, end_tmpl)
                    self._persist(key, 1)
                    self._remove(key)
                    return
                if not engine.text_plain and not engine.choices:
                    await self._send_templates(event, StoryTemplates.build_status_msg(
                        "故事起始节点无内容。输入 /cyoa → 继续游戏 跳过。"))
                    self._persist(key, 1)
                    return

            plat = self._plat(event)
            if self._btn.supports_buttons(plat):
                if await self._try_btn(event, key):
                    return
            await self._send_game_segment(event, key)
            await self._loop(event, key)
        except asyncio.CancelledError:
            self._persist(key, 1)
            self._remove(key)
        except Exception as e:
            self.logger.error(f"Render: {e}")
            try:
                if not engine.is_ended:
                    await self._send_templates(event, StoryTemplates.build_game_text(
                        engine.text_plain, [], story_id))
            except Exception:
                pass
            self._persist(key, 1)
            self._remove(key)

    async def _send_game_segment(self, event, key: str):
        eng = self._engines.get(key)
        s = self._sessions.get(key)
        if not eng or not s:
            return

        tmpl = StoryTemplates.build_game_text(eng.text_plain, eng.choices, s.story_id)
        await self._send_templates(event, tmpl)

    async def _try_btn(self, event, key: str) -> bool:
        eng = self._engines.get(key)
        s = self._sessions.get(key)
        if not eng or not s:
            return False
        if not eng.text_plain and not eng.choices:
            return False

        ad = self._adapter(s.platform)
        if not ad:
            return False

        t = "group" if s.group_id else "user"
        tid = s.group_id or s.user_id

        if eng.choices and self._btn.supports_buttons(s.platform):
            try:
                await self._btn.send(ad, s.platform, t, tid, eng.text_plain, eng.choices)
                return True
            except Exception:
                pass

        tmpl = StoryTemplates.build_game_text(eng.text_plain, eng.choices, s.story_id)
        await self._send_templates_adapter(ad, s.platform, t, tid, tmpl)
        return True

    async def _loop(self, event, key: str):
        if key in self._locks:
            return
        self._locks.add(key)

        try:
            eng = self._engines.get(key)
            s = self._sessions.get(key)

            while eng and not eng.is_ended and key in self._sessions:
                if eng.has_error and not eng.text_plain and not eng.choices:
                    await self._send_templates(event, StoryTemplates.build_status_msg(
                        f"引擎错误: {eng.error}\n输入 /cyoa 退出。"))
                    break

                text = eng.text_plain
                choices = eng.choices

                if not text and not choices:
                    if eng.is_ended:
                        end_tmpl = StoryTemplates.build_game_end("", s.story_id if s else "")
                        await self._send_templates(event, end_tmpl)
                        self._persist(key, 1)
                        self._remove(key)
                        break
                    skip = await event.choose("这步没有任何内容，是否跳过？", ["跳过"], timeout=30)
                    if skip is None:
                        await self._send_templates(event, StoryTemplates.build_status_msg(
                            "超时，进度已保存。输入 /cyoa → 继续游戏。"))
                        self._persist(key, 1)
                        self._remove(key)
                        break
                    eng._step()
                    continue

                if not choices:
                    if text:
                        tmpl = StoryTemplates.build_game_text(text, [], s.story_id if s else "")
                        await self._send_templates(event, tmpl)
                    break

                opts = [c["text"] for c in choices]
                prompt = text if text else "请选择:"
                _game_timeout = min(self._timeout, 120)
                self.logger.debug(f"[WAIT] _loop choose: {len(opts)} options (timeout={_game_timeout}s, key={key})")
                idx = await event.choose(prompt, opts, timeout=_game_timeout)

                if idx is None:
                    self.logger.debug(f"[WAIT] _loop choose: TIMED OUT (key={key})")
                    self._persist(key, 1)
                    self._remove(key)
                    try:
                        await self._send_templates(event, StoryTemplates.build_status_msg(
                            "超时，进度已保存。输入 /cyoa → 继续游戏。"))
                    except Exception:
                        pass
                    break

                if key not in self._sessions:
                    break

                if not eng.choose(idx):
                    await self._send_templates(event, StoryTemplates.build_status_msg(
                        "选择失败，引擎可能已出错。输入 /cyoa 退出。"))
                    self._persist(key, 1)
                    break

                eng = self._engines.get(key)

                if eng and eng.is_ended:
                    end_tmpl = StoryTemplates.build_game_end(
                        eng.text_plain, s.story_id if s else "")
                    await self._send_templates(event, end_tmpl)
                    self._persist(key, 1)
                    self._remove(key)
                    break

                if eng and eng.text_plain:
                    plat = self._plat(event)
                    if self._btn.supports_buttons(plat) and eng.choices:
                        try:
                            ad = self._adapter(plat)
                            if ad and s:
                                tt = "group" if s.group_id else "user"
                                tid2 = s.group_id or s.user_id
                                await self._btn.send(ad, plat, tt, tid2, eng.text_plain, eng.choices)
                                continue
                        except Exception:
                            pass
                    tmpl = StoryTemplates.build_game_text(
                        eng.text_plain, eng.choices, s.story_id if s else "")
                    await self._send_templates(event, tmpl)

        except asyncio.CancelledError:
            self._persist(key, 1)
            self._remove(key)
        except Exception as e:
            self.logger.error(f"Loop: {e}")
            try:
                await self._send_templates(event, StoryTemplates.build_status_msg(
                    "游戏出错，进度已保存。"))
                self._persist(key, 1)
            except Exception:
                pass
            self._remove(key)
        finally:
            self._locks.discard(key)


    # ─── button callback ───────────────────────────────────────────

    async def _on_button(self, event):
        idx = self._btn.parse_callback(event)
        if idx is None:
            return

        if not isinstance(idx, int) or idx < 0:
            return

        try:
            uid = self._uid(event)
            if not uid:
                return

            key = None
            for k, sess in self._sessions.items():
                if sess.user_id == uid:
                    key = k
                    break
            if not key:
                return

            eng = self._engines.get(key)
            if not eng:
                self._remove(key)
                return

            if key in self._locks:
                return

            s = self._sessions.get(key)
            if not s:
                return

            if idx >= len(eng.choices):
                return

            await self._ack(event)

            if not eng.choose(idx):
                await self._send_in_session(key, StoryTemplates.build_status_msg(
                    f"选择失败: {eng.error or '未知错误'}\n输入 /cyoa 退出。"))
                self._persist(key, 1)
                return

            if eng.is_ended:
                await self._send_in_session(key, StoryTemplates.build_game_end(
                    eng.text_plain, s.story_id))
                self._persist(key, 1)
                self._remove(key)
                return

            while not eng.text_plain and not eng.choices and not eng.is_ended:
                eng._step()
            if eng.is_ended:
                await self._send_in_session(key, StoryTemplates.build_game_end(
                    eng.text_plain, s.story_id))
                self._persist(key, 1)
                self._remove(key)
                return

            if not eng.text_plain and not eng.choices:
                await self._send_in_session(key, StoryTemplates.build_status_msg(
                    "这步没有任何内容。输入 /cyoa → 继续游戏 跳过。"))
                return

            ad = self._adapter(s.platform)
            if ad and self._btn.supports_buttons(s.platform) and eng.choices:
                try:
                    tt = "group" if s.group_id else "user"
                    tid = s.group_id or s.user_id
                    await self._btn.send(ad, s.platform, tt, tid, eng.text_plain, eng.choices)
                    return
                except Exception:
                    pass

            await self._send_in_session(key, StoryTemplates.build_game_text(
                eng.text_plain, eng.choices, s.story_id))

        except Exception as e:
            self.logger.error(f"Button: {e}")

    async def _send_in_session(self, key: str, text: str):
        s = self._sessions.get(key)
        if not s:
            return
        ad = self._adapter(s.platform)
        if not ad:
            return
        tt = "group" if s.group_id else "user"
        tid = s.group_id or s.user_id
        try:
            await ad.Send.To(tt, tid).Text(text)
        except Exception:
            pass

    async def _ack(self, event):
        try:
            cid = ""
            if hasattr(event, "get_callback_id"):
                cid = event.get_callback_id()
            elif hasattr(event, "get"):
                cid = event.get("telegram_callback_id", "") or event.get("qqbot_interaction_id", "")
            if cid:
                plat = self._plat(event)
                if plat in ("telegram", "yunhu", "yunhu_user", "qqbot"):
                    ad = self._adapter(plat)
                    if ad:
                        asyncio.ensure_future(ad.Send.AnswerCallback(cid, text=""))
        except Exception:
            pass

    # ─── session / state ───────────────────────────────────────────

    def _key(self, event, story_id: str = "") -> str:
        parts = [self._uid(event)]
        g = self._gid(event)
        if g:
            parts.append(g)
        if story_id:
            parts.append(story_id)
        return ".".join(parts)

    def _find(self, event):
        uid = self._uid(event)
        gid = self._gid(event)
        for k, s in self._sessions.items():
            if s.user_id == uid and (gid is None or s.group_id == gid):
                return self._engines.get(k), k
        return None, None

    def _is_game_stuck(self, key: str) -> bool:
        eng = self._engines.get(key)
        if not eng:
            return True
        if eng.is_ended:
            return True
        if eng.has_error and not eng.text_plain and not eng.choices:
            return True
        if not eng.text_plain and not eng.choices:
            return True
        return False

    def _cur_story(self, event) -> Optional[str]:
        _, k = self._find(event)
        if k:
            return self._sessions[k].story_id
        uid = self._uid(event)
        for k in self._sessions:
            if k.startswith(uid):
                return self._sessions[k].story_id
        return None

    def _remove(self, key: str):
        self._sessions.pop(key, None)
        self._engines.pop(key, None)

    def _persist(self, key: str, slot: int):
        eng = self._engines.get(key)
        s = self._sessions.get(key)
        if not eng or not s:
            return
        s.ink_state = eng.save_state()
        s.saved_slot = slot
        s.touch()
        sdk.storage.set(f"cyoa.{s.save_key}", s.to_dict())

    def _save_all(self):
        for k in self._sessions:
            self._persist(k, self._sessions[k].saved_slot or 1)

    async def _idle_cleanup_loop(self):
        try:
            while True:
                await asyncio.sleep(60)
                now = time.time()
                idle_limit = self._timeout * 2
                stale = []
                for k, s in list(self._sessions.items()):
                    if k in self._locks:
                        continue
                    if hasattr(s, 'last_active') and s.last_active:
                        if now - s.last_active > idle_limit:
                            stale.append(k)
                    elif hasattr(s, 'updated_at') and s.updated_at:
                        if now - s.updated_at > idle_limit:
                            stale.append(k)
                for k in stale:
                    self._persist(k, 1)
                    self._remove(k)
                    self.logger.info(f"Idle cleanup: removed session {k}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Idle cleanup error: {e}")

    def _get_save(self, event, story_id: str, slot: int = 1) -> Optional[dict]:
        uid = self._uid(event)
        gid = self._gid(event)
        p = GameSession.save_key_pattern(uid, story_id, gid)
        return sdk.storage.get(f"cyoa.{p}.{slot}")

    # ─── helpers ───────────────────────────────────────────────────

    def _uid(self, event) -> str:
        if hasattr(event, "get_user_id"):
            return event.get_user_id() or ""
        if hasattr(event, "get"):
            return event.get("user_id", "")
        return ""

    def _gid(self, event) -> Optional[str]:
        if hasattr(event, "get_group_id"):
            return event.get_group_id() or None
        if hasattr(event, "get"):
            return event.get("group_id") or None
        return None

    def _plat(self, event) -> str:
        if hasattr(event, "get_platform"):
            return event.get_platform() or ""
        if hasattr(event, "get"):
            return event.get("platform", "")
        return ""

    def _adapter(self, platform: str):
        return sdk.adapter.get(platform)

    def _resolve_story(self, story_id: str) -> list[dict]:
        results = []
        for s in self._repo.list_all_stories():
            if s["id"] == story_id:
                results.append({
                    "ref": f"repo:{s['repo_name']}|{story_id}",
                    "title": s.get("title", story_id),
                    "source": f"仓库: {s['repo_name']}",
                })
        for s in self._repo.list_imported():
            if s["id"] == story_id:
                results.append({
                    "ref": f"imported|{story_id}",
                    "title": s.get("title", story_id),
                    "source": "导入",
                })
        return results

    async def _find_story(self, event, ref: str) -> Optional[str]:
        if ref.startswith("repo:"):
            _, rest = ref.split(":", 1)
            repo_name, story_id = rest.split("|", 1)
            t = self._repo.get_cached_story(repo_name, story_id)
            if t:
                return t
            idx = self._repo.get_index(repo_name)
            if idx:
                for s in idx.get("stories", []):
                    if s["id"] == story_id:
                        ok, t, _ = await self._repo.download_story(repo_name, story_id)
                        if ok and t:
                            return t
        if ref.startswith("imported|"):
            story_id = ref.split("|", 1)[1]
            return self._repo.get_imported(story_id)
        t = self._repo.get_imported(ref)
        if t:
            return t
        for r in self._repo.list_repos():
            t = self._repo.get_cached_story(r["name"], ref)
            if t:
                return t
            idx = self._repo.get_index(r["name"])
            if not idx:
                continue
            for s in idx.get("stories", []):
                if s["id"] == ref:
                    ok, t, _ = await self._repo.download_story(r["name"], ref)
                    if ok and t:
                        return t
        return None

    def _get_stories_by_cat(self, cat: str) -> list[dict]:
        if cat == "repo":
            return self._repo.list_all_stories()
        return self._repo.list_imported()

    # ─── REST API routes ──────────────────────────────────────────

    def _register_routes(self):
        r = self.sdk.router
        r.register_http_route("CYOA", "/api/stats", handler=self._api_stats, methods=["GET"])
        r.register_http_route("CYOA", "/api/stories", handler=self._api_stories, methods=["GET"])
        r.register_http_route("CYOA", "/api/stories/upload", handler=self._api_upload, methods=["POST"])
        r.register_http_route("CYOA", "/api/stories/{story_id}", handler=self._api_story_delete, methods=["DELETE"])
        r.register_http_route("CYOA", "/api/saves", handler=self._api_saves, methods=["GET"])
        r.register_http_route("CYOA", "/api/saves/{save_key:path}", handler=self._api_save_delete, methods=["DELETE"])
        r.register_http_route("CYOA", "/api/repos", handler=self._api_repos, methods=["GET"])
        r.register_http_route("CYOA", "/api/repos", handler=self._api_repo_add, methods=["POST"])
        r.register_http_route("CYOA", "/api/repos/{name}/update", handler=self._api_repo_update, methods=["POST"])
        r.register_http_route("CYOA", "/api/repos/{name}", handler=self._api_repo_delete, methods=["DELETE"])

    def _unregister_routes(self):
        r = self.sdk.router
        for path in ["/api/stats", "/api/stories", "/api/stories/upload",
                     "/api/saves", "/api/repos"]:
            try:
                r.unregister_http_route("CYOA", path)
            except Exception:
                pass

    def _verify_request(self, request) -> bool:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return False
        if hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard:
            try:
                return self.sdk.Dashboard.verify_request(request)
            except Exception:
                pass
        config_token = os.environ.get("ERISPULSE_DASHBOARD_TOKEN", "")
        if config_token and token == config_token:
            return True
        return bool(token)

    async def _api_stats(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        all_stories = self._repo.list_all_stories()
        imported = self._repo.list_imported()
        repos = self._repo.list_repos()
        saves = self._repo.list_saves()
        active_games = len(self._sessions)
        return JSONResponse({
            "total_stories": len(all_stories) + len(imported),
            "repo_stories": len(all_stories),
            "imported_stories": len(imported),
            "repos": len(repos),
            "saves": len(saves),
            "active_games": active_games,
        })

    async def _api_stories(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        all_stories = self._repo.list_all_stories()
        imported = self._repo.list_imported()
        return JSONResponse({
            "repo_stories": all_stories,
            "imported_stories": imported,
        })

    async def _api_upload(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            form = await request.form()
            file = form.get("file")
            if not file:
                return JSONResponse({"error": "No file provided"}, status_code=400)
            content = await file.read()
            if len(content) > 20 * 1024 * 1024:
                return JSONResponse({"error": "File too large (max 20MB)"}, status_code=400)
            filename = file.filename or "story.ink.json"
            ok, sid, msg = self._repo.import_from_bytes(content, filename)
            if not ok:
                return JSONResponse({"error": msg}, status_code=400)
            return JSONResponse({"ok": True, "story_id": sid})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def _api_story_delete(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        story_id = request.path_params.get("story_id", "")
        ok = self._repo.delete_imported(story_id)
        if ok:
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Not found or not imported"}, status_code=404)

    async def _api_saves(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        saves = self._repo.list_saves()
        return JSONResponse({"saves": saves})

    async def _api_save_delete(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        key = "cyoa." + request.path_params.get("save_key", "")
        ok = self._repo.delete_save(key)
        if ok:
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Not found"}, status_code=404)

    async def _api_repos(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        repos = self._repo.list_repos()
        result = []
        for r in repos:
            index = self._repo.get_index(r["name"]) or {}
            stories = index.get("stories", [])
            result.append({**r, "stories": stories})
        return JSONResponse({"repos": result})

    async def _api_repo_add(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            data = await request.json()
            name = data.get("name", "").strip()
            url = data.get("url", "").strip()
            if not name or not url:
                return JSONResponse({"error": "name and url required"}, status_code=400)
            ok, msg = self._repo.add_repo(name, url)
            if not ok:
                return JSONResponse({"error": msg}, status_code=400)
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def _api_repo_update(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        name = request.path_params.get("name", "")
        ok, msg = await self._repo.update_repo(name)
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        return JSONResponse({"ok": True, "message": msg})

    async def _api_repo_delete(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        name = request.path_params.get("name", "")
        ok, msg = self._repo.remove_repo(name)
        if not ok:
            return JSONResponse({"error": msg}, status_code=404)
        return JSONResponse({"ok": True})

    # ─── Dashboard View ───────────────────────────────────────────

    def _register_dashboard_view(self):
        try:
            if not (hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard):
                return
            self.sdk.Dashboard.register_view(
                id="CYOA",
                title="互动小说管理", title_en="CYOA Manager",
                icon_svg='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                         '<path d="M4 19.5A2.5 2.5 0 016.5 17H20"/>'
                         '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>'
                         '<path d="M12 7l3 3-3 3"/></svg>',
                html_content=self._dashboard_html(),
                js_content=self._dashboard_js(),
                css_content=self._dashboard_css(),
                loader="loadCYOAView",
                group="group_tools",
            )
        except Exception as e:
            self.logger.warning(f"Dashboard register failed: {e}")

    @staticmethod
    def _dashboard_css():
        return '.cy-table{width:100%;border-collapse:collapse;font-size:13px;}.cy-table th{text-align:left;padding:8px 10px;border-bottom:2px solid var(--bd);color:var(--tx-s);font-weight:600;}.cy-table td{padding:8px 10px;border-bottom:1px solid var(--bd);}.cy-table tr:hover td{background:var(--bg-s);}.cy-badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600;}.cy-badge-repo{background:rgba(139,92,246,0.1);color:#8b5cf6;}.cy-badge-imported{background:rgba(34,197,94,0.1);color:#22c55e;}.cy-btn{padding:4px 12px;border:none;border-radius:6px;cursor:pointer;font-size:12px;margin-right:4px;}.cy-btn-primary{background:var(--accent);color:#fff;}.cy-btn-danger{background:#ef4444;color:#fff;}.cy-btn-sm{padding:3px 8px;font-size:11px;}.cy-stats{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap;}.cy-stat{background:var(--bg-t);border-radius:8px;padding:12px 18px;min-width:100px;}.cy-stat-num{font-size:22px;font-weight:bold;color:var(--accent);}.cy-stat-label{font-size:11px;color:var(--tx-s);margin-top:2px;}.cy-modal-bg{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:100;}.cy-modal{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--bg-p);border-radius:12px;padding:24px;min-width:360px;max-width:90vw;max-height:80vh;overflow-y:auto;}.cy-modal h3{margin:0 0 16px;font-size:16px;color:var(--tx-p);}.cy-modal label{display:block;font-size:12px;color:var(--tx-s);margin-bottom:4px;margin-top:10px;}.cy-modal input,.cy-modal select{width:100%;padding:8px;border:1px solid var(--bd);border-radius:6px;background:var(--bg-s);color:var(--tx-p);box-sizing:border-box;}.cy-upload-zone{border:2px dashed var(--bd);border-radius:8px;padding:30px;text-align:center;cursor:pointer;color:var(--tx-s);margin-top:10px;}.cy-upload-zone:hover{border-color:var(--accent);color:var(--accent);}.cy-upload-zone.dragover{background:rgba(139,92,246,0.05);border-color:var(--accent);}.cy-section-title{font-size:15px;font-weight:bold;color:var(--tx-p);margin:20px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--bd);}'

    @staticmethod
    def _dashboard_html():
        return '<h1 class="page-title">\u4e92\u52a8\u5c0f\u8bf4\u7ba1\u7406</h1><div class="cy-stats" id="cy-stats"></div><div class="cy-section-title">\u6545\u4e8b\u5217\u8868</div><div style="margin-bottom:12px;"><button class="btn btn-primary" onclick="cyOpenUpload()">\u4e0a\u4f20\u6545\u4e8b</button><button class="btn btn-secondary" onclick="cyLoadStories()">\u5237\u65b0</button></div><div style="overflow-x:auto;"><table class="cy-table"><thead><tr><th>ID</th><th>\u6807\u9898</th><th>\u6765\u6e90</th><th>\u4f5c\u8005</th><th>\u64cd\u4f5c</th></tr></thead><tbody id="cy-stories-body"><tr><td colspan="5" style="color:var(--tx-s);">\u52a0\u8f7d\u4e2d...</td></tr></tbody></table></div><div class="cy-section-title">\u5b58\u6863\u7ba1\u7406</div><div style="overflow-x:auto;"><table class="cy-table"><thead><tr><th>\u6545\u4e8b ID</th><th>\u7528\u6237</th><th>\u69fd\u4f4d</th><th>\u4fdd\u5b58\u65f6\u95f4</th><th>\u64cd\u4f5c</th></tr></thead><tbody id="cy-saves-body"><tr><td colspan="5" style="color:var(--tx-s);">\u52a0\u8f7d\u4e2d...</td></tr></tbody></table></div><div class="cy-section-title">\u4ed3\u5e93\u7ba1\u7406</div><div style="margin-bottom:12px;"><button class="btn btn-primary" onclick="cyOpenAddRepo()">\u6dfb\u52a0\u4ed3\u5e93</button></div><div style="overflow-x:auto;"><table class="cy-table"><thead><tr><th>\u540d\u79f0</th><th>URL</th><th>\u6545\u4e8b\u6570</th><th>\u64cd\u4f5c</th></tr></thead><tbody id="cy-repos-body"><tr><td colspan="4" style="color:var(--tx-s);">\u52a0\u8f7d\u4e2d...</td></tr></tbody></table></div><div class="cy-modal-bg" id="cy-upload-modal"><div class="cy-modal"><h3>\u4e0a\u4f20\u6545\u4e8b</h3><p style="font-size:12px;color:var(--tx-s);margin:0 0 10px;">\u652f\u6301 .ink.json \u6587\u4ef6\uff08\u6700\u5927 20MB\uff09</p><div class="cy-upload-zone" id="cy-upload-zone" onclick="document.getElementById(\'cy-file-input\').click()" ondragover="event.preventDefault();this.classList.add(\'dragover\')" ondragleave="this.classList.remove(\'dragover\')" ondrop="event.preventDefault();this.classList.remove(\'dragover\');cyHandleFiles(event.dataTransfer.files)">\u70b9\u51fb\u6216\u62d6\u62fd\u6587\u4ef6\u5230\u6b64\u5904</div><input type="file" id="cy-file-input" accept=".json,.ink.json" style="display:none" onchange="cyHandleFiles(this.files)"><div id="cy-upload-status" style="margin-top:10px;font-size:12px;color:var(--tx-s);"></div><div style="margin-top:16px;text-align:right;"><button class="btn btn-secondary" onclick="cyCloseUpload()">\u5173\u95ed</button></div></div></div><div class="cy-modal-bg" id="cy-repo-modal"><div class="cy-modal"><h3>\u6dfb\u52a0\u4ed3\u5e93</h3><label>\u4ed3\u5e93\u540d\u79f0</label><input id="cy-repo-name" placeholder="my-stories"><label>\u4ed3\u5e93 URL</label><input id="cy-repo-url" placeholder="https://example.com/stories"><div style="margin-top:16px;text-align:right;"><button class="btn btn-secondary" onclick="cyCloseAddRepo()">\u53d6\u6d88</button><button class="btn btn-primary" onclick="cySubmitRepo()">\u6dfb\u52a0</button></div></div></div>'

    @staticmethod
    def _dashboard_js():
        return "function cyApi(m,p,b){var t=localStorage.getItem('__ep_tk__');var o={method:m,headers:{'Authorization':'Bearer '+t}};if(b){if(b instanceof FormData){o.body=b;}else{o.headers['Content-Type']='application/json';o.body=JSON.stringify(b);}}return fetch('/CYOA'+p,o).then(function(r){return r.json();});}function esc(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}function fmtTime(ts){if(!ts)return '-';var d=new Date(ts*1000);return d.toLocaleString();}function loadCYOAView(){cyLoadStats();cyLoadStories();cyLoadSaves();cyLoadRepos();}function cyLoadStats(){cyApi('GET','/api/stats').then(function(d){if(d.error)return;document.getElementById('cy-stats').innerHTML='<div class=\"cy-stat\"><div class=\"cy-stat-num\">'+(d.total_stories||0)+'</div><div class=\"cy-stat-label\">\u603b\u6545\u4e8b\u6570</div></div>'+'<div class=\"cy-stat\"><div class=\"cy-stat-num\">'+(d.imported_stories||0)+'</div><div class=\"cy-stat-label\">\u5df2\u5bfc\u5165</div></div>'+'<div class=\"cy-stat\"><div class=\"cy-stat-num\">'+(d.repos||0)+'</div><div class=\"cy-stat-label\">\u4ed3\u5e93</div></div>'+'<div class=\"cy-stat\"><div class=\"cy-stat-num\">'+(d.saves||0)+'</div><div class=\"cy-stat-label\">\u5b58\u6863</div></div>'+'<div class=\"cy-stat\"><div class=\"cy-stat-num\">'+(d.active_games||0)+'</div><div class=\"cy-stat-label\">\u8fdb\u884c\u4e2d</div></div>';});}function cyLoadStories(){cyApi('GET','/api/stories').then(function(d){if(d.error)return;var h='';(d.repo_stories||[]).forEach(function(s){h+='<tr><td>'+esc(s.id)+'</td><td>'+esc(s.title)+'</td><td><span class=\"cy-badge cy-badge-repo\">'+esc(s.repo_name)+'</span></td><td>'+esc(s.author)+'</td><td>-</td></tr>';});(d.imported_stories||[]).forEach(function(s){h+='<tr><td>'+esc(s.id)+'</td><td>'+esc(s.title)+'</td><td><span class=\"cy-badge cy-badge-imported\">\u5bfc\u5165</span></td><td>'+esc(s.author)+'</td><td><button class=\"cy-btn cy-btn-danger cy-btn-sm\" data-sid=\"'+esc(s.id)+'\" onclick=\"cyDeleteStory(this.dataset.sid)\">\u5220\u9664</button></td></tr>';});if(!h)h='<tr><td colspan=\"5\" style=\"color:var(--tx-s);\">\u6682\u65e0\u6545\u4e8b</td></tr>';document.getElementById('cy-stories-body').innerHTML=h;});}function cyLoadSaves(){cyApi('GET','/api/saves').then(function(d){if(d.error)return;var h='';(d.saves||[]).forEach(function(s){var k=(s._key||'').replace('cyoa.','');h+='<tr><td>'+esc(s.story_id)+'</td><td>'+esc(s.user_id)+'</td><td>'+(s.saved_slot||1)+'</td><td>'+fmtTime(s.saved_at)+'</td><td><button class=\"cy-btn cy-btn-danger cy-btn-sm\" data-sk=\"'+esc(k)+'\" onclick=\"cyDeleteSave(this.dataset.sk)\">\u5220\u9664</button></td></tr>';});if(!h)h='<tr><td colspan=\"5\" style=\"color:var(--tx-s);\">\u6682\u65e0\u5b58\u6863</td></tr>';document.getElementById('cy-saves-body').innerHTML=h;});}function cyLoadRepos(){cyApi('GET','/api/repos').then(function(d){if(d.error)return;var h='';(d.repos||[]).forEach(function(r){h+='<tr><td>'+esc(r.name)+'</td><td style=\"word-break:break-all;\">'+esc(r.url)+'</td><td>'+(r.story_count||0)+'</td><td><button class=\"cy-btn cy-btn-primary cy-btn-sm\" data-rn=\"'+esc(r.name)+'\" onclick=\"cyUpdateRepo(this.dataset.rn)\">\u66f4\u65b0</button><button class=\"cy-btn cy-btn-danger cy-btn-sm\" data-rn2=\"'+esc(r.name)+'\" onclick=\"cyDeleteRepo(this.dataset.rn2)\">\u5220\u9664</button></td></tr>';});if(!h)h='<tr><td colspan=\"4\" style=\"color:var(--tx-s);\">\u6682\u65e0\u4ed3\u5e93</td></tr>';document.getElementById('cy-repos-body').innerHTML=h;});}function cyDeleteStory(id){if(!confirm('\u786e\u5b9a\u5220\u9664\u6545\u4e8b '+id+'\uff1f'))return;cyApi('DELETE','/api/stories/'+encodeURIComponent(id)).then(function(r){if(r.ok){cyLoadStories();cyLoadStats();}else{alert(r.error||'\u5220\u9664\u5931\u8d25');}});}function cyDeleteSave(key){if(!confirm('\u786e\u5b9a\u5220\u9664\u8be5\u5b58\u6863\uff1f'))return;cyApi('DELETE','/api/saves/'+encodeURIComponent(key)).then(function(r){if(r.ok){cyLoadSaves();cyLoadStats();}else{alert(r.error||'\u5220\u9664\u5931\u8d25');}});}function cyUpdateRepo(name){cyApi('POST','/api/repos/'+encodeURIComponent(name)+'/update').then(function(r){if(r.ok){alert('\u66f4\u65b0\u6210\u529f: '+r.message);cyLoadRepos();cyLoadStories();cyLoadStats();}else{alert(r.error||'\u66f4\u65b0\u5931\u8d25');}});}function cyDeleteRepo(name){if(!confirm('\u786e\u5b9a\u5220\u9664\u4ed3\u5e93 '+name+'\uff1f'))return;cyApi('DELETE','/api/repos/'+encodeURIComponent(name)).then(function(r){if(r.ok){cyLoadRepos();cyLoadStories();cyLoadStats();}else{alert(r.error||'\u5220\u9664\u5931\u8d25');}});}function cyOpenUpload(){document.getElementById('cy-upload-modal').style.display='block';document.getElementById('cy-upload-status').textContent='';}function cyCloseUpload(){document.getElementById('cy-upload-modal').style.display='none';}function cyHandleFiles(files){if(!files||!files.length)return;var f=files[0];var st=document.getElementById('cy-upload-status');if(f.size>20*1024*1024){st.textContent='\u6587\u4ef6\u8fc7\u5927\uff08\u6700\u5927 20MB\uff09';st.style.color='#ef4444';return;}st.textContent='\u4e0a\u4f20\u4e2d...';st.style.color='var(--tx-s)';var fd=new FormData();fd.append('file',f);cyApi('POST','/api/stories/upload',fd).then(function(r){if(r.ok){st.textContent='\u4e0a\u4f20\u6210\u529f\uff01ID: '+r.story_id;st.style.color='#22c55e';cyLoadStories();cyLoadStats();}else{st.textContent='\u4e0a\u4f20\u5931\u8d25: '+(r.error||'');st.style.color='#ef4444';}}).catch(function(e){st.textContent='\u4e0a\u4f20\u5931\u8d25: '+e.message;st.style.color='#ef4444';});}function cyOpenAddRepo(){document.getElementById('cy-repo-modal').style.display='block';}function cyCloseAddRepo(){document.getElementById('cy-repo-modal').style.display='none';}function cySubmitRepo(){var n=document.getElementById('cy-repo-name').value.trim();var u=document.getElementById('cy-repo-url').value.trim();if(!n||!u){alert('\u8bf7\u586b\u5199\u540d\u79f0\u548c URL');return;}cyApi('POST','/api/repos',{name:n,url:u}).then(function(r){if(r.ok){cyCloseAddRepo();document.getElementById('cy-repo-name').value='';document.getElementById('cy-repo-url').value='';cyLoadRepos();cyLoadStats();}else{alert(r.error||'\u6dfb\u52a0\u5931\u8d25');}});}"
