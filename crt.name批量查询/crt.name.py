import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import queue
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os
from datetime import datetime

class CrtNameGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("crt.name 批量子域名查询工具（支持自动保存）")
        self.root.geometry("950x750")
        self.root.minsize(850, 650)

        self.is_running = False
        self.result_queue = queue.Queue()
        self.total_domains = 0
        self.finished_count = 0
        self.auto_save_path = None          # 当前自动保存文件路径
        self.all_results = []               # 完整结果缓存

        self.create_widgets()
        self.poll_queue()

    def create_widgets(self):
        # ===== 顶部输入区 =====
        top_frame = ttk.LabelFrame(self.root, text="域名输入（每行一个 apex 域名）", padding=10)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        self.domain_text = scrolledtext.ScrolledText(top_frame, height=6, font=("Consolas", 11))
        self.domain_text.pack(fill=tk.X)
        self.domain_text.insert(tk.END, "example.com")

        # ===== 选项区 =====
        option_frame = ttk.Frame(self.root)
        option_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(option_frame, text="线程数:").pack(side=tk.LEFT)
        self.thread_var = tk.IntVar(value=3)
        ttk.Spinbox(option_frame, from_=1, to=8, width=5, textvariable=self.thread_var).pack(side=tk.LEFT, padx=5)

        self.json_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(option_frame, text="JSON 格式", variable=self.json_var).pack(side=tk.LEFT, padx=10)

        self.dates_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(option_frame, text="包含首次出现日期", variable=self.dates_var).pack(side=tk.LEFT, padx=10)

        self.auto_save_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(option_frame, text="自动保存结果", variable=self.auto_save_var).pack(side=tk.LEFT, padx=15)

        # ===== 按钮区 =====
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.start_btn = ttk.Button(btn_frame, text="开始批量查询", command=self.start_query)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_query, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="清空结果", command=self.clear_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="复制全部结果", command=self.copy_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="手动导出 TXT", command=self.export_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="选择自动保存目录", command=self.choose_save_dir).pack(side=tk.LEFT, padx=5)

        # ===== 进度条 =====
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill=tk.X, padx=10, pady=5)

        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress.pack(fill=tk.X, side=tk.LEFT, expand=True)

        self.status_label = ttk.Label(progress_frame, text="就绪", width=30)
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # ===== 结果区 =====
        result_frame = ttk.LabelFrame(self.root, text="查询结果", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.result_text = scrolledtext.ScrolledText(result_frame, font=("Consolas", 10))
        self.result_text.pack(fill=tk.BOTH, expand=True)

        # 默认保存目录
        self.save_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(self.save_dir):
            self.save_dir = os.getcwd()

    def choose_save_dir(self):
        path = filedialog.askdirectory(initialdir=self.save_dir)
        if path:
            self.save_dir = path
            messagebox.showinfo("提示", f"自动保存目录已设置为:\n{self.save_dir}")

    def start_query(self):
        domains = [d.strip() for d in self.domain_text.get("1.0", tk.END).splitlines() if d.strip()]
        if not domains:
            messagebox.showwarning("提示", "请至少输入一个域名")
            return

        if len(domains) > 1000:
            if not messagebox.askyesno("警告", f"你输入了 {len(domains)} 个域名，超过免费额度（1000/天）。\n是否继续？"):
                return

        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.finished_count = 0
        self.total_domains = len(domains)
        self.progress_var.set(0)
        self.status_label.config(text=f"0 / {self.total_domains}")
        self.all_results = []

        # 创建自动保存文件
        self.auto_save_path = None
        if self.auto_save_var.get():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"crt_name_results_{timestamp}.txt"
            self.auto_save_path = os.path.join(self.save_dir, filename)
            with open(self.auto_save_path, "w", encoding="utf-8") as f:
                f.write(f"crt.name 批量查询结果\n")
                f.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"域名数量: {self.total_domains}\n")
                f.write("=" * 70 + "\n\n")

        self.result_text.delete("1.0", tk.END)
        self.result_text.insert(tk.END, f"[*] 开始查询 {self.total_domains} 个域名，线程数: {self.thread_var.get()}\n")
        if self.auto_save_path:
            self.result_text.insert(tk.END, f"[*] 自动保存文件: {self.auto_save_path}\n")
        self.result_text.insert(tk.END, "\n")

        threading.Thread(target=self.worker, args=(domains,), daemon=True).start()

    def stop_query(self):
        self.is_running = False
        self.status_label.config(text="正在停止...")
        self.stop_btn.config(state=tk.DISABLED)

    def worker(self, domains):
        max_workers = self.thread_var.get()
        use_json = self.json_var.get()
        use_dates = self.dates_var.get()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.query_one, domain, use_json, use_dates): domain
                for domain in domains
            }

            for future in as_completed(futures):
                if not self.is_running:
                    break
                domain = futures[future]
                try:
                    result = future.result()
                    self.result_queue.put(("ok", domain, result))
                except Exception as e:
                    self.result_queue.put(("error", domain, str(e)))

        self.result_queue.put(("done", None, None))

    def query_one(self, apex: str, use_json: bool, use_dates: bool) -> str:
        params = {"apex": apex}
        if use_json:
            params["format"] = "json"
        if use_dates:
            params["dates"] = "1"

        url = "https://crt.name/v1/search"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; crt-name-gui/1.1)"}

        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return resp.text.strip()
                elif resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    raise Exception(f"HTTP {resp.status_code}: {resp.text[:120]}")
            except requests.RequestException as e:
                if attempt == 2:
                    raise
                time.sleep(1)
        raise Exception("重试失败")

    def append_to_file(self, text: str):
        """实时追加写入自动保存文件"""
        if self.auto_save_path:
            try:
                with open(self.auto_save_path, "a", encoding="utf-8") as f:
                    f.write(text)
            except Exception as e:
                print(f"写入文件失败: {e}")

    def poll_queue(self):
        try:
            while True:
                msg_type, domain, data = self.result_queue.get_nowait()

                if msg_type == "ok":
                    self.finished_count += 1
                    block = f"{'='*60}\n[+] {domain}\n{'-'*60}\n"
                    if data:
                        block += data + "\n\n"
                    else:
                        block += "(无结果)\n\n"

                    self.result_text.insert(tk.END, block)
                    self.result_text.see(tk.END)
                    self.all_results.append(block)
                    self.append_to_file(block)          # 实时保存

                elif msg_type == "error":
                    self.finished_count += 1
                    block = f"[!] {domain} 失败: {data}\n\n"
                    self.result_text.insert(tk.END, block)
                    self.result_text.see(tk.END)
                    self.all_results.append(block)
                    self.append_to_file(block)

                elif msg_type == "done":
                    self.is_running = False
                    self.start_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.status_label.config(text="完成")
                    self.progress_var.set(100)

                    finish_msg = f"\n[*] 全部完成！共处理 {self.finished_count} 个域名\n"
                    if self.auto_save_path:
                        finish_msg += f"[*] 结果已自动保存到:\n{self.auto_save_path}\n"
                        # 再写一次结束标记
                        self.append_to_file(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        self.append_to_file(f"成功处理: {self.finished_count} 个域名\n")

                    self.result_text.insert(tk.END, finish_msg)
                    self.result_text.see(tk.END)
                    break

                if self.total_domains > 0:
                    percent = (self.finished_count / self.total_domains) * 100
                    self.progress_var.set(percent)
                    self.status_label.config(text=f"{self.finished_count} / {self.total_domains}")

        except queue.Empty:
            pass

        self.root.after(100, self.poll_queue)

    def clear_result(self):
        self.result_text.delete("1.0", tk.END)
        self.all_results = []

    def copy_result(self):
        content = self.result_text.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        messagebox.showinfo("提示", "结果已复制到剪贴板")

    def export_result(self):
        content = self.result_text.get("1.0", tk.END)
        if not content.strip():
            messagebox.showwarning("提示", "没有可导出的内容")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=self.save_dir
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("提示", f"已导出到:\n{path}")


if __name__ == "__main__":
    root = tk.Tk()
    app = CrtNameGUI(root)
    root.mainloop()