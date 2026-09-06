# -*- coding: utf-8 -*-
"""多用户并行的 OCC 任务池 —— 用进程隔离替代全局串行锁

背景
----
pythonOCC 的全局状态(句柄表 / 内存池 / 异常栈)非线程安全。旧实现在 Flask
主进程里用一个全局 threading.Lock 把所有装配、出图请求串行化,后果是:

  * 单次装配要 10~20s,第二个用户只能干等,页面像卡死;
  * 任一请求在 OCC 内部崩溃,可能污染同进程后续请求的状态;
  * 主进程跑 OCC 时,连静态资源请求都要排队。

方案
----
把 OCC 任务放进 ProcessPoolExecutor 的子进程执行:

  * 进程级隔离天然规避线程安全问题,各任务互不干扰;
  * N 个 worker 并行,多用户的请求真正同时推进;
  * Flask 主线程只负责提交与轮询,不再被单个用户阻塞;
  * 子进程崩了只丢这一个任务,主进程和其它任务不受影响。

任务日志由子进程写入 logs/tasks/<task_id>.log,主进程轮询时回传尾部,
于是每个用户在页面上只看得到自己那一条的实时进度。

两种用法
--------
submit()  异步,返回 task_id,配合 /api/task/<id> 轮询(装配构建用)
run()     同步,提交后阻塞取结果(出图接口用,等价替换原 `with _build_lock:`)

任务状态: pending(排队) → running(子进程执行中) → done / error
去重:     key 相同的任务在未结束前不会重复排队,后来者复用同一 task_id。
          这样多个用户点同一型号时只算一次,避免并发写同一个 output 目录。

环境变量
--------
BUILD_POOL_WORKERS  并行 worker 数,默认 min(4, CPU 核数)
OCC_POOL_INLINE=1   任务改在主进程线程内执行,便于 IDE 下断点与单测打桩;
                    代价是失去进程隔离、不保证 OCC 线程安全,禁止生产开启
"""
import json
import os
import sys
import time
import threading
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

# 本文件位于 src/web/,需把 src 加入 sys.path 才能导入 core/drawing/batch 包
_HERE = os.path.dirname(os.path.abspath(__file__))          # src/web
_SRC_DIR = os.path.dirname(_HERE)                           # src
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from core import paths
from core import rebuild_assembly as rb

TASK_LOG_DIR = os.path.join(paths.LOG_DIR, "tasks")


# ===================== 子进程侧:任务分派 =====================

def _run_build(p):
    """装配构建(STEP/GLB 导出)"""
    return rb.build_assembly(p["model_code"], motor=p.get("motor"),
                             series=p.get("series"))


def _run_drawing_views(p):
    from core import drawing_engine
    return drawing_engine.generate_drawing_views_fast(p["step_path"])


def _run_drawing_views_raw(p):
    from core import drawing_engine
    return drawing_engine.generate_drawing_views_raw(p["step_path"])


def _run_drawing_pdf(p):
    from drawing import drawing_generator
    return drawing_generator.generate_drawing_pdf(
        p["step_path"], p["output_pdf"], p["params"])


def _run_drawing_dxf(p):
    from drawing import dxf_exporter
    return dxf_exporter.generate_dxf_from_step(
        p["step_path"], p["output_dxf"], params=p["params"])


def _run_view_palette(p):
    from core import drawing_engine
    # 调色板要一次投影全部 9+3 个视图,串行太慢。内部并行 worker 数
    # 按视图数自动(min(9, 视图数, CPU)):视图多 worker 就多,与
    # generate_all_standard_views 的自动逻辑一致
    return drawing_engine.generate_all_standard_views(
        p["shape_path"], view_names=p.get("view_names"),
        parallel=True)


def _run_view_single(p):
    from core import drawing_engine
    return drawing_engine.generate_view_by_name(
        p["shape_path"], p["view_name"])


def _run_template_base(p):
    """算基准数据(整批一次),结果 JSON 化后供各型号任务复用"""
    from batch import batch_drawing as bd
    return bd.prepare_base(p["template_doc"], p["out_dir"])


def _run_template_one(p):
    """单个型号出图:与同批其它型号在不同 worker 上并行"""
    from batch import batch_drawing as bd
    base = p["base"]
    return bd.generate_one_frontend(p["model_code"], p["template_doc"],
                                    base["views"], base["refs"],
                                    base["profile"], p["out_dir"],
                                    base["view_names"])


# 注册表:value 必须是模块级函数(子进程按引用反序列化)
_KINDS = {
    "build": _run_build,
    "drawing-views": _run_drawing_views,
    "drawing-views-raw": _run_drawing_views_raw,
    "drawing-pdf": _run_drawing_pdf,
    "drawing-dxf": _run_drawing_dxf,
    "view-palette": _run_view_palette,
    "view-single": _run_view_single,
    "template-base": _run_template_base,
    "template-one": _run_template_one,
}


def _worker(kind, log_path, payload):
    """子进程入口:接管日志 → 执行任务 → 返回 JSON 串

    结果先序列化成 JSON 字符串再跨进程返回,避免把 numpy / OCC 对象
    带进 pickle 链路(那些对象跨进程后不可用,早失败早报错)。
    """
    def _log(msg, _p=log_path):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        try:
            with open(_p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # build_assembly 内部通过模块全局 log() 输出,替换即接管全部进度
    rb.log = _log
    _log("任务启动 (pid=%d, kind=%s)" % (os.getpid(), kind))
    t0 = time.time()
    try:
        result = _KINDS[kind](payload)
        _log("任务完成,耗时 %.2fs" % (time.time() - t0))
        return {"ok": True,
                "json": json.dumps(result, ensure_ascii=False, default=str)}
    except Exception as e:
        _log("任务失败: %s: %s" % (type(e).__name__, e))
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                "traceback": traceback.format_exc()}


# ===================== 主进程侧:任务池 =====================

class TaskError(RuntimeError):
    """子进程任务失败(携带子进程 traceback,便于定位)"""

    def __init__(self, message, traceback_text=None):
        super().__init__(message)
        self.traceback_text = traceback_text


def _default_workers():
    """默认并行度:环境变量 BUILD_POOL_WORKERS 优先,否则取 min(4, CPU 核数)

    OCC 任务内存占用大,worker 数不宜盲目跟核数走。
    """
    env = os.environ.get("BUILD_POOL_WORKERS", "").strip()
    if env.isdigit():
        return max(1, int(env))
    return max(1, min(4, os.cpu_count() or 1))


def _env_inline():
    """OCC_POOL_INLINE=1 时在主进程线程内跑任务(调试/打桩用)

    走线程而非子进程,于是可以在 IDE 里下断点、也能被 monkeypatch 打桩。
    代价是失去进程隔离,不保证 OCC 线程安全 —— 仅限调试与测试,禁止生产开启。
    """
    return os.environ.get("OCC_POOL_INLINE", "").strip() in ("1", "true", "yes")


def _tail(path, n):
    """读取日志文件尾部 n 行(子进程边跑边写,主进程轮询时取最新片段)"""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    return [ln.rstrip("\r\n") for ln in lines[-n:]]


class TaskPool:
    """OCC 任务池:提交 / 轮询 / 同步等待 / 去重 / 过期回收"""

    def __init__(self, max_workers=None, ttl=1800.0, inline=None):
        self.max_workers = max_workers or _default_workers()
        self.ttl = ttl                      # 终态任务保留时长(秒)
        # inline=True 时任务在主进程线程内执行(调试/测试),否则走子进程
        self.inline = _env_inline() if inline is None else inline
        self._lock = threading.Lock()
        self._pool_lock = threading.Lock()
        self._executor = None
        self._inline_executor = None
        self._tasks = {}                    # task_id -> task dict
        self._by_key = {}                   # "kind:key" -> task_id
        self._seq = 0
        os.makedirs(TASK_LOG_DIR, exist_ok=True)

    # ---------- 执行器(懒创建) ----------
    def _ensure_executor(self):
        """首次提交时才建池

        必须懒创建:Windows 用 spawn,子进程会重新导入主模块(server.py);
        若在模块顶层建池,每个子进程都会再建一个池,无限派生。
        """
        if self.inline:
            if self._inline_executor is None:
                with self._pool_lock:
                    if self._inline_executor is None:
                        self._inline_executor = ThreadPoolExecutor(
                            max_workers=self.max_workers,
                            thread_name_prefix="occ-inline")
            return self._inline_executor
        if self._executor is None:
            with self._pool_lock:
                if self._executor is None:
                    self._executor = ProcessPoolExecutor(
                        max_workers=self.max_workers)
        return self._executor

    # ---------- 提交 ----------
    def submit(self, kind, key, payload, client=None):
        """提交任务,返回 (task_id, dedup)

        dedup=True 表示复用了同 key 的未完成任务,没有真正排队。
        """
        if kind not in _KINDS:
            raise ValueError("未知任务类型: %s,可选: %s"
                             % (kind, sorted(_KINDS)))
        dedup_key = "%s:%s" % (kind, key)
        with self._lock:
            self._gc_locked()
            hit = self._by_key.get(dedup_key)
            if hit is not None:
                return hit, True
            self._seq += 1
            task_id = "%s-%04d" % (kind, self._seq)
            task = {
                "task_id": task_id,
                "kind": kind,
                "key": key,
                "client": client,
                "status": "pending",
                "result": None,
                "error": None,
                "traceback": None,
                "log_path": os.path.join(TASK_LOG_DIR, task_id + ".log"),
                "submitted_at": time.time(),
                "finished_at": None,
                "_dedup_key": dedup_key,
                "_fut": None,
            }
            self._tasks[task_id] = task
            self._by_key[dedup_key] = task_id

        # 在锁外提交:子进程可能瞬间完成,持锁时回调会等锁,徒增阻塞
        fut = self._ensure_executor().submit(_worker, kind,
                                             task["log_path"], payload)
        with self._lock:
            task["_fut"] = fut
        fut.add_done_callback(lambda f, _id=task_id: self._on_done(_id, f))
        return task_id, False

    def _on_done(self, task_id, fut):
        """任务结束回调(在进程池的管理线程执行)"""
        try:
            out = fut.result()
        except Exception as e:
            # 含 BrokenProcessPool(子进程被杀)等进程池级故障
            out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                   "traceback": traceback.format_exc()}
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                return
            t["finished_at"] = time.time()
            # 任务已终态,释放去重占位:后续同 key 请求可以重新排队
            self._by_key.pop(t["_dedup_key"], None)
            if out.get("ok"):
                t["status"] = "done"
                try:
                    t["result"] = json.loads(out["json"])
                except (TypeError, ValueError):
                    t["result"] = out.get("json")
            else:
                t["status"] = "error"
                t["error"] = out.get("error") or "子进程任务失败"
                t["traceback"] = out.get("traceback")

    # ---------- 同步等待 ----------
    def _future(self, task_id):
        """取任务对应的 Future(提交后 _fut 有一小段空窗期,需自旋等一下)"""
        while True:
            with self._lock:
                t = self._tasks.get(task_id)
                if t is None:
                    raise KeyError("任务不存在: %s" % task_id)
                fut = t.get("_fut")
            if fut is not None:
                return fut
            time.sleep(0.02)

    def wait(self, task_id, timeout=None, grace=5.0):
        """阻塞等待任务结束

        Returns:
            任务结果(dict / list / 任意 JSON 结构)
        Raises:
            TaskError     子进程内任务失败
            TimeoutError  超时
        """
        fut = self._future(task_id)
        try:
            fut.result(timeout=timeout)
        except FutureTimeout:
            raise TimeoutError("任务 %s 超时(%.0fs)" % (task_id, timeout or 0))
        except Exception:
            pass  # 失败详情已由 _on_done 落地到任务状态

        # fut.result() 返回与 done_callback 执行存在极小竞态,等状态落定
        deadline = time.time() + grace
        while time.time() < deadline:
            with self._lock:
                if self._tasks[task_id]["status"] in ("done", "error"):
                    break
            time.sleep(0.02)

        with self._lock:
            t = self._tasks[task_id]
            status, result = t["status"], t["result"]
            error, tb = t["error"], t["traceback"]
        if status == "done":
            return result
        if status == "error":
            raise TaskError(error, tb)
        raise TimeoutError("任务 %s 超时(%.0fs)" % (task_id, timeout or 0))

    def run(self, kind, key, payload, timeout=None):
        """同步执行(等价于旧写法 `with _build_lock: ...`)

        出图类接口直接替换即可:仍然阻塞当前请求,但 OCC 计算发生在
        独立子进程,多用户之间不再互相排队。
        """
        task_id, _ = self.submit(kind, key, payload)
        return self.wait(task_id, timeout=timeout)

    # ---------- 查询 ----------
    def status(self, task_id, log_lines=80):
        """任务快照(含日志尾部);任务不存在返回 None"""
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                return None
            fut = t.get("_fut")
            snap = {k: v for k, v in t.items() if not k.startswith("_")}
        if snap["status"] == "pending" and fut is not None and fut.running():
            snap["status"] = "running"
        snap["elapsed"] = round(
            (snap["finished_at"] or time.time()) - snap["submitted_at"], 2)
        snap["log"] = _tail(t["log_path"], log_lines)
        snap.pop("log_path", None)
        return snap

    def list_tasks(self, limit=50):
        """最近任务列表(多用户可看到彼此的排队情况)"""
        now = time.time()
        with self._lock:
            # 先按源 task 的 submitted_at 排序(精简后的 items 不带该字段,不能直接排)
            ordered = sorted(
                self._tasks.values(),
                key=lambda t: t.get("submitted_at", 0),
                reverse=True,
            )
            items = []
            for t in ordered:
                fut = t.get("_fut")
                status = t["status"]
                if status == "pending" and fut is not None and fut.running():
                    status = "running"
                items.append({
                    "task_id": t["task_id"],
                    "kind": t["kind"],
                    "key": t["key"],
                    "status": status,
                    "elapsed": round(
                        (t["finished_at"] or now) - t["submitted_at"], 2),
                })
        return items[:limit]

    def stats(self):
        """任务池总览:并行度与各状态计数"""
        st = {"workers": self.max_workers, "pending": 0, "running": 0,
              "done": 0, "error": 0}
        with self._lock:
            for t in self._tasks.values():
                fut = t.get("_fut")
                key = t["status"]
                if key == "pending" and fut is not None and fut.running():
                    key = "running"
                st[key] = st.get(key, 0) + 1
        st["total"] = st["pending"] + st["running"] + st["done"] + st["error"]
        return st

    def shutdown(self, wait=False):
        """回收执行器(服务退出时调用)"""
        with self._pool_lock:
            for name in ("_executor", "_inline_executor"):
                ex = getattr(self, name)
                if ex is not None:
                    ex.shutdown(wait=wait)
                    setattr(self, name, None)

    # ---------- 回收 ----------
    def _gc_locked(self):
        """清理过期终态任务(调用方需已持有 self._lock)"""
        now = time.time()
        for task_id, t in list(self._tasks.items()):
            if t["status"] in ("pending", "running"):
                continue
            if now - (t["finished_at"] or now) < self.ttl:
                continue
            self._tasks.pop(task_id, None)
            self._by_key.pop(t["_dedup_key"], None)
            try:
                os.remove(t["log_path"])
            except OSError:
                pass


# ===================== 进程内单例 =====================

_POOL = None
_POOL_LOCK = threading.Lock()


def get_pool():
    """获取全局任务池(懒创建,保证子进程不会重复建池)"""
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = TaskPool()
    return _POOL
