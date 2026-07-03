import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests


class FastSonarDownloaderGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("SonarQube 源码高速安全下载器")
        self.root.geometry("620x460")
        self.root.resizable(False, False)

        # 设置界面样式
        style = ttk.Style()
        style.theme_use("clam")

        # 1. 网址输入
        tk.Label(root, text="SonarQube 基础网址:", font=("Arial", 10)).place(
            x=30, y=25
        )
        self.url_entry = tk.Entry(root, width=50, font=("Arial", 10))
        self.url_entry.place(x=160, y=25)
        self.url_entry.insert(0, "http://127.0.0.1")

        # 2. 项目Key输入
        tk.Label(root, text="项目名称 (ID/Key):", font=("Arial", 10)).place(
            x=30, y=65
        )
        self.key_entry = tk.Entry(root, width=50, font=("Arial", 10))
        self.key_entry.place(x=160, y=65)
        self.key_entry.insert(0, "")

        # 3. 保存路径选择
        tk.Label(root, text="本地保存路径:", font=("Arial", 10)).place(
            x=30, y=105
        )
        self.path_entry = tk.Entry(root, width=38, font=("Arial", 10))
        self.path_entry.place(x=160, y=105)
        default_path = os.path.abspath("./service_api_sources")
        self.path_entry.insert(0, default_path)

        self.browse_btn = tk.Button(
            root, text="选择浏览...", command=self.browse_folder
        )
        self.browse_btn.place(x=440, y=101)

        # 4. 安全并发控制 (新增滑块，防止网站卡死)
        tk.Label(
            root, text="并发线程数 (控制速度):", font=("Arial", 10)
        ).place(x=30, y=145)
        self.thread_scale = tk.Scale(
            root, from_=1, to=20, orient=tk.HORIZONTAL, length=200
        )
        self.thread_scale.set(5)  # 默认设置为 5 线程，安全且温和
        self.thread_scale.place(x=160, y=130)

        tk.Label(
            root, text="※ 提示: 担心服务器撑不住可调低至 2~3", fg="gray", font=("Arial", 9)
        ).place(x=380, y=145)

        # 5. 下载按钮
        self.download_btn = tk.Button(
            root,
            text="开始批量下载源码",
            font=("Arial", 11, "bold"),
            bg="#28a745",
            fg="white",
            width=25,
            height=2,
            command=self.start_download_thread,
        )
        self.download_btn.place(x=180, y=190)

        # 6. 日志输出文本框与滚动条
        tk.Label(root, text="下载进度日志:", font=("Arial", 10)).place(
            x=30, y=250
        )
        self.log_text = tk.Text(
            root, width=75, height=11, font=("Consolas", 9), state=tk.DISABLED
        )
        self.log_text.place(x=30, y=270)

        scrollbar = tk.Scrollbar(root, command=self.log_text.yview)
        scrollbar.place(x=570, y=270, height=160)
        self.log_text.config(yscrollcommand=scrollbar.set)

        # 下载控制开关
        self.is_running = False

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, os.path.abspath(folder))

    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def start_download_thread(self):
        if self.is_running:
            return
        thread = threading.Thread(target=self.execute_download)
        thread.daemon = True
        thread.start()

    def download_single_file(self, sonar_url, file_info, save_dir):
        """单个文件的下载任务（供线程池调用）"""
        file_key = file_info["key"]
        file_path = file_info["path"]

        local_path = os.path.join(save_dir, file_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        source_url = f"{sonar_url}/api/sources/raw?key={file_key}"
        try:
            # 设置 5 秒超时，防止单次请求卡死死锁
            src_res = requests.get(source_url, timeout=5)
            if src_res.status_code == 200:
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(src_res.text)
                return True, file_path
            else:
                return False, f"{file_path} (状态码 {src_res.status_code})"
        except Exception as e:
            return False, f"{file_path} (错误: {e})"

    def execute_download(self):
        self.is_running = True
        sonar_url = self.url_entry.get().strip().rstrip("/")
        project_key = self.key_entry.get().strip()
        save_dir = self.path_entry.get().strip()
        max_workers = self.thread_scale.get()  # 获取当前滑块选择的线程数

        if not sonar_url or not project_key or not save_dir:
            messagebox.showwarning("提示", "请完整填写所有输入项！")
            self.is_running = False
            return

        self.download_btn.config(state=tk.DISABLED, text="正在下载中...", bg="#6c757d")
        self.log(f"正在建立连接... (当前安全线程数设为: {max_workers})")

        # 1. 自动翻页获取所有文件列表
        files = []
        page = 1
        ps = 500

        while True:
            tree_url = f"{sonar_url}/api/components/tree?component={project_key}&qualifiers=FIL&p={page}&ps={ps}"
            try:
                res = requests.get(tree_url, timeout=10)
                if res.status_code != 200:
                    self.log(f"【错误】服务器响应异常，状态码: {res.status_code}")
                    break
                data = res.json()
            except Exception as e:
                self.log(f"【错误】无法连接到服务器: {e}")
                break

            if "components" not in data or not data["components"]:
                break

            files.extend(data["components"])
            if len(data["components"]) < ps:
                break
            page += 1

        if not files:
            self.log("【失败】未能获取到任何项目文件。")
            self.download_btn.config(
                state=tk.NORMAL, text="开始批量下载源码", bg="#28a745"
            )
            self.is_running = False
            return

        self.log(f"【成功连通】项目共有 {len(files)} 个文件。开始多线程并发拉取...")

        # 2. 使用线程池并发下载
        success_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有下载任务
            futures = {
                executor.submit(
                    self.download_single_file, sonar_url, f_info, save_dir
                ): f_info
                for f_info in files
            }

            # 哪个下完哪个先打印日志
            for future in as_completed(futures):
                success, info = future.result()
                if success:
                    self.log(f"已成功下载: {info}")
                    success_count += 1
                else:
                    self.log(f" 下载失败: {info}")

        self.log(
            f"\n任务结束！成功下载 {success_count}/{len(files)} 个文件。"
        )
        self.log(f"保存位置: {os.path.abspath(save_dir)}")

        self.download_btn.config(state=tk.NORMAL, text="开始批量下载源码", bg="#28a745")
        self.is_running = False
        messagebox.showinfo(
            "下载成功", f"源码已全部下载完成！\n路径：{os.path.abspath(save_dir)}"
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = FastSonarDownloaderGUI(root)
    root.mainloop()
