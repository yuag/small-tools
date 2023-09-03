import os

# 检查文件是否存在
def check_file_exists(file_path):
    return os.path.isfile(file_path)

# 检查进程是否运行
def check_process_running(process_name):
    process_list = os.popen('tasklist').read()
    return process_name.lower() in process_list.lower()

files_to_check = [
    "C:\\windows\\System32\\Drivers\\Vmmouse.sys",
    "C:\\windows\\System32\\Drivers\\vmtray.dll",
    "C:\\windows\\System32\\Drivers\\Vmmouse.sys",
    "C:\\windows\\System32\\Drivers\\vmtray.dll",
    "C:\\windows\\System32\\Drivers\\VMToolsHook.dll",
    "C:\\windows\\System32\\Drivers\\vmmousever.dll",
    "C:\\windows\\System32\\Drivers\\vmhgfs.dll",
    "C:\\windows\\System32\\Drivers\\vmGuestLib.dll",
    "C:\\windows\\System32\\Drivers\\VBoxMouse.sys",
    "C:\\windows\\System32\\Drivers\\VBoxGuest.sys",
    "C:\\windows\\System32\\Drivers\\VBoxSF.sys",
    "C:\\windows\\System32\\Drivers\\VBoxVideo.sys",
    "C:\\windows\\System32\\vboxdisp.dll",
    "C:\\windows\\System32\\vboxhook.dll",
    "C:\\windows\\System32\\vboxoglerrorspu.dll",
    "C:\\windows\\System32\\vboxoglpassthroughspu.dll",
    "C:\\windows\\System32\\vboxservice.exe",
    "C:\\windows\\System32\\vboxtray.exe",
    "C:\\windows\\System32\\VBoxControl.exe",
    # 添加其他文件路径...
]

processes_to_check = [
    "vmtoolsd.exe",
    "VBoxService.exe",
    "Vmwaretrat.exe",
    "Vmwareuser.exe",
    "Vmacthlp.exe",
    "vboxtray.exe",
    # 添加其他进程名称...
]

is_virtual_machine = False

# 检查文件是否存在
for file_path in files_to_check:
    if check_file_exists(file_path):
        is_virtual_machine = True
        break

# 检查进程是否运行
for process_name in processes_to_check:
    if check_process_running(process_name):
        is_virtual_machine = True
        break

if is_virtual_machine:
    print("虚拟机检测到了。")
else:
    print("没有检测到虚拟机。")
