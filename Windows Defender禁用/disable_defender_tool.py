import tkinter as tk
from tkinter import messagebox, ttk
import winreg
import ctypes
import sys
import subprocess

class DefenderDisabler:
    def __init__(self, root):
        self.root = root
        self.root.title("Windows Defender 注册表禁用工具")
        self.root.geometry("500x500")
        self.root.resizable(False, False)
        
        # 检查管理员权限
        if not self.is_admin():
            messagebox.showerror("错误", "此工具需要以管理员身份运行！\n\n请右键单击脚本 → 以管理员身份运行")
            sys.exit(1)
        
        self.setup_ui()
        self.check_defender_status()
    
    def is_admin(self):
        """检查是否以管理员身份运行"""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    
    def setup_ui(self):
        """构建UI界面"""
        # 标题
        title_frame = tk.Frame(self.root, bg="#2c3e50")
        title_frame.pack(fill=tk.X)
        
        title = tk.Label(title_frame, text="⚙️ Windows Defender 注册表禁用工具", 
                        font=("Arial", 14, "bold"), bg="#2c3e50", fg="white")
        title.pack(pady=10)
        
        # 状态显示
        status_frame = tk.LabelFrame(self.root, text="当前状态", font=("Arial", 11, "bold"), padx=10, pady=10)
        status_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.status_label = tk.Label(status_frame, text="检查中...", 
                                     font=("Arial", 10), fg="orange", justify=tk.LEFT)
        self.status_label.pack(anchor=tk.W)
        
        # 操作按钮
        button_frame = tk.LabelFrame(self.root, text="操作选项", font=("Arial", 11, "bold"), padx=10, pady=10)
        button_frame.pack(fill=tk.BOTH, padx=10, pady=10, expand=True)
        
        self.disable_btn = tk.Button(button_frame, text="🔒 永久禁用 Defender", 
                                     command=self.disable_defender, 
                                     bg="#e74c3c", fg="white", font=("Arial", 11, "bold"),
                                     cursor="hand2", padx=20, pady=10)
        self.disable_btn.pack(fill=tk.X, pady=5)
        
        self.enable_btn = tk.Button(button_frame, text="✅ 恢复 Defender", 
                                    command=self.enable_defender, 
                                    bg="#27ae60", fg="white", font=("Arial", 11, "bold"),
                                    cursor="hand2", padx=20, pady=10)
        self.enable_btn.pack(fill=tk.X, pady=5)
        
        # 详细信息
        info_frame = tk.LabelFrame(self.root, text="注册表修改项", font=("Arial", 10, "bold"), padx=10, pady=10)
        info_frame.pack(fill=tk.BOTH, padx=10, pady=10, expand=True)
        
        info_text = tk.Text(info_frame, height=10, font=("Courier", 9), state=tk.DISABLED)
        info_text.pack(fill=tk.BOTH)
        
        self.info_text = info_text
        
        # 显示修改内容
        self.update_info_text()
        
        # 底部提示
        tip_frame = tk.LabelFrame(self.root, text="⚠️ 重要提示", font=("Arial", 9), padx=10, pady=5)
        tip_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tip = tk.Label(tip_frame, text="• 修改后请重启电脑生效\n• 确保已安装其他杀毒软件\n• 注意：此操作需要管理员权限", 
                      font=("Arial", 9), justify=tk.LEFT, fg="#7f8c8d")
        tip.pack(anchor=tk.W)
    
    def update_info_text(self):
        """更新信息显示"""
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        
        info = """将修改以下注册表项：

路径：
HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Microsoft\Windows Defender

创建/修改的值：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. DisableAntiSpyware = 1
2. DisableAntiVirus = 1
3. DisableBehaviorMonitoring = 1
4. DisableRealtimeMonitoring = 1

这些设置将永久禁用Defender的核心保护功能。
"""
        self.info_text.insert(1.0, info)
        self.info_text.config(state=tk.DISABLED)
    
    def check_defender_status(self):
        """检查Defender当前状态"""
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                r"SOFTWARE\Policies\Microsoft\Windows Defender")
            
            try:
                disabled_av, _ = winreg.QueryValueEx(key, "DisableAntiVirus")
                disabled_as, _ = winreg.QueryValueEx(key, "DisableAntiSpyware")
                
                if disabled_av == 1 and disabled_as == 1:
                    status = "✅ 已禁用\n（DisableAntiVirus=1, DisableAntiSpyware=1）"
                    color = "green"
                else:
                    status = "❌ 未禁用\n（或禁用不完整）"
                    color = "red"
            except:
                status = "❌ 未禁用\n（注册表项不存在）"
                color = "red"
            
            winreg.CloseKey(key)
        except:
            status = "❌ 未禁用\n（无法读取注册表）"
            color = "red"
        
        self.status_label.config(text=status, fg=color)
    
    def disable_defender(self):
        """禁用Defender"""
        if messagebox.askyesno("确认", "确定要永久禁用 Windows Defender 吗？\n\n"
                               "系统会修改注册表，修改后需要重启电脑才能生效。\n"
                               "请确保已安装其他杀毒软件！"):
            try:
                # 打开或创建注册表键
                key_path = r"SOFTWARE\Policies\Microsoft\Windows Defender"
                key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                
                # 设置禁用值
                winreg.SetValueEx(key, "DisableAntiVirus", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "DisableAntiSpyware", 0, winreg.REG_DWORD, 1)
                
                # 创建实时保护子项并设置
                try:
                    rt_key = winreg.CreateKey(key, "Real-Time Protection")
                    winreg.SetValueEx(rt_key, "DisableBehaviorMonitoring", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(rt_key, "DisableRealtimeMonitoring", 0, winreg.REG_DWORD, 1)
                    winreg.CloseKey(rt_key)
                except:
                    pass
                
                winreg.CloseKey(key)
                
                messagebox.showinfo("成功", "✅ 注册表已修改！\n\n"
                                   "请立即重启电脑让更改生效。\n\n"
                                   "修改完成后，Defender 会被永久禁用。")
                
                self.check_defender_status()
                
                # 询问是否立即重启
                if messagebox.askyesno("重启", "是否立即重启电脑？"):
                    os.system("shutdown /s /t 30 /c 'Windows Defender 已禁用，电脑将在30秒后重启'")
                
            except Exception as e:
                messagebox.showerror("错误", f"修改注册表失败！\n\n错误信息：{str(e)}\n\n"
                                    "请确保以管理员身份运行此工具。")
    
    def enable_defender(self):
        """恢复Defender"""
        if messagebox.askyesno("确认", "确定要恢复 Windows Defender 吗？\n\n"
                               "系统会删除禁用的注册表值。"):
            try:
                key_path = r"SOFTWARE\Policies\Microsoft\Windows Defender"
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 
                                    access=winreg.KEY_WRITE)
                
                # 删除禁用值
                try:
                    winreg.DeleteValue(key, "DisableAntiVirus")
                except:
                    pass
                
                try:
                    winreg.DeleteValue(key, "DisableAntiSpyware")
                except:
                    pass
                
                # 删除实时保护子项的值
                try:
                    rt_key = winreg.OpenKey(key, "Real-Time Protection", 
                                          access=winreg.KEY_WRITE)
                    try:
                        winreg.DeleteValue(rt_key, "DisableBehaviorMonitoring")
                    except:
                        pass
                    try:
                        winreg.DeleteValue(rt_key, "DisableRealtimeMonitoring")
                    except:
                        pass
                    winreg.CloseKey(rt_key)
                except:
                    pass
                
                winreg.CloseKey(key)
                
                messagebox.showinfo("成功", "✅ 注册表已恢复！\n\n"
                                   "请重启电脑让更改生效。\n\n"
                                   "Defender 会恢复到默认状态。")
                
                self.check_defender_status()
                
            except Exception as e:
                messagebox.showerror("错误", f"修改注册表失败！\n\n错误信息：{str(e)}")

if __name__ == "__main__":
    import os
    root = tk.Tk()
    app = DefenderDisabler(root)
    root.mainloop()
