# -*- coding: utf-8 -*-
"""实况照片备份查看器 V1.3 · 相册索引模块

职责：``相册索引.json`` 的读写、原子落盘、损坏自愈与相册 CRUD。

设计依据：``V1.3设计\\04_V1.3_分类体系与数据规格.md``（冻结版 V1.1）。

红线约束（V1.3 红线 L13 / L8）：
    - 本模块**只读写 ``相册索引.json``**，与 ``.processed.json`` 完全隔离，
      不复用、不合并、不改写其键值语义；
    - 索引是**旁路数据**：损坏或丢失都不影响原始照片与备份产物。

本模块为 V1.3 新增代码，不属于 V1.2 的 12 个受保护函数。
"""

import datetime
import json
import os
import shutil

SCHEMA = "livephoto-album-index/1.0"
INDEX_NAME = "相册索引.json"
BACKUP_NAME = "相册索引.json.bak"
TMP_NAME = "相册索引.json.tmp"

MAX_NAME_LEN = 30
ILLEGAL_NAME_CHARS = set('\\/:*?"<>|')

# 相册 id 前缀（一经分配永不复用，避免旧记录指向新相册）
PREFIX_DIR = "alb_dir"
PREFIX_MAN = "alb_man"


def _now_iso():
    """当前时间 ISO8601（带本地时区）。"""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _date_stamp():
    return datetime.datetime.now().strftime("%Y%m%d")


def photo_key(rel_dir, base_name):
    """构造 photo_key：``<源根相对目录>/<基名小写>``，分隔符统一 ``/``。

    只依赖相对路径，不依赖盘符或绝对路径 → 换盘符/换机器后仍能命中。
    """
    base = str(base_name).lower()
    rel = (rel_dir or "").replace("\\", "/").strip("/")
    return rel + "/" + base if rel else base


def is_valid_album_name(name):
    """相册名是否合法：非空、不超长、不含非法字符。"""
    if not name:
        return False
    if len(name) > MAX_NAME_LEN:
        return False
    return not (set(name) & ILLEGAL_NAME_CHARS)


def truncate_album_name(name):
    """目录名过长时截断并加省略号，原文另存 ``source_path``（04 号 A-7）。"""
    if len(name) <= MAX_NAME_LEN:
        return name
    return name[: MAX_NAME_LEN - 1] + "…"


class AlbumIndex(object):
    """``相册索引.json`` 的内存模型 + 原子读写。

    使用方式::

        idx = AlbumIndex.load(output_dir)
        idx.ensure_dir_albums(["旅行", "美食"])   # 自动归类
        idx.create_album("家人")
        idx.assign(["旅行/云南/img_0346"], ["alb_man_..."])
        idx.save()                                  # 原子落盘
    """

    def __init__(self, output_dir, data=None, recovered=False):
        self.output_dir = os.path.abspath(output_dir)
        self.recovered = recovered          # True 表示本次内容来自 .bak 自愈
        self.write_blocked = False          # True 表示 schema 不认识，禁止写入
        self.dirty = False
        if data is None:
            data = {
                "schema": SCHEMA,
                "updated_at": "",
                "source_root": "",
                "albums": [],
                "assignments": {},
                "orphans": [],
            }
        self.data = data

    # ---------- 路径 ----------

    @property
    def index_path(self):
        return os.path.join(self.output_dir, INDEX_NAME)

    @property
    def backup_path(self):
        return os.path.join(self.output_dir, BACKUP_NAME)

    @property
    def tmp_path(self):
        return os.path.join(self.output_dir, TMP_NAME)

    # ---------- 加载 / 自愈 ----------

    @classmethod
    def load(cls, output_dir):
        """加载索引；损坏时依次尝试 ``.bak``，均失败则返回空索引（不阻断浏览）。

        返回 ``(AlbumIndex, status)``，status ∈ ok / recovered / broken / blocked。
        """
        idx = cls(output_dir)
        path = idx.index_path
        if not os.path.exists(path):
            return idx, "ok"

        data, err = _read_json(path)
        if data is not None:
            status = idx._adopt(data)
            return idx, status

        # 主文件损坏 → 尝试 .bak
        if os.path.exists(idx.backup_path):
            bdata, berr = _read_json(idx.backup_path)
            if bdata is not None:
                idx._adopt(bdata)
                idx.recovered = True
                # 立即用恢复内容重写主文件（04 号 §6.2）
                try:
                    idx.save()
                except Exception:
                    pass
                return idx, "recovered"
        return idx, "broken"

    def _adopt(self, data):
        """把读到的 dict 收编为内部结构；返回状态 ok / blocked。"""
        if not isinstance(data, dict):
            return "broken"
        schema = data.get("schema")
        if schema != SCHEMA:
            # 未知版本 → 拒绝写入、保留原文件（04 号 §6.2）
            self.write_blocked = True
            self.data["albums"] = []
            self.data["assignments"] = {}
            return "blocked"
        self.data = {
            "schema": SCHEMA,
            "updated_at": data.get("updated_at", ""),
            "source_root": data.get("source_root", ""),
            "albums": [a for a in data.get("albums", []) if isinstance(a, dict)],
            "assignments": dict(data.get("assignments", {}) or {}),
            "orphans": list(data.get("orphans", []) or []),
        }
        return "ok"

    # ---------- 落盘（原子） ----------

    def save(self):
        """原子写：tmp → fsync → 备份旧件 → os.replace。

        任何一步失败都**保留原文件不变**并抛异常（04 号 §6.1）。
        """
        if self.write_blocked:
            raise RuntimeError("blocked_schema")
        self.data["schema"] = SCHEMA
        self.data["updated_at"] = _now_iso()
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)

        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.tmp_path, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        try:
            if os.path.exists(self.index_path):
                shutil.copy2(self.index_path, self.backup_path)
            os.replace(self.tmp_path, self.index_path)
        except Exception:
            try:
                if os.path.exists(self.tmp_path):
                    os.remove(self.tmp_path)
            except OSError:
                pass
            raise
        self.dirty = False

    # ---------- 相册 CRUD ----------

    def albums(self, kind=None):
        items = self.data["albums"]
        if kind:
            items = [a for a in items if a.get("kind") == kind]
        return items

    def get_album(self, album_id):
        for a in self.data["albums"]:
            if a.get("id") == album_id:
                return a
        return None

    def find_manual_by_name(self, name):
        for a in self.data["albums"]:
            if a.get("kind") == "manual" and a.get("name") == name:
                return a
        return None

    def _new_id(self, kind):
        prefix = PREFIX_DIR if kind == "dir" else PREFIX_MAN
        used = set(a.get("id") for a in self.data["albums"])
        seq = 1
        while True:
            cand = "%s_%s_%04d" % (prefix, _date_stamp(), seq)
            if cand not in used:
                return cand
            seq += 1

    def ensure_dir_albums(self, names):
        """为目录相册确保存在（04 号 A-4：首次发现时自动创建，已存在则复用）。

        返回 ``{目录名: album_id}``。
        """
        mapping = {}
        for raw in names:
            name = truncate_album_name(str(raw))
            found = None
            for a in self.data["albums"]:
                if a.get("kind") == "dir" and a.get("name") == name:
                    found = a
                    break
            if found is None:
                found = {
                    "id": self._new_id("dir"),
                    "name": name,
                    "kind": "dir",
                    "source_path": str(raw),
                    "created_at": _now_iso(),
                    "note": "",
                }
                self.data["albums"].append(found)
                self.dirty = True
            mapping[raw] = found["id"]
        return mapping

    def create_album(self, name):
        """新建手动相册。名称非法或重名时抛出 ``ValueError``（由 API 转成文案）。"""
        name = (name or "").strip()
        if not is_valid_album_name(name):
            raise ValueError("invalid_name")
        if self.find_manual_by_name(name):
            raise ValueError("duplicate_name")
        album = {
            "id": self._new_id("manual"),
            "name": name,
            "kind": "manual",
            "created_at": _now_iso(),
            "note": "",
        }
        self.data["albums"].append(album)
        self.dirty = True
        return album

    def rename_album(self, album_id, new_name):
        """重命名相册（手动/目录均可）。"""
        new_name = (new_name or "").strip()
        if not is_valid_album_name(new_name):
            raise ValueError("invalid_name")
        album = self.get_album(album_id)
        if album is None:
            raise ValueError("not_found")
        if album.get("kind") == "manual":
            other = self.find_manual_by_name(new_name)
            if other is not None and other.get("id") != album_id:
                raise ValueError("duplicate_name")
        album["name"] = new_name
        self.dirty = True
        return album

    def delete_album(self, album_id):
        """删除相册（**仅删相册，不删照片**）；成员回落为未分类。"""
        album = self.get_album(album_id)
        if album is None:
            raise ValueError("not_found")
        self.data["albums"] = [a for a in self.data["albums"] if a.get("id") != album_id]
        for key in list(self.data["assignments"].keys()):
            lst = self.data["assignments"].get(key) or []
            lst = [x for x in lst if x != album_id]
            self.data["assignments"][key] = lst
        self.dirty = True
        return True

    # ---------- 归类 ----------

    def assign(self, keys, album_ids):
        """把照片归入相册（幂等：重复归类不产生重复记录）。"""
        changed = 0
        for key in keys:
            cur = list(self.data["assignments"].get(key) or [])
            for aid in album_ids:
                if aid not in cur:
                    cur.append(aid)
                    changed += 1
            self.data["assignments"][key] = cur
        if changed:
            self.dirty = True
        return changed

    def unassign(self, keys, album_ids):
        """移出相册（保留空数组痕迹，避免复活）。"""
        changed = 0
        for key in keys:
            cur = list(self.data["assignments"].get(key) or [])
            for aid in album_ids:
                if aid in cur:
                    cur.remove(aid)
                    changed += 1
            self.data["assignments"][key] = cur
        if changed:
            self.dirty = True
        return changed

    def manual_albums_of(self, key):
        """某照片归属的手动相册 id 列表（只保留索引中仍存在的相册）。"""
        ids = self.data["assignments"].get(key) or []
        alive = set(a.get("id") for a in self.data["albums"])
        return [x for x in ids if x in alive]

    # ---------- 重建 ----------

    def rebuild_dir_albums(self, dir_names):
        """从目录结构重建：保留全部手动相册与 assignments，只重建目录相册集合。"""
        keep = [a for a in self.data["albums"] if a.get("kind") == "manual"]
        self.data["albums"] = keep
        self.ensure_dir_albums(dir_names)
        self.dirty = True

    def set_source_root(self, path):
        if self.data.get("source_root") != path:
            self.data["source_root"] = path
            self.dirty = True

    def orphan_keys(self, alive_keys):
        """把已不存在的照片键移入 orphans（保留不删，UI 不展示）。"""
        orphans = set(self.data.get("orphans") or [])
        for key in list(self.data["assignments"].keys()):
            if key not in alive_keys:
                orphans.add(key)
        self.data["orphans"] = sorted(orphans)


def _read_json(path):
    """读 JSON；成功返回 (data, None)，失败返回 (None, err)。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:
        return None, str(e)
