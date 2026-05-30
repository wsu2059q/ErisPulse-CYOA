from __future__ import annotations
from typing import Optional

from ErisPulse import sdk
from ErisPulse.Core.Bases import BaseModule
from ErisPulse.Core.Event import command, notice, message
from ErisPulse.loaders import ModuleLoadStrategy

from .engines.ink_engine import InkEngine, HAS_INK
from .models.session import GameSession
from .platform_buttons import PlatformButtons
from .story_repo import StoryRepo


class Main(BaseModule):
    def __init__(self):
        self.sdk = sdk
        self.logger = sdk.logger.get_child("CYOA")
        self.config = self._cfg()
        self._repo = StoryRepo(sdk.storage, self.logger)
        self._btn = PlatformButtons()
        self._engines: dict[str, InkEngine] = {}
        self._sessions: dict[str, GameSession] = {}
        self._locks: set[str] = set()

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
        self._load_sessions()

        @command("cyoa", aliases=["互动小说", "故事"], help="Ink 互动小说")
        async def _cyoa(evt):
            await self._dispatch(evt)

        self._btn_h = notice.on_notice(priority=40)(self._on_button)
        self._msg_h = message.on_message(priority=40)(self._on_message)
        self.logger.info("CYOA loaded (Ink)")

    async def on_unload(self, event):
        self._save_all()
        if self._msg_h:
            message.unregister(self._msg_h)
        self.logger.info("CYOA unloaded")

    # ─── dispatch ─────────────────────────────────────────────────

    async def _dispatch(self, event):
        args = event.get_command_args() if hasattr(event, "get_command_args") else []
        if isinstance(args, str):
            args = args.split() if args else []
        if not args:
            return await self._help(event)

        sub = args[0].lower()
        rest = args[1:]

        cmds = {
            "list": self._list, "ls": self._list,
            "play": self._play, "开始": self._play,
            "import": self._import, "导入": self._import,
            "repo": self._repo_cmd, "仓库": self._repo_cmd,
            "save": self._save, "存档": self._save,
            "load": self._load, "读档": self._load,
            "restart": self._restart,
            "quit": self._quit, "exit": self._quit,
        }

        fn = cmds.get(sub)
        if fn:
            await fn(event, *rest) if rest else await fn(event)
        else:
            await event.reply("未知命令。 /cyoa 查看帮助。")

    async def _help(self, event):
        await event.reply(
            "CYOA Ink 互动小说\n"
            "/cyoa list - 故事\n"
            "/cyoa play <ID> - 开始\n"
            "/cyoa import <URL> - 导入\n"
            "/cyoa save|load|restart|quit\n"
            "/cyoa repo list|add|remove|update"
        )

    # ─── commands ───────────────────────────────────────────────────

    async def _list(self, event):
        repo = self._repo.list_all_stories()
        imp = self._repo.list_imported()
        if not repo and not imp:
            return await event.reply("暂无故事。\n/cyoa import <URL> 或 /cyoa repo add <名> <URL>")

        lines = ["故事:\n"]
        for s in repo:
            lines.append(f"  {s.get('title', s['id'])} [仓库:{s.get('repo_name','?')}]")
            lines.append(f"     ID: {s['id']}  作者: {s.get('author','?')}  v{s.get('version','1.0')}")
            if s.get("description"):
                lines.append(f"     {s['description']}")
            lines.append("")
        for s in imp:
            lines.append(f"  {s.get('title', s['id'])} [导入]")
            lines.append(f"     ID: {s['id']}")
            lines.append("")
        lines.append("/cyoa play <ID>")
        await event.reply("\n".join(lines))

    async def _play(self, event, story_id=""):
        if not story_id:
            return await event.reply("/cyoa play <故事ID>")

        if not HAS_INK:
            return await event.reply("inkpython 未安装。 pip install inkpython")

        key = self._key(event, story_id)
        if key in self._sessions:
            return await event.reply("已在游戏中。 /cyoa quit 退出。")

        ink_json = await self._find_story(event, story_id)
        if not ink_json:
            return

        saved = self._get_save(event, story_id)
        state = saved.get("ink_state") if saved else None

        try:
            engine = InkEngine(ink_json, state)
        except Exception as e:
            self.logger.error(f"Ink init: {e}")
            return await event.reply(f"加载失败: {e}")

        session = GameSession(
            story_id=story_id,
            user_id=self._uid(event),
            group_id=self._gid(event),
            platform=self._plat(event),
        )
        self._sessions[key] = session
        self._engines[key] = engine

        try:
            plat = self._plat(event)
            if self._btn.supports_buttons(plat):
                if await self._try_btn(event, key):
                    return
            await self._loop(event, key)
        except Exception as e:
            self.logger.error(f"Render: {e}")
            await event.reply(engine.text or "(开始)")

    async def _find_story(self, event, story_id: str) -> Optional[str]:
        # imported
        t = self._repo.get_imported(story_id)
        if t:
            return t
        # cached
        for r in self._repo.list_repos():
            t = self._repo.get_cached_story(r["name"], story_id)
            if t:
                return t
        # download
        for r in self._repo.list_repos():
            idx = self._repo.get_index(r["name"])
            if not idx:
                continue
            for s in idx.get("stories", []):
                if s["id"] == story_id:
                    await event.reply("下载中...")
                    ok, t, msg = await self._repo.download_story(r["name"], story_id)
                    if ok and t:
                        return t
                    await event.reply(f"下载失败: {msg}")
                    return None
        await event.reply(f"未找到 '{story_id}'。")
        return None

    async def _import(self, event, *args):
        if not args:
            return await event.reply("/cyoa import <URL>\n导入 Inky/inklecate 编译的 .ink.json 文件。")

        await event.reply("下载中...")
        ok, sid, ink_json, msg = await self._repo.import_story(args[0])
        if not ok:
            return await event.reply(f"导入失败: {msg}")
        await event.reply(f"已导入\nID: {sid}\n/cyoa play {sid}")

    async def _save(self, event, slot="1"):
        _, key = self._find(event)
        if not key:
            return await event.reply("无游戏中。")
        try:
            slot = int(slot)
        except ValueError:
            slot = 1
        self._persist(key, slot)
        await event.reply(f"已保存到槽位 {slot}")

    async def _load(self, event, slot="1"):
        try:
            slot = int(slot)
        except ValueError:
            slot = 1
        sid = self._cur_story(event)
        if not sid:
            return await event.reply("无可用故事。")
        saved = self._get_save(event, sid, slot)
        if not saved:
            return await event.reply("无存档。")
        old = self._find(event)[1]
        if old:
            self._remove(old)
        await self._play(event, sid)

    async def _restart(self, event):
        _, key = self._find(event)
        if not key:
            return await event.reply("无游戏中。")
        sid = self._sessions[key].story_id
        self._remove(key)
        await self._play(event, sid)

    async def _quit(self, event):
        _, key = self._find(event)
        if not key:
            return await event.reply("无游戏中。")
        self._persist(key, 1)
        self._remove(key)
        await event.reply("已退出，进度已保存。")

    async def _repo_cmd(self, event, *args):
        args = list(args)
        if not args:
            repos = self._repo.list_repos()
            if not repos:
                return await event.reply("暂无仓库。\n/cyoa repo add <名> <URL>")
            lines = ["仓库:\n"]
            for r in repos:
                lines.append(f"  {r['name']} ({r.get('story_count',0)} 故事)")
                lines.append(f"     {r['url']}\n")
            return await event.reply("\n".join(lines))

        sub = args[0].lower()
        rest = args[1:]

        if sub in ("add", "添加"):
            if len(rest) < 2:
                return await event.reply("/cyoa repo add <名> <URL>")
            ok, msg = self._repo.add_repo(rest[0], rest[1])
            await event.reply(msg if not ok else f"已添加 '{rest[0]}'。 /cyoa repo update 获取列表。")

        elif sub in ("remove", "rm", "删除"):
            if not rest:
                return await event.reply("/cyoa repo remove <名>")
            ok, msg = self._repo.remove_repo(rest[0])
            await event.reply(msg)

        elif sub in ("update", "更新"):
            if rest:
                ok, msg = await self._repo.update_repo(rest[0])
                await event.reply(f"更新 '{rest[0]}': {msg}")
            else:
                results = await self._repo.update_all()
                lines = ["更新:\n"]
                for name, msg in results.items():
                    lines.append(f"  {name}: {msg}")
                await event.reply("\n".join(lines))
        else:
            await event.reply("/cyoa repo [list|add|remove|update]")

    # ─── rendering ─────────────────────────────────────────────────

    async def _try_btn(self, event, key: str) -> bool:
        eng = self._engines.get(key)
        if not eng:
            return False
        if not eng.text and not eng.choices:
            return False
        try:
            await self._send(event, key)
            return True
        except Exception as e:
            self.logger.warning(f"Btn: {e}")
            return False

    async def _send(self, event, key: str):
        eng = self._engines.get(key)
        s = self._sessions.get(key)
        if not eng or not s:
            return

        ad = self._adapter(s.platform)
        if not ad:
            return

        t = "group" if s.group_id else "user"
        tid = s.group_id or s.user_id

        if eng.image:
            try:
                await ad.Send.To(t, tid).Image(eng.image)
            except Exception:
                pass

        if eng.choices and self._btn.supports_buttons(s.platform):
            try:
                await self._btn.send(ad, s.platform, t, tid, eng.text, eng.choices)
                return
            except Exception:
                pass

        if eng.text:
            await ad.Send.To(t, tid).Text(eng.text)

    async def _loop(self, event, key: str):
        if key in self._locks:
            return
        self._locks.add(key)

        try:
            eng = self._engines.get(key)

            while eng and not eng.is_ended and key in self._sessions:
                text = eng.text
                choices = eng.choices
                img = eng.image

                if not text and not choices:
                    break

                if img:
                    await self._try_img(event, img)

                if not choices:
                    if text:
                        await event.reply(text)
                    break

                opts = [c["text"] for c in choices]
                prompt = text if text else "请选择:"
                idx = await event.choose(prompt, opts, timeout=self._timeout)

                if idx is None:
                    await event.reply("超时。 /cyoa load 恢复。")
                    self._persist(key, 1)
                    self._remove(key)
                    break

                if key not in self._sessions:
                    break

                eng.choose(idx)
                eng = self._engines.get(key)

                if eng and eng.is_ended:
                    await event.reply(eng.text or "故事结束。")
                    self._persist(key, 1)
                    self._remove(key)
                    break

        except Exception as e:
            self.logger.error(f"Loop: {e}")
            try:
                await event.reply("出错，已保存。")
                self._persist(key, 1)
            except Exception:
                pass
        finally:
            self._locks.discard(key)

    async def _try_img(self, event, url: str):
        try:
            ad = self._adapter(self._plat(event))
            if ad:
                await ad.Send.To(
                    "group" if self._gid(event) else "user",
                    self._gid(event) or self._uid(event),
                ).Image(url)
                return
        except Exception:
            pass
        try:
            await event.reply(f"[图片] {url}")
        except Exception:
            pass

    # ─── button callback ───────────────────────────────────────────

    async def _on_button(self, event):
        idx = self._btn.parse_callback(event)
        if idx is None:
            return

        try:
            uid = self._uid(event)
            if not uid:
                return

            key = None
            for k in self._sessions:
                if k.startswith(uid):
                    key = k
                    break
            if not key:
                return

            eng = self._engines.get(key)
            if not eng:
                return

            await self._ack(event)
            eng.choose(idx)

            if eng.is_ended:
                await self._send(event, key)
                self._persist(key, 1)
                self._remove(key)
                return

            await self._send(event, key)

        except Exception as e:
            self.logger.error(f"Button: {e}")

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
                        import asyncio
                        asyncio.ensure_future(ad.Send.AnswerCallback(cid, text=""))
        except Exception:
            pass

    async def _on_message(self, event):
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

    def _load_sessions(self):
        keys = sdk.storage.keys() if hasattr(sdk.storage, "keys") else []
        for k in keys:
            if k.startswith("cyoa.saves."):
                try:
                    st = sdk.storage.get(k)
                    if st and st.get("story_id"):
                        self.logger.info(f"Save found: {st['story_id']}")
                except Exception:
                    pass

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
