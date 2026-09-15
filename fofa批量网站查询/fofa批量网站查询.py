# -*- coding: utf-8 -*-
import os
import base64
import csv
import time
import re
import threading
import queue
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ----------------- 基础配置 -----------------
FIELDS = "host,ip,port,domain,title,country,protocol,server"
FINAL_CSV = "fofa_all_results.csv"
DONE_FILE = "done.txt"
RATE_LIMIT_KEYS = ("rate", "too fast", "too many", "限速", "速度太快", "频繁", "820003", "45012")
QUOTA_KEYS = ("balance", "quota", "permission", "insufficient", "overdue", "fpoint", "coin", "额度", "次数用完")

# ----------------------------------------------------------------------------
# 后台扫描引擎 (逻辑核心)
# ----------------------------------------------------------------------------
class FofaScanEngine:
    def __init__(self, config, log_queue, stop_event):
        self.cfg = config
        self.log_queue = log_queue
        self.stop_event = stop_event
        self.done_lock = Lock()
        self.file_lock = Lock()
        self.stats_lock = Lock()
        self.write_buffer_lock = Lock()
        self.api_exhausted = False
        self.done_set_mem = set()
        self.stats = {"total": 0, "skipped": 0, "empty": 0, "done": 0, "rows": 0}
        self._local = threading.local()
        self.rate_lock = Lock()
        self.rate_last = 0.0

    def fofa_get(self, url):
        """Serialize FOFA HTTP: one in-flight request, min interval between starts."""
        interval = max(0.2, float(self.cfg.get("request_interval") or 1.2))
        with self.rate_lock:
            now = time.time()
            wait = self.rate_last + interval - now
            if wait > 0:
                end = now + wait
                while time.time() < end:
                    if self.stop_event.is_set() or self.api_exhausted:
                        return None
                    time.sleep(min(0.2, max(0.0, end - time.time())))
            if self.stop_event.is_set() or self.api_exhausted:
                return None
            resp = self.get_session().get(url, timeout=25)
            self.rate_last = time.time()
            return resp

    def log(self, msg):
        self.log_queue.put(("log", msg))

    def report_progress(self, completed, total):
        self.log_queue.put(("progress", (completed, total)))

    def report_stats(self):
        with self.stats_lock:
            self.log_queue.put(("stats", dict(self.stats)))

    def get_session(self):
        if not hasattr(self._local, "session"):
            session = requests.Session()
            retry = Retry(total=self.cfg["max_retries"], backoff_factor=1, status_forcelist=[500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._local.session = session
        return self._local.session

    def fofa_query(self, q, task_id, page=1):
        """核心请求函数，包含 API 状态监控 + 完整错误打印"""
        if self.api_exhausted:
            return None
        q_base64 = base64.b64encode(q.encode()).decode()
        url = (
            f"https://fofa.info/api/v1/search/all?"
            f"email={self.cfg['email']}&key={self.cfg['key']}"
            f"&page={page}&size={self.cfg['page_size']}"
            f"&fields={FIELDS}"
            f"&qbase64={q_base64}"
        )

        for attempt in range(1, self.cfg["max_retries"] + 1):
            if self.stop_event.is_set() or self.api_exhausted:
                return None
            try:
                resp = self.fofa_get(url)
                if resp is None:
                    return None
                if resp.status_code == 429:
                    wait = 8.0 * attempt
                    self.log(f"[!] 任务 {task_id} 被限速 (429)，等待 {wait:.0f} 秒...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    errmsg = str(data.get("errmsg", "未知错误"))
                    lower_msg = errmsg.lower()
                    if any(k in lower_msg or k in errmsg for k in RATE_LIMIT_KEYS):
                        wait = 8.0 * attempt
                        self.log(f"[!] 任务 {task_id} FOFA 限速: {errmsg}，等待 {wait:.0f} 秒...")
                        time.sleep(wait)
                        continue
                    self.log(f"[!] API 返回错误 | 任务: {task_id}")
                    self.log(f"    查询语句: {q}")
                    self.log(f"    错误信息: {errmsg}")
                    if any(k in lower_msg or k in errmsg for k in QUOTA_KEYS):
                        self.log("\n" + "!" * 60)
                        self.log("[!!!] 停止：API 额度已用尽或账号权限不足！")
                        self.log(f"[!!!] 最后的扫描任务: {task_id}")
                        self.log(f"[!!!] 最后的查询语句: {q}")
                        self.log(f"[!!!] 官方错误原因: {errmsg}")
                        self.log("!" * 60 + "\n")
                        self.api_exhausted = True
                        self.stop_event.set()
                    return None
                return data
            except Exception as e:
                if attempt == self.cfg["max_retries"]:
                    self.log(f"[!] 任务 {task_id} 请求失败: {e}")
                    self.log(f"    查询语句: {q}")
                time.sleep(2 * attempt)
        return None

    def append_to_final_csv(self, rows):
        if not rows:
            return
        p = os.path.join(self.cfg["output_dir"], FINAL_CSV)
        with self.file_lock:
            exists = os.path.exists(p)
            with open(p, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                if not exists:
                    writer.writerow(FIELDS.split(","))
                writer.writerows(rows)
            with self.stats_lock:
                self.stats["rows"] += len(rows)

    def run_task(self, task):
        idx, total_tasks, query, task_id, sub_csv_path = task

        with self.done_lock:
            if task_id in self.done_set_mem:
                with self.stats_lock:
                    self.stats["skipped"] += 1
                return

        task_results = []
        page = 1
        while True:
            if self.stop_event.is_set() or self.api_exhausted:
                break

            data = self.fofa_query(query, task_id, page=page)
            if not data or not data.get("results"):
                break
            rows = data["results"]
            task_results.extend(rows)

            self.append_to_final_csv(rows)
            total_size = int(data.get("size", 0))
            if page == 1:
                self.log(f"[{idx}/{total_tasks}] {task_id} | 发现 {total_size} 条记录")
                self.log(f"    实际查询: {query}")
            else:
                self.log(f"  └─ {task_id} 翻页: 第 {page} 页")

            if len(task_results) >= total_size or len(rows) < self.cfg["page_size"]:
                break

            page += 1

        if task_results:
            with self.file_lock:
                with open(sub_csv_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(FIELDS.split(","))
                    writer.writerows(task_results)
            with self.stats_lock:
                self.stats["done"] += 1
        else:
            if not self.api_exhausted:
                with self.stats_lock:
                    self.stats["empty"] += 1
                self.log(f"[空结果] {task_id} | 查询: {query}")

        if not self.api_exhausted and not self.stop_event.is_set():
            p = os.path.join(self.cfg["output_dir"], DONE_FILE)
            with self.done_lock:
                self.done_set_mem.add(task_id)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(task_id + "\n")

    def run(self):
        os.makedirs(self.cfg["output_dir"], exist_ok=True)
        p = os.path.join(self.cfg["output_dir"], DONE_FILE)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                self.done_set_mem = set(line.strip() for line in f if line.strip())

        combos = list(product(self.cfg["keywords"], self.cfg["countries"], self.cfg["ports"], self.cfg["asns"]))
        tasks = []
        fixed = self.cfg.get("fixed_condition", "").strip()

        for idx, (kw, c, p, a) in enumerate(combos, 1):
            # 更贴近官网写法，去掉强制括号
            q_parts = [kw.strip()]

            if fixed:
                q_parts.append(fixed)

            if c:
                q_parts.append(f'country="{c}"')
            if p:
                q_parts.append(f'port="{p}"')
            if a:
                q_parts.append(f'asn="{a}"')

            query = " && ".join(q_parts)

            safe_kw = re.sub(r'[\\/:*?"<>|=]', "_", kw)[:30]
            tid = f"{c or 'ALL'}_{p or 'ALL'}_{a or 'ALL'}_{safe_kw}"
            sub_csv = os.path.join(self.cfg["output_dir"], f"{tid}.csv")
            tasks.append((idx, len(combos), query, tid, sub_csv))

        pending = [t for t in tasks if t[3] not in self.done_set_mem]
        self.log(f"[*] 任务准备就绪。总组合: {len(tasks)}，待扫描: {len(pending)}")
        self.log(f"[*] page_size={self.cfg['page_size']}  并发={self.cfg['max_workers']}  请求间隔={self.cfg['request_interval']}s")
        self.report_progress(0, max(1, len(pending)))

        with ThreadPoolExecutor(max_workers=self.cfg["max_workers"]) as executor:
            futures = {executor.submit(self.run_task, t): t[3] for t in pending}
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                self.report_progress(done_count, len(pending))
                self.report_stats()
                if self.api_exhausted:
                    break
        self.log(f"\n[✓] 流程结束。总计抓取数据: {self.stats['rows']} 条。")
        self.log_queue.put(("done", None))

# ----------------------------------------------------------------------------
# GUI 界面
# ----------------------------------------------------------------------------
class FofaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FOFA 批量扫描工具 (全量/断点版)")
        self.root.geometry("1100x820")
        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self._setup_ui()
        self._listen_queue()

    def _setup_ui(self):
        left = ttk.Frame(self.root)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        right = ttk.Frame(self.root)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 1. 账号
        f1 = ttk.LabelFrame(left, text="账号信息")
        f1.pack(fill=tk.X, pady=5)
        ttk.Label(f1, text="Email:").grid(row=0, column=0, padx=5, pady=5)
        self.email = ttk.Entry(f1, width=35)
        self.email.grid(row=0, column=1)
        ttk.Label(f1, text="Key:").grid(row=1, column=0, padx=5, pady=5)
        self.key = ttk.Entry(f1, width=35, show="*")
        self.key.grid(row=1, column=1)

        # 2. 目录
        f2 = ttk.LabelFrame(left, text="保存位置")
        f2.pack(fill=tk.X, pady=5)
        self.path = tk.StringVar(value=os.path.join(os.getcwd(), "fofa_output"))
        ttk.Entry(f2, textvariable=self.path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        ttk.Button(f2, text="选择", command=lambda: self.path.set(filedialog.askdirectory())).pack(side=tk.LEFT, padx=5)

        # 3. 组合参数
        f3 = ttk.LabelFrame(left, text="组合参数 (留空表示不限制)")
        f3.pack(fill=tk.BOTH, expand=True, pady=5)
        self.inputs = {}
        labels = ["关键词/域名", "国家", "端口", "ASN"]
        keys = ["KEYWORDS", "COUNTRIES", "PORTS", "ASNS"]
        for i, (name, key) in enumerate(zip(labels, keys)):
            frame = ttk.Frame(f3)
            frame.grid(row=i // 2, column=i % 2, sticky="nsew", padx=5, pady=5)
            ttk.Label(frame, text=name).pack(anchor="w")
            txt = tk.Text(frame, width=25, height=7)
            txt.pack(fill=tk.BOTH, expand=True)
            self.inputs[key] = txt
        f3.columnconfigure(0, weight=1)
        f3.columnconfigure(1, weight=1)

        # 4. 固定条件
        f3_5 = ttk.LabelFrame(left, text="固定条件（会自动加在每个关键词后面）")
        f3_5.pack(fill=tk.X, pady=5)
        self.fixed_condition = tk.Text(f3_5, height=2)
        self.fixed_condition.pack(fill=tk.X, padx=5, pady=5)
        self.fixed_condition.insert("1.0", 'icon_hash=="-2070047203"')

        # 5. 高级设置
        f4 = ttk.LabelFrame(left, text="高级设置")
        f4.pack(fill=tk.X, pady=5)
        ttk.Label(f4, text="每页数量(page_size):").grid(row=0, column=0, padx=5, pady=5)
        self.page_size_var = tk.StringVar(value="100")   # 默认改成 100，更安全
        ttk.Entry(f4, textvariable=self.page_size_var, width=10).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(f4, text="（建议 100；权限高可 1000）").grid(row=0, column=2, padx=5, sticky="w")
        ttk.Label(f4, text="并发线程:").grid(row=1, column=0, padx=5, pady=5)
        self.workers_var = tk.StringVar(value="1")
        ttk.Entry(f4, textvariable=self.workers_var, width=10).grid(row=1, column=1, padx=5, pady=5)
        ttk.Label(f4, text="建议 1，最多 3（线程仍共用一把限速锁）").grid(row=1, column=2, padx=5, sticky="w")
        ttk.Label(f4, text="请求间隔(秒):").grid(row=2, column=0, padx=5, pady=5)
        self.interval_var = tk.StringVar(value="1.2")
        ttk.Entry(f4, textvariable=self.interval_var, width=10).grid(row=2, column=1, padx=5, pady=5)
        ttk.Label(f4, text="任意两次 FOFA 请求的最小间隔，默认 1.2").grid(row=2, column=2, padx=5, sticky="w")

        # 6. 按钮
        self.btn_start = ttk.Button(left, text="开始扫描", command=self._start)
        self.btn_start.pack(side=tk.LEFT, padx=20, pady=10)
        self.btn_stop = ttk.Button(left, text="强行停止", command=lambda: self.stop_event.set(), state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, pady=10)

        # 右侧
        self.stat_info = ttk.Label(right, text="就绪", font=("", 10, "bold"))
        self.stat_info.pack(pady=5)
        self.progress = ttk.Progressbar(right, mode='determinate')
        self.progress.pack(fill=tk.X, padx=10, pady=5)
        self.log_box = tk.Text(right, bg="#1c1c1c", fg="#00e600", state=tk.DISABLED)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _start(self):
        def parse(name):
            val = self.inputs[name].get("1.0", "end").strip().splitlines()
            return [v.strip() for v in val if v.strip()] or [""]

        fixed = self.fixed_condition.get("1.0", "end").strip()

        try:
            page_size = int(self.page_size_var.get().strip())
            if page_size < 1 or page_size > 10000:
                raise ValueError
        except Exception:
            messagebox.showwarning("提示", "page_size 必须是 1~10000 的整数")
            return
        try:
            max_workers = int(self.workers_var.get().strip())
            if max_workers < 1 or max_workers > 3:
                raise ValueError
        except Exception:
            messagebox.showwarning("提示", "并发线程必须是 1~3 的整数")
            return
        try:
            request_interval = float(self.interval_var.get().strip())
            if request_interval < 0.2 or request_interval > 30:
                raise ValueError
        except Exception:
            messagebox.showwarning("提示", "请求间隔必须是 0.2~30 秒")
            return

        cfg = {
            "email": self.email.get().strip(),
            "key": self.key.get().strip(),
            "output_dir": self.path.get().strip(),
            "keywords": parse("KEYWORDS"),
            "countries": parse("COUNTRIES"),
            "ports": parse("PORTS"),
            "asns": parse("ASNS"),
            "fixed_condition": fixed,
            "max_workers": max_workers,
            "request_interval": request_interval,
            "max_retries": 3,
            "page_size": page_size
        }
        if not cfg["email"] or not cfg["key"]:
            messagebox.showwarning("提示", "请填写 Email 和 Key")
            return

        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.config(state=tk.DISABLED)
        self.stop_event = threading.Event()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)

        engine = FofaScanEngine(cfg, self.log_queue, self.stop_event)
        threading.Thread(target=engine.run, daemon=True).start()

    def _listen_queue(self):
        try:
            while True:
                m = self.log_queue.get_nowait()
                if m[0] == "log":
                    self.log_box.config(state=tk.NORMAL)
                    self.log_box.insert("end", m[1] + "\n")
                    self.log_box.see("end")
                    self.log_box.config(state=tk.DISABLED)
                elif m[0] == "progress":
                    self.progress['value'] = (m[1][0] / m[1][1] * 100) if m[1][1] else 0
                elif m[0] == "stats":
                    s = m[1]
                    self.stat_info.config(text=f"已完成任务: {s['done']} | 结果条数: {s['rows']} | 跳过: {s['skipped']}")
                elif m[0] == "done":
                    self.btn_start.config(state=tk.NORMAL)
                    self.btn_stop.config(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.root.after(100, self._listen_queue)

if __name__ == "__main__":
    root = tk.Tk()
    FofaGUI(root)
    root.mainloop()
