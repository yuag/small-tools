import tkinter as tk
import json
import requests
from tkinter import filedialog
import urllib3
urllib3.disable_warnings()


class AwvsScanGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Awvs Scan GUI")
        self.geometry("400x200")
        
        self.scanner_entry = tk.Entry(self)
        self.scanner_entry.pack()
        self.scanner_entry.insert(tk.END, "wvs地址")  # Modify URL

        self.api_entry = tk.Entry(self)
        self.api_entry.pack()
        self.api_entry.insert(tk.END, "秘钥")  # Modify API

        self.browse_button = tk.Button(self, text="添加URL", command=self.browse_file)
        self.browse_button.pack()

        self.start_button = tk.Button(self, text="Start", command=self.start_scan)
        self.start_button.pack()

        self.result_label = tk.Label(self)
        self.result_label.pack()

        self.file_path = ""

    def browse_file(self):
        self.file_path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])

    def start_scan(self):
        scanner_url = self.scanner_entry.get()
        api_key = self.api_entry.get()

        headers = {'X-Auth': api_key, 'content-type': 'application/json'}

        try:
            success_count = 0
            failure_count = 0

            with open(self.file_path) as file:
                for line in file:
                    website = line.strip('\n\r')
                    data = {
                        'address': website,
                        'description': 'awvs-auto',
                        'criticality': '10'
                    }
                    response = requests.post(f'{scanner_url}/api/v1/targets', data=json.dumps(data), headers=headers, verify=False)
                    if response.status_code == 201:
                        success_count += 1
                        print(f'Successfully added target: {website}')
                    else:
                        failure_count += 1
                        print(f'Failed to add target: {website}')

            result_message = f"添加成功的URL数量: {success_count}\n添加失败的URL数量: {failure_count}"
            self.result_label.config(text=result_message)

        except Exception as e:
            print(f'Error: {str(e)}')

if __name__ == "__main__":
    app = AwvsScanGUI()
    app.mainloop()
