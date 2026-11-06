# -*- coding: utf-8 -*-
"""实况照片备份查看器 V1.3 · 相册页桥接 API

职责：把 WebView2 前端的调用转发到 Python 侧，实现 8 态状态机、相册 CRUD、
媒体轨判定与导出；**所有写操作经 Python 侧校验后落盘**，前端不得直接碰文件系统。

设计依据：``V1.3设计\\03_V1.3_客户端浏览页布局与组件.md`` §六 桥接 API。

API 清单 = 设计 14 个方法 + **必要增补 7 个**（增补理由见 ``__init__`` 注释，
须在实施报告中登记）：
    - ``prepare_media``：05 号 §2.2 判定流程要求"T1 失败 → 现场转码 T2"，
      必须有一个触发入口，否则兜底链路无法运行；
    - ``get_thumb``：封面按需生成（逐张 ffmpeg 抽帧代价高），配合前端懒加载；
    - ``pick_source_folder`` / ``create_album_prompt`` / ``rebuild_index`` /
      ``continue_without_index`` / ``open_external`` / ``show_wizard``：
      对应 07 号文案中的入口按钮落点。

红线约束：
    - 任何方法**不抛异常**，异常一律转成 ``{ok:false, error:...}``（前端不崩溃）；
    - 耗时操作走**后台线程**，不阻塞 UI；
    - 扫描为**只读**，写入仅落输出目录；
    - 路径不存在/无权限**如实返回明确 error**，不得沿用旧结果冒充新结果。

本模块为 V1.3 新增代码，不属于 V1.2 的 12 个受保护函数。
"""

import os
import threading
import time
import urllib.parse

import album_index
import album_media
import album_scan

STATE_A1 = "A1"   # 未设置源目录
STATE_A2 = "A2"   # 扫描中
STATE_A3 = "A3"   # 建索引中
STATE_A4 = "A4"   # 就绪
STATE_A5 = "A5"   # 索引为空（无可识别实况）
STATE_A6 = "A6"   # 索引异常
STATE_A7 = "A7"   # 转码中
STATE_A8 = "A8"   # WebView2 不可用

ERR_NOT_FOUND = "not_found"
ERR_NO_ACCESS = "no_access"
ERR_INVALID = "invalid_name"
ERR_DUPLICATE = "duplicate_name"


def to_file_url(path):
    """本地绝对路径 → ``file:///`` URL（兼容中文与空格）。"""
    p = os.path.abspath(str(path)).replace("\\", "/")
    return "file:///" + urllib.parse.quote(p, safe="/:")


class AlbumApi(object):
    """相册页的 Python 侧实现。

    ``host`` 需提供（由 Tk 侧实现）：
        get_source() / set_source_display(path) / pick_folder() / get_output_dir() /
        push_state(state) / push_status(status) / open_external(url) / show_wizard() /
        on_scan_progress(done, total)
    """

    def __init__(self, host):
        self.host = host
        self.lock = threading.RLock()
        self.state = STATE_A1
        self.source = ""
        self.items = []            # album_scan.LivePhotoItem 列表
        self.by_key = {}
        self.index = None          # album_index.AlbumIndex
        self.index_status = "ok"   # ok / recovered / broken / blocked
        self.dir_albums = []       # 目录相册名（发现顺序）
        self._cancel = False
        self._scanning = False
        self._busy = False
        self.issues = {}             # 配对/格式异常分类计数（来自 scan_source）
        self._probe_cache = {}       # (path, mtime_ns, size) → 只读探测结果

    # ================= 内部工具 =================

    def _err(self, code, detail=""):
        return {"ok": False, "error": code, "detail": detail}

    def _ok(self, **kw):
        d = {"ok": True}
        d.update(kw)
        return d

    def _output_dir(self):
        try:
            return self.host.get_output_dir()
        except Exception:
            return ""

    def _push_state(self, **extra):
        st = {
            "kind": "state",
            "state": self.state,
            "source": self.source,
            "total": len(self.items),
            "index_ok": self.index_status in ("ok", "recovered"),
            "albums": self._albums_payload(),
            "issues": dict(self.issues),
        }
        st.update(extra)
        try:
            self.host.push_state(st)
        except Exception:
            pass

    def _albums_payload(self):
        """分类栏数据：视图 + 目录相册 + 手动相册（各带计数）。"""
        out = []
        manual_ids = set()
        if self.index is not None:
            for a in self.index.albums():
                if a.get("kind") == "manual":
                    manual_ids.add(a.get("id"))
        # 目录相册：按第一层目录名统计
        dir_count = {}
        for it in self.items:
            if it.dir_album:
                dir_count[it.dir_album] = dir_count.get(it.dir_album, 0) + 1
        if self.index is not None:
            for a in self.index.albums():
                if a.get("kind") != "dir":
                    continue
                src = a.get("source_path") or a.get("name")
                out.append({"id": a.get("id"), "name": a.get("name"), "kind": "dir",
                            "count": dir_count.get(src, 0), "path": src})
        else:
            for name in self.dir_albums:
                out.append({"id": "dir:" + name, "name": name, "kind": "dir",
                            "count": dir_count.get(name, 0), "path": name})
        if self.index is not None:
            for a in self.index.albums():
                if a.get("kind") != "manual":
                    continue
                cnt = 0
                for it in self.items:
                    if a.get("id") in self.index.manual_albums_of(it.key):
                        cnt += 1
                out.append({"id": a.get("id"), "name": a.get("name"), "kind": "manual",
                            "count": cnt})
        return out

    def _photo_albums(self, it):
        """一张照片的有效相册（目录相册 + 手动相册，叠加）。"""
        res = []
        if self.index is not None:
            for a in self.index.albums():
                if a.get("kind") == "dir" and (a.get("source_path") or a.get("name")) == it.dir_album:
                    res.append({"id": a.get("id"), "name": a.get("name"), "kind": "dir"})
        if self.index is not None:
            for aid in self.index.manual_albums_of(it.key):
                a = self.index.get_album(aid)
                if a:
                    res.append({"id": a.get("id"), "name": a.get("name"), "kind": "manual"})
        return res

    def _filter(self, album_id):
        if album_id in (None, "", "all"):
            return list(self.items)
        if album_id == "none":
            return [it for it in self.items if not self._photo_albums(it)]
        if self.index is not None:
            a = self.index.get_album(album_id)
            if a is not None and a.get("kind") == "manual":
                return [it for it in self.items
                        if album_id in self.index.manual_albums_of(it.key)]
        return [it for it in self.items if it.dir_album == album_id]

    # ================= 状态 =================

    def get_state(self):
        with self.lock:
            payload = {
                "kind": "state",
                "state": self.state,
                "source": self.source,
                "total": len(self.items),
                "index_ok": self.index_status in ("ok", "recovered"),
                "albums": self._albums_payload(),
                "issues": dict(self.issues),
            }
            # 不再一次性塞 500 条：统一由前端按 offset/limit 分页取数
            return self._ok(data=payload)

    def _item_payload(self, it):
        # 仅标记「文件存在」，不把存在等同于可读取/可播放。
        exists = os.path.isfile(it.video_path)
        return {
            "key": it.key,
            "name": it.name,
            "media": to_file_url(it.video_path),
            "thumb": "",
            "albums": self._photo_albums(it),
            "media_state": "exists" if exists else "missing",
        }

    # ================= 源目录 =================

    def sync_source_path(self, path):
        """**仅双向同步路径显示**，不触发扫描（复核裁定 P-1）。

        路径无效 → 明确 error，不沿用旧结果（V1.1 修订 R-8）。
        """
        path = str(path or "").strip()
        if not path:
            return self._err(ERR_NOT_FOUND)
        if not os.path.isdir(path):
            return self._err(ERR_NOT_FOUND, path)
        if not os.access(path, os.R_OK):
            return self._err(ERR_NO_ACCESS, path)
        changed = (path != self.source)
        self.source = path
        if changed:
            try:
                self.host.set_source_display(path)
            except Exception:
                pass
        self._push_state()
        return self._ok(synced=True, source=path)

    def set_source(self, path):
        """**显式扫描动作**（A1 空态按钮 / 「刷新」）：校验 → 扫描 → 建索引。"""
        path = str(path or "").strip()
        if not path or not os.path.isdir(path):
            return self._err(ERR_NOT_FOUND, path)
        if not os.access(path, os.R_OK):
            return self._err(ERR_NO_ACCESS, path)
        changed = (path != self.source)
        self.source = path
        if changed:
            try:
                self.host.set_source_display(path)
            except Exception:
                pass
        self._start_scan(path)
        return self._ok(total=len(self.items), state=self.state)

    def refresh(self):
        if not self.source:
            return self._err(ERR_NOT_FOUND)
        if not os.path.isdir(self.source):
            return self._err(ERR_NOT_FOUND, self.source)
        self._start_scan(self.source)
        return self._ok(state=self.state)

    def pick_source_folder(self):
        """打开系统目录选择框（由 Tk 线程执行）。"""
        try:
            path = self.host.pick_folder()
        except Exception as e:
            return self._err("pick_failed", str(e))
        if not path:
            return self._ok(cancelled=True)
        return self.set_source(path)

    def cancel_scan(self):
        self._cancel = True
        return self._ok()

    def _start_scan(self, path):
        if self._scanning:
            return
        self._scanning = True
        self._cancel = False
        self.state = STATE_A2
        self._push_state()
        th = threading.Thread(target=self._scan_worker, args=(path,), daemon=True)
        th.start()

    def _scan_worker(self, path):
        try:
            issues = {}
            items, dir_albums, cancelled = album_scan.scan_source(
                path, should_cancel=lambda: self._cancel, issues=issues)
            if cancelled:
                # A2 取消后的去向：有有效索引 → A4（沿用旧数据 + 明确提示）；否则 A1
                self.state = STATE_A4 if self.index is not None else STATE_A1
                self._push_state(status={"main": album_page_copy("st_cancelled"),
                                         "extra": "", "cls": "warn"})
                return
            self.items = items
            self.by_key = {it.key: it for it in items}
            self.dir_albums = dir_albums
            self.issues = issues
            self._probe_cache.clear()

            if not items:
                self.state = STATE_A5
                self._push_state()
                return

            self.state = STATE_A3
            self._push_state()
            out = self._output_dir()
            idx, status = album_index.AlbumIndex.load(out) if out else (None, "ok")
            if idx is None:
                idx = album_index.AlbumIndex(out or os.getcwd())
            self.index = idx
            self.index_status = status
            if status == "blocked":
                # 未知 schema：只读浏览，分类写操作禁用（04 号 §6.2）
                self.index = None
            else:
                idx.set_source_root(path)
                idx.ensure_dir_albums(dir_albums)
                alive = set(it.key for it in items)
                idx.orphan_keys(alive)
                try:
                    idx.save()
                except Exception:
                    pass
            self.state = STATE_A4
            self._push_state(force_reload=True)
        except Exception as e:
            self.state = STATE_A1 if self.index is None else STATE_A4
            self._push_state(status={"main": str(e), "extra": "", "cls": "warn"})
        finally:
            self._scanning = False

    # ================= 相册 =================

    def list_albums(self):
        with self.lock:
            return self._ok(albums=self._albums_payload())

    def list_photos(self, album_id="all", offset=0, limit=200, sort="time"):
        try:
            offset = max(0, int(offset))
            limit = max(1, min(1000, int(limit)))
        except Exception:
            offset, limit = 0, 200
        with self.lock:
            subset = self._filter(album_id)
            page = subset[offset:offset + limit]
            items = [self._item_payload(it) for it in page]
            return self._ok(total=len(subset), items=items,
                            issues=dict(self.issues))

    def create_album(self, name):
        if self.index is None:
            return self._err("index_unavailable")
        try:
            album = self.index.create_album(name)
        except ValueError as e:
            code = str(e)
            return self._err(ERR_DUPLICATE if code == "duplicate_name" else ERR_INVALID)
        try:
            self.index.save()
        except Exception as e:
            return self._err("save_failed", str(e))
        self._push_state()
        return self._ok(album={"id": album["id"], "name": album["name"],
                                "kind": album["kind"], "count": 0})

    def create_album_prompt(self):
        """由 Tk 侧弹出输入框后调用 create_album。"""
        try:
            name = self.host.prompt_album_name()
        except Exception:
            name = None
        if not name:
            return self._ok(cancelled=True)
        return self.create_album(name)

    def rename_album(self, album_id, name):
        if self.index is None:
            return self._err("index_unavailable")
        try:
            album = self.index.rename_album(album_id, name)
        except ValueError as e:
            code = str(e)
            return self._err(ERR_DUPLICATE if code == "duplicate_name" else ERR_INVALID)
        try:
            self.index.save()
        except Exception as e:
            return self._err("save_failed", str(e))
        self._push_state()
        return self._ok(album={"id": album["id"], "name": album["name"]})

    def delete_album(self, album_id):
        if self.index is None:
            return self._err("index_unavailable")
        try:
            self.index.delete_album(album_id)
        except ValueError:
            return self._err(ERR_NOT_FOUND)
        try:
            self.index.save()
        except Exception as e:
            return self._err("save_failed", str(e))
        self._push_state()
        return self._ok()

    def assign(self, photo_keys, album_ids):
        if self.index is None:
            return self._err("index_unavailable")
        try:
            changed = self.index.assign(list(photo_keys or []), list(album_ids or []))
            self.index.save()
        except Exception as e:
            return self._err("save_failed", str(e))
        self._push_state()
        return self._ok(changed=changed)

    def unassign(self, photo_keys, album_ids):
        if self.index is None:
            return self._err("index_unavailable")
        try:
            changed = self.index.unassign(list(photo_keys or []), list(album_ids or []))
            self.index.save()
        except Exception as e:
            return self._err("save_failed", str(e))
        self._push_state()
        return self._ok(changed=changed)

    def rebuild_index(self):
        """从目录结构重建：保留手动相册与 assignments（04 号 §6.3）。"""
        if self.index is None:
            return self._err("index_unavailable")
        try:
            self.index.rebuild_dir_albums(self.dir_albums)
            self.index.save()
        except Exception as e:
            return self._err("save_failed", str(e))
        self.index_status = "ok"
        self._push_state()
        return self._ok()

    def continue_without_index(self):
        """忽略损坏索引，继续只读浏览（A6 的降级出口）。"""
        self.index = None
        self.index_status = "broken"
        self.state = STATE_A4
        self._push_state()
        return self._ok()

    # ================= 媒体 =================

    def get_thumb(self, key):
        """按需生成/返回封面（懒加载）。"""
        it = self.by_key.get(key)
        if it is None:
            return self._err(ERR_NOT_FOUND)
        out = self._output_dir()
        try:
            p = album_media.ensure_cover(out, it.video_path,
                                         root=self.source, name=it.name)
        except Exception:
            p = None
        return self._ok(thumb=to_file_url(p) if p else "")

    def _probe(self, it):
        """按需只读探测视频（按 path+mtime+size 缓存），不触碰源文件。"""
        try:
            st = os.stat(it.video_path)
            ck = (it.video_path, st.st_mtime_ns, st.st_size)
        except OSError:
            ck = (it.video_path, 0, 0)
        hit = self._probe_cache.get(ck)
        if hit is not None:
            return dict(hit)
        res = album_media.probe_video(it.video_path)
        self._probe_cache[ck] = dict(res)
        return res

    def get_photo_detail(self, key):
        it = self.by_key.get(key)
        if it is None:
            return self._err(ERR_NOT_FOUND)
        out = self._output_dir()
        tracks = {"video": to_file_url(it.video_path), "transcode": None, "gif": None}
        try:
            mp4 = album_media.ensure_transcoded(out, it.video_path, root=self.source)
            tracks["transcode"] = to_file_url(mp4)
        except Exception:
            pass
        # 三层状态：文件存在（exists）→ 可读可解帧（probe）→ 实际可播放
        # （playable，仅由浏览器 <video> 的 playing 事件确认，Python 侧不保证）。
        return self._ok(key=key, tracks=tracks, probe=self._probe(it),
                        playable=None)

    def prepare_media(self, key):
        """T1 失败时的兜底触发：先分类异常，再 T2 转码，最后才是 GIF 展示。

        返回 ``{"track": "transcode"|"gif", "url": str}`` 或明确 error code：
        ``video_missing / video_unreadable / decode_failed / transcode_failed``。
        GIF 只是明确标注的降级展示，前端不将其计入实况视频播放成功。
        """
        it = self.by_key.get(key)
        if it is None:
            return self._err(ERR_NOT_FOUND, "这张照片已不在扫描结果里")
        out = self._output_dir()
        self.state = STATE_A7
        try:
            self.host.push_status({"main": album_page_copy("v15_title"),
                                   "extra": album_page_copy("v15_tip"), "cls": "info"})
        except Exception:
            pass
        detail = "no_media_track"
        try:
            if not os.path.isfile(it.video_path):
                return self._err("video_missing", "找不到对应的视频文件")
            probe = self._probe(it)
            if not probe.get("readable"):
                return self._err("video_unreadable", probe.get("detail", ""))
            if not probe.get("decodable"):
                return self._err("decode_failed", probe.get("detail", ""))
            try:
                mp4 = album_media.ensure_transcoded(
                    out, it.video_path, root=self.source)
                return self._ok(track="transcode", url=to_file_url(mp4))
            except Exception as e:
                detail = str(e)
        finally:
            self.state = STATE_A4
        gif = None
        try:
            cand = os.path.join(out, "GIF动图", it.name + ".gif")
            if os.path.exists(cand):
                gif = cand
        except Exception:
            gif = None
        if gif:
            return self._ok(track="gif", url=to_file_url(gif))
        return self._err("transcode_failed", detail)

    def export_mp4(self, photo_keys=None):
        """导出安卓友好 MP4（批量前做粗空间预检，05 号 §六 / R-9）。"""
        out = self._output_dir()
        if not out:
            return self._err("no_output_dir")
        items = self.items
        if photo_keys:
            want = set(photo_keys)
            items = [it for it in self.items if it.key in want]
        if not items:
            return self._ok(files=[], dir="")
        need = album_media.estimate_export_size(items)
        space = album_media.rough_space_check(album_media.export_dir(out), need)
        if space["state"] == "insufficient":
            return self._err("insufficient_space",
                             "空间可能不够（需要约 %.1f MB，可用 %.1f MB）"
                             % (need / 1048576.0, space["free"] / 1048576.0))
        if space["state"] == "unknown":
            return self._err("space_unknown", "未完成空间检查")
        try:
            res = album_media.export_mp4(items, out)
        except Exception as e:
            return self._err("export_failed", str(e))
        return self._ok(files=res["files"], skipped=res["skipped"],
                        dir=res["dir"], cancelled=res["cancelled"])

    def open_in_explorer(self, key):
        it = self.by_key.get(key)
        if it is None:
            return self._err(ERR_NOT_FOUND)
        try:
            self.host.open_external(it.photo_path)
        except Exception as e:
            return self._err("open_failed", str(e))
        return self._ok()

    def open_external(self):
        """V-18 降级：用系统浏览器打开相册页。"""
        try:
            self.host.open_external(None)
        except Exception:
            return self._err("open_failed")
        return self._ok()

    def show_wizard(self):
        try:
            self.host.show_wizard()
        except Exception:
            return self._err("wizard_failed")
        return self._ok()


def album_page_copy(key):
    """取相册页文案（延迟导入，避免模块级循环依赖）。"""
    try:
        import album_page
        return album_page.COPY.get(key, "")
    except Exception:
        return ""
