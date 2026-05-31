from __future__ import annotations
import json
import os
import time
import aiohttp
from typing import Any, Optional


class StoryRepo:
    def __init__(self, storage: Any, logger: Any = None):
        self._storage = storage
        self._logger = logger
        self._cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

    def _repo_key(self, name: str) -> str:
        return f"cyoa.repos.{name}"

    def _index_key(self, name: str) -> str:
        return f"cyoa.repos.{name}.index"

    def add_repo(self, name: str, url: str) -> tuple[bool, str]:
        if self._storage.get(self._repo_key(name)):
            return False, f"仓库 '{name}' 已存在"
        self._storage.set(self._repo_key(name), {"name": name, "url": url.rstrip("/")})
        if self._logger:
            self._logger.info(f"Added repo: {name}")
        return True, "OK"

    def remove_repo(self, name: str) -> tuple[bool, str]:
        if not self._storage.get(self._repo_key(name)):
            return False, f"仓库 '{name}' 不存在"
        self._storage.delete(self._repo_key(name))
        self._storage.delete(self._index_key(name))
        return True, "OK"

    def list_repos(self) -> list[dict]:
        result = []
        keys = self._storage.keys() if hasattr(self._storage, "keys") else []
        for key in keys:
            if key.startswith("cyoa.repos.") and not key.endswith(".index"):
                repo = self._storage.get(key)
                if repo:
                    index = self._storage.get(self._index_key(repo.get("name", ""))) or {}
                    repo["story_count"] = len(index.get("stories", []))
                    result.append(repo)
        return result

    def get_repo(self, name: str) -> Optional[dict]:
        return self._storage.get(self._repo_key(name))

    def get_index(self, name: str) -> Optional[dict]:
        return self._storage.get(self._index_key(name))

    async def update_repo(self, name: str) -> tuple[bool, str]:
        repo = self.get_repo(name)
        if not repo:
            return False, f"仓库 '{name}' 不存在"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{repo['url']}/index.json", timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return False, f"HTTP {resp.status}"
                    text = await resp.text()
                    index = json.loads(text)
        except aiohttp.ClientError as e:
            return False, f"网络错误: {e}"
        except json.JSONDecodeError:
            return False, "index.json 格式错误"

        if not isinstance(index, dict) or "stories" not in index:
            return False, "index.json 缺少 stories 字段"

        self._storage.set(self._index_key(name), index)
        count = len(index.get("stories", []))
        if self._logger:
            self._logger.info(f"Updated '{name}': {count} stories")
        return True, f"OK: {count} 个故事"

    async def update_all(self) -> dict[str, str]:
        results = {}
        for repo in self.list_repos():
            ok, msg = await self.update_repo(repo["name"])
            results[repo["name"]] = msg
        return results

    async def download_story(self, repo_name: str, story_id: str) -> tuple[bool, Optional[str], str]:
        repo = self.get_repo(repo_name)
        if not repo:
            return False, None, f"仓库 '{repo_name}' 不存在"

        base = f"{repo['url']}/stories/{story_id}"
        for ext in (".ink.json", ".json"):
            url = f"{base}/story{ext}"
            result = await self._try_download(url)
            if result:
                return result

        return False, None, "story.ink.json 未找到"

    async def _try_download(self, url: str) -> Optional[tuple[bool, Optional[str], str]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return None
                    return True, await resp.text(), "OK"
        except Exception:
            return None

    def get_cached_story(self, repo_name: str, story_id: str) -> Optional[str]:
        for ext in (".ink.json", ".json"):
            path = os.path.join(self._cache_dir, repo_name, story_id, f"story{ext}")
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
        return None

    def list_all_stories(self) -> list[dict]:
        results = []
        for repo in self.list_repos():
            index = self.get_index(repo["name"])
            if not index:
                continue
            for story in index.get("stories", []):
                story["repo_name"] = repo["name"]
                results.append(story)
        return results

    # ─── Imported ─────────────────────────────────────────────────

    def _validate_ink_json(self, text: str) -> tuple[bool, Optional[dict], str]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False, None, "无效 JSON"
        if not isinstance(data, dict) or "inkVersion" not in data:
            return False, None, "不是有效的 Ink JSON 文件（缺少 inkVersion）。请用 Inky/inklecate 编译 .ink 文件。"
        return True, data, "OK"

    def _save_imported_file(self, story_id: str, content: str):
        dir_path = os.path.join(self._cache_dir, "imported", story_id)
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, "story.ink.json"), "w", encoding="utf-8") as f:
            f.write(content)

    def _register_imported(self, story_id: str, url: str = "", title: str = ""):
        imported = self._storage.get("cyoa.imported") or []
        if not any(s.get("id") == story_id for s in imported):
            imported.append({
                "id": story_id,
                "title": title or story_id,
                "author": "Unknown",
                "version": "1.0.0",
                "url": url,
                "imported_at": time.time(),
            })
            self._storage.set("cyoa.imported", imported)

    async def import_story(self, url: str) -> tuple[bool, Optional[str], Optional[str], str]:
        import re as _re
        dl = url
        if "github.com" in dl and "/blob/" in dl:
            dl = _re.sub(r"https://github\.com/(.+?)/blob/(.+)", r"https://raw.githubusercontent.com/\1/\2", dl)
        elif "gitee.com" in dl and "/blob/" in dl:
            dl = dl.replace("/blob/", "/raw/")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(dl, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return False, None, None, f"HTTP {resp.status}"
                    ct = resp.headers.get("Content-Type", "")
                    text = await resp.text()
                    if "text/html" in ct and not text.strip().startswith("{"):
                        return False, None, None, "获取到网页而非 JSON，请使用 raw 链接。"
        except aiohttp.ClientError as e:
            return False, None, None, f"网络错误: {e}"

        ok, data, msg = self._validate_ink_json(text)
        if not ok:
            return False, None, None, msg

        story_id = url.rsplit("/", 1)[-1].replace(".ink.json", "").replace(".json", "")
        if not story_id or story_id in ("raw", "blob", "main", "master"):
            story_id = f"imported_{int(time.time())}"

        self._save_imported_file(story_id, text)
        self._register_imported(story_id, url=dl, title=data.get("title", ""))

        return True, story_id, text, "OK"

    def import_from_content(self, json_str: str, source: str = "paste") -> tuple[bool, Optional[str], str]:
        ok, data, msg = self._validate_ink_json(json_str)
        if not ok:
            return False, None, msg

        story_id = f"imported_{int(time.time())}"

        self._save_imported_file(story_id, json_str)
        self._register_imported(story_id, url=f"{source}://{story_id}", title=data.get("title", ""))

        if self._logger:
            self._logger.info(f"Imported from {source}: {story_id}")
        return True, story_id, "OK"

    def import_from_bytes(self, data: bytes, filename: str = "") -> tuple[bool, Optional[str], str]:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("gbk")
            except UnicodeDecodeError:
                return False, None, "文件编码无法识别，请使用 UTF-8 编码。"

        source = "file"
        if filename:
            clean = filename.replace(".ink.json", "").replace(".json", "")
            if clean and clean not in ("raw", "blob", "main", "master"):
                source = f"file:{clean}"

        return self.import_from_content(text, source=source)

    def list_imported(self) -> list[dict]:
        return self._storage.get("cyoa.imported") or []

    def get_imported(self, story_id: str) -> Optional[str]:
        path = os.path.join(self._cache_dir, "imported", story_id, "story.ink.json")
        if not os.path.isfile(path):
            path = os.path.join(self._cache_dir, "imported", story_id, "story.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def delete_imported(self, story_id: str) -> bool:
        imported = self._storage.get("cyoa.imported") or []
        updated = [s for s in imported if s.get("id") != story_id]
        if len(updated) == len(imported):
            return False
        self._storage.set("cyoa.imported", updated)
        import shutil
        p = os.path.join(self._cache_dir, "imported", story_id)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        return True

    def list_saves(self) -> list[dict]:
        saves = []
        keys = self._storage.keys() if hasattr(self._storage, "keys") else []
        for k in keys:
            if k.startswith("cyoa.saves."):
                try:
                    st = self._storage.get(k)
                    if st and st.get("story_id"):
                        st["_key"] = k
                        saves.append(st)
                except Exception:
                    pass
        return saves

    def delete_save(self, key: str) -> bool:
        if self._storage.get(key):
            self._storage.delete(key)
            return True
        return False
