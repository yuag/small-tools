import os
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from google.cloud import storage
from google.oauth2 import service_account
from datetime import datetime

class GCSDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("GCS 高速文件浏览器 (已优化)")
        self.root.geometry("900x700")

        self.client = None
        self.all_blobs = []  # 缓存所有 blob 对象，方便过滤和全选
        
        self.setup_ui()

    def setup_ui(self):
        # --- 样式配置 ---
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)

        # --- 第一步：凭据区域 ---
        cred_frame = ttk.LabelFrame(self.root, text=" 身份凭据 ", padding="10")
        cred_frame.pack(fill=tk.X, padx=10, pady=5)

        self.cred_label = ttk.Label(cred_frame, text="请先加载 JSON 密钥", foreground="gray")
        self.cred_label.pack(side=tk.LEFT)
        ttk.Button(cred_frame, text="加载 JSON", command=self.load_json_file).pack(side=tk.RIGHT)

        # --- 第二步：Bucket 与 搜索 ---
        ctrl_frame = ttk.LabelFrame(self.root, text=" 存储桶与过滤 ", padding="10")
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(ctrl_frame, text="Bucket:").grid(row=0, column=0, sticky="w")
        self.bucket_combo = ttk.Combobox(ctrl_frame, state="readonly", width=30)
        self.bucket_combo.grid(row=0, column=1, padx=5, sticky="ew")
        
        self.refresh_btn = ttk.Button(ctrl_frame, text="刷新桶", command=self.fetch_buckets, state=tk.DISABLED)
        self.refresh_btn.grid(row=0, column=2, padx=2)

        self.list_btn = ttk.Button(ctrl_frame, text="列出文件", command=self.load_files, state=tk.DISABLED)
        self.list_btn.grid(row=0, column=3, padx=2)

        ttk.Label(ctrl_frame, text="搜索过滤:").grid(row=1, column=0, pady=10, sticky="w")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.filter_tree)
        self.search_entry = ttk.Entry(ctrl_frame, textvariable=self.search_var)
        self.search_entry.grid(row=1, column=1, columnspan=3, padx=5, pady=10, sticky="ew")
        
        ctrl_frame.columnconfigure(1, weight=1)

        # --- 第三步：Treeview 文件列表 ---
        list_frame = ttk.Frame(self.root, padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True)

        # 定义表格列
        columns = ("name", "size", "time")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        
        self.tree.heading("name", text="文件名 (支持 多选/Ctrl+A)")
        self.tree.heading("size", text="大小")
        self.tree.heading("time", text="最后修改时间")
        
        self.tree.column("name", width=450, anchor="w")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("time", width=180, anchor="center")

        # 滚动条
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        # --- 第四步：操作按钮 ---
        op_frame = ttk.Frame(self.root, padding="10")
        op_frame.pack(fill=tk.X)

        ttk.Button(op_frame, text="全选所有", command=self.select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(op_frame, text="取消全选", command=lambda: self.tree.selection_remove(self.tree.get_children())).pack(side=tk.LEFT)

        self.status_label = ttk.Label(op_frame, text="就绪")
        self.status_label.pack(side=tk.LEFT, padx=20)

        self.download_btn = ttk.Button(op_frame, text="下载所选文件", command=self.download_files, state=tk.DISABLED)
        self.download_btn.pack(side=tk.RIGHT)

    # --- 功能逻辑 ---

    def load_json_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not path: return
        try:
            creds = service_account.Credentials.from_service_account_file(path)
            with open(path, 'r') as f:
                self.project_id = json.load(f).get('project_id', '')
            self.client = storage.Client(credentials=creds, project=self.project_id)
            self.cred_label.config(text=f"项目: {self.project_id}", foreground="green")
            self.refresh_btn.config(state=tk.NORMAL)
            self.fetch_buckets()
        except Exception as e:
            messagebox.showerror("凭据错误", str(e))

    def fetch_buckets(self):
        self.status_label.config(text="获取 Bucket 中...")
        def worker():
            try:
                names = [b.name for b in self.client.list_buckets()]
                self.root.after(0, lambda: self._update_bucket_combo(names))
            except Exception as e:
                # FIX: Capture error message in default argument to avoid closure issue
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: messagebox.showerror("错误", f"无法获取 Bucket: {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def _update_bucket_combo(self, names):
        self.bucket_combo['values'] = names
        if names: self.bucket_combo.current(0)
        self.list_btn.config(state=tk.NORMAL)
        self.status_label.config(text="Bucket 加载完成")

    def load_files(self):
        bucket_name = self.bucket_combo.get()
        if not bucket_name: return
        
        self.list_btn.config(state=tk.DISABLED)
        self.status_label.config(text="正在读取文件索引 (请稍候)...")
        self.tree.delete(*self.tree.get_children())
        self.all_blobs = []

        def worker():
            try:
                bucket = self.client.bucket(bucket_name)
                # 获取列表时只拿必要属性以提高速度
                blobs = list(bucket.list_blobs())
                self.all_blobs = blobs
                
                # 使用后分子批处理插入 UI，防止界面卡死
                self.root.after(0, self._batch_insert, blobs, 0)
            except Exception as e:
                # FIX: Capture error message in default argument to avoid closure issue
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: messagebox.showerror("错误", msg))
                self.root.after(0, lambda: self.list_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def _batch_insert(self, data_list, start_index):
        """分批插入数据，每批 200 条，保持 UI 响应"""
        batch_size = 200
        end_index = start_index + batch_size
        subset = data_list[start_index:end_index]

        for blob in subset:
            size_str = self._format_size(blob.size)
            time_str = blob.updated.strftime("%Y-%m-%d %H:%M:%S") if blob.updated else "N/A"
            self.tree.insert("", "end", iid=blob.name, values=(blob.name, size_str, time_str))

        if end_index < len(data_list):
            self.status_label.config(text=f"已加载 {end_index}...")
            self.root.after(10, self._batch_insert, data_list, end_index)
        else:
            self.status_label.config(text=f"共加载 {len(data_list)} 个文件")
            self.list_btn.config(state=tk.NORMAL)
            self.download_btn.config(state=tk.NORMAL)

    def filter_tree(self, *args):
        """实时搜索过滤"""
        query = self.search_var.get().lower()
        self.tree.delete(*self.tree.get_children())
        # 重新插入符合条件的项
        for blob in self.all_blobs:
            if query in blob.name.lower():
                size_str = self._format_size(blob.size)
                time_str = blob.updated.strftime("%Y-%m-%d %H:%M:%S") if blob.updated else "N/A"
                self.tree.insert("", "end", iid=blob.name, values=(blob.name, size_str, time_str))

    def select_all(self):
        """全选当前可见的所有行"""
        self.tree.selection_set(self.tree.get_children())

    def download_files(self):
        selected_iids = self.tree.selection()
        if not selected_iids:
            messagebox.showwarning("提示", "请先选择（点击高亮）要下载的文件")
            return

        save_dir = filedialog.askdirectory()
        if not save_dir: return

        self.download_btn.config(state=tk.DISABLED)
        
        def worker():
            bucket = self.client.bucket(self.bucket_combo.get())
            total = len(selected_iids)
            try:
                for idx, name in enumerate(selected_iids):
                    self.root.after(0, lambda n=name, i=idx, t=total: self.status_label.config(text=f"下载中 ({i+1}/{t}): {n}"))
                    blob = bucket.blob(name)
                    local_path = os.path.join(save_dir, name)
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    blob.download_to_filename(local_path)
                
                messagebox.showinfo("成功", f"已成功下载 {total} 个文件！")
            except Exception as e:
                # FIX: Capture error message in default argument to avoid closure issue
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: messagebox.showerror("失败", msg))
            finally:
                self.root.after(0, lambda: self.download_btn.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.status_label.config(text="就绪"))

        threading.Thread(target=worker, daemon=True).start()

    def _format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

if __name__ == "__main__":
    root = tk.Tk()
    app = GCSDownloader(root)
    root.mainloop()