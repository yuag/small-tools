# -*- coding: utf-8 -*-
import os
import base64
import csv
import time
import random
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

        self.api_exhausted = False  # API 耗尽开关
        self.done_set_mem = set()
        self.stats = {"total": 0, "skipped": 0, "empty": 0, "done": 0, "rows": 0}

        self._local = threading.local()

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
            # 设置重试逻辑
            retry = Retry(total=self.cfg["max_retries"], backoff_factor=1, status_forcelist=[500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._local.session = session
        return self._local.session

    def fofa_query(self, q, task_id, page=1):
        """核心请求函数，包含 API 状态监控"""
        if self.api_exhausted: return None

        q_base64 = base64.b64encode(q.encode()).decode()
        url = (
            f"https://fofa.info/api/v1/search/all?"
            f"email={self.cfg['email']}&key={self.cfg['key']}"
            f"&page={page}&size={self.cfg['page_size']}"
            f"&fields={FIELDS}"
            f"&qbase64={q_base64}"
        )
        
        for attempt in range(1, self.cfg["max_retries"] + 1):
            if self.stop_event.is_set() or self.api_exhausted: return None
            try:
                resp = self.get_session().get(url, timeout=25)
                if resp.status_code == 429:
                    time.sleep(20) # 被限速
                    continue

                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    errmsg = data.get("errmsg", "").lower()
                    # 检测 API 余额或权限是否用尽
                    if any(k in errmsg for k in ["balance", "quota", "permission", "insufficient", "overdue", "limit"]):
                        self.log("\n" + "!"*60)
                        self.log(f"[!!!] 停止：API 额度已用尽或账号权限不足！")
                        self.log(f"[!!!] 最后的扫描任务: {task_id}")
                        self.log(f"[!!!] 最后的查询语句: {q}")
                        self.log(f"[!!!] 官方错误原因: {errmsg}")
                        self.log("!"*60 + "\n")
                        self.api_exhausted = True
                        self.stop_event.set() # 停止所有后续线程
                        return None
                    return None
                return data
            except Exception as e:
                if attempt == self.cfg["max_retries"]:
                    self.log(f"[!] 任务 {task_id} 请求失败: {e}")
                time.sleep(2)
        return None

    def append_to_final_csv(self, rows):
        """实时将数据写入总表，无需去重"""
        if not rows: return
        p = os.path.join(self.cfg["output_dir"], FINAL_CSV)
        with self.file_lock:
            exists = os.path.exists(p)
            with open(p, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                if not exists: writer.writerow(FIELDS.split(","))
                writer.writerows(rows)
            with self.stats_lock:
                self.stats["rows"] += len(rows)

    def run_task(self, task):
        idx, total_tasks, query, task_id, sub_csv_path = task
        
        # 检查是否已完成或需停止
        with self.done_lock:
            if task_id in self.done_set_mem:
                with self.stats_lock: self.stats["skipped"] += 1
                return

        task_results = []
        page = 1
        while True:
            if self.stop_event.is_set() or self.api_exhausted: break
            
            data = self.fofa_query(query, task_id, page=page)
            if not data or not data.get("results"): break

            rows = data["results"]
            task_results.extend(rows)
            
            # 实时保存到总文件
            self.append_to_final_csv(rows)

            total_size = int(data.get("size", 0))
            if page == 1:
                self.log(f"[{idx}/{total_tasks}] {task_id} | 发现 {total_size} 条记录")
            else:
                self.log(f"  └─ {task_id} 翻页: 第 {page} 页")

            if len(task_results) >= total_size or len(rows) < self.cfg["page_size"]: 
                break
            
            page += 1
            time.sleep(self.cfg["min_delay"] + random.random() * (self.cfg["max_delay"] - self.cfg["min_delay"]))

        if task_results:
            # 存一份独立的小文件
            with self.file_lock:
                with open(sub_csv_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(FIELDS.split(","))
                    writer.writerows(task_results)
            with self.stats_lock: self.stats["done"] += 1
        else:
            if not self.api_exhausted:
                with self.stats_lock: self.stats["empty"] += 1

        # 记录完成标记
        if not self.api_exhausted and not self.stop_event.is_set():
            p = os.path.join(self.cfg["output_dir"], DONE_FILE)
            with self.done_lock:
                self.done_set_mem.add(task_id)
                with open(p, "a", encoding="utf-8") as f: f.write(task_id + "\n")

    def run(self):
        os.makedirs(self.cfg["output_dir"], exist_ok=True)
        # 加载断点
        p = os.path.join(self.cfg["output_dir"], DONE_FILE)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                self.done_set_mem = set(line.strip() for line in f if line.strip())

        # 生成组合
        combos = list(product(self.cfg["keywords"], self.cfg["countries"], self.cfg["ports"], self.cfg["asns"]))
        tasks = []
        for idx, (kw, c, p, a) in enumerate(combos, 1):
            q_parts = [f'({kw})']
            if c: q_parts.append(f'country="{c}"')
            if p: q_parts.append(f'port="{p}"')
            if a: q_parts.append(f'asn="{a}"')
            
            query = " && ".join(q_parts)
            # 文件名安全处理
            safe_kw = re.sub(r'[\\/:*?"<>|=]', "_", kw)[:30]
            tid = f"{c or 'ALL'}_{p or 'ALL'}_{a or 'ALL'}_{safe_kw}"
            sub_csv = os.path.join(self.cfg["output_dir"], f"{tid}.csv")
            tasks.append((idx, len(combos), query, tid, sub_csv))

        pending = [t for t in tasks if t[3] not in self.done_set_mem]
        self.log(f"[*] 任务准备就绪。总组合: {len(tasks)}，待扫描: {len(pending)}")
        self.report_progress(0, max(1, len(pending)))

        with ThreadPoolExecutor(max_workers=self.cfg["max_workers"]) as executor:
            futures = {executor.submit(self.run_task, t): t[3] for t in pending}
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                self.report_progress(done_count, len(pending))
                self.report_stats()
                if self.api_exhausted: break

        self.log(f"\n[✓] 流程结束。总计抓取数据: {self.stats['rows']} 条。")
        self.log_queue.put(("done", None))

# ----------------------------------------------------------------------------
# GUI 界面
# ----------------------------------------------------------------------------
class FofaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FOFA 批量扫描工具 (全量/断点版)")
        self.root.geometry("1100x800")
        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self._setup_ui()
        self._listen_queue()

    def _setup_ui(self):
        # 布局
        left = ttk.Frame(self.root); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        right = ttk.Frame(self.root); right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 1. 账号
        f1 = ttk.LabelFrame(left, text="账号信息")
        f1.pack(fill=tk.X, pady=5)
        ttk.Label(f1, text="Email:").grid(row=0, column=0, padx=5, pady=5)
        self.email = ttk.Entry(f1, width=35); self.email.grid(row=0, column=1)
        ttk.Label(f1, text="Key:").grid(row=1, column=0, padx=5, pady=5)
        self.key = ttk.Entry(f1, width=35, show="*"); self.key.grid(row=1, column=1)

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
        for i, name in enumerate(["KEYWORDS", "COUNTRIES", "PORTS", "ASNS"]):
            frame = ttk.Frame(f3); frame.grid(row=i//2, column=i%2, sticky="nsew", padx=5, pady=5)
            ttk.Label(frame, text=name).pack(anchor="w")
            txt = tk.Text(frame, width=25, height=10); txt.pack(fill=tk.BOTH, expand=True)
            self.inputs[name] = txt
        f3.columnconfigure(0, weight=1); f3.columnconfigure(1, weight=1)

        # 4. 按钮
        self.btn_start = ttk.Button(left, text="开始扫描", command=self._start)
        self.btn_start.pack(side=tk.LEFT, padx=20, pady=10)
        self.btn_stop = ttk.Button(left, text="强行停止", command=lambda: self.stop_event.set(), state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, pady=10)

        # 右侧：统计和日志
        self.stat_info = ttk.Label(right, text="就绪", font=("", 10, "bold"))
        self.stat_info.pack(pady=5)
        self.progress = ttk.Progressbar(right, mode='determinate'); self.progress.pack(fill=tk.X, padx=10, pady=5)
        self.log_box = tk.Text(right, bg="#1c1c1c", fg="#00e600", state=tk.DISABLED)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _start(self):
        def parse(name):
            val = self.inputs[name].get("1.0", "end").strip().splitlines()
            return [v.strip() for v in val if v.strip()] or [""]

        cfg = {
            "email": self.email.get().strip(), "key": self.key.get().strip(),
            "output_dir": self.path.get().strip(),
            "keywords": parse("KEYWORDS"), "countries": parse("COUNTRIES"),
            "ports": parse("PORTS"), "asns": parse("ASNS"),
            "max_workers": 5, "min_delay": 1.5, "max_delay": 2.5, "max_retries": 2, "page_size": 10000
        }
        if not cfg["email"] or not cfg["key"]: 
            messagebox.showwarning("提示", "请填写 Email 和 Key"); return

        self.log_box.config(state=tk.NORMAL); self.log_box.delete("1.0", tk.END); self.log_box.config(state=tk.DISABLED)
        self.stop_event = threading.Event()
        self.btn_start.config(state=tk.DISABLED); self.btn_stop.config(state=tk.NORMAL)
        
        engine = FofaScanEngine(cfg, self.log_queue, self.stop_event)
        threading.Thread(target=engine.run, daemon=True).start()

    def _listen_queue(self):
        try:
            while True:
                m = self.log_queue.get_nowait()
                if m[0] == "log":
                    self.log_box.config(state=tk.NORMAL); self.log_box.insert("end", m[1]+"\n"); self.log_box.see("end"); self.log_box.config(state=tk.DISABLED)
                elif m[0] == "progress":
                    self.progress['value'] = (m[1][0]/m[1][1]*100) if m[1][1] else 0
                elif m[0] == "stats":
                    s = m[1]; self.stat_info.config(text=f"已完成任务: {s['done']} | 结果条数: {s['rows']} | 跳过: {s['skipped']}")
                elif m[0] == "done":
                    self.btn_start.config(state=tk.NORMAL); self.btn_stop.config(state=tk.DISABLED)
        except queue.Empty: pass
        self.root.after(100, self._listen_queue)

if __name__ == "__main__":
    root = tk.Tk(); FofaGUI(root); root.mainloop()
