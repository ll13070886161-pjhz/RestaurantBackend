#!/usr/bin/env python3
"""
云存储上传工具
支持多种云存储服务
"""

import os
import sys
import json
import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
import requests

class CloudUploader:
    """云存储上传器"""
    
    def __init__(self):
        self.services = {
            'catbox': self.upload_to_catbox,
            'file.io': self.upload_to_fileio,
            '0x0.st': self.upload_to_0x0,
        }
    
    def upload_to_catbox(self, file_path: Path) -> Optional[str]:
        """上传到 catbox.moe (免费，无大小限制)"""
        try:
            with open(file_path, 'rb') as f:
                files = {'fileToUpload': (file_path.name, f)}
                response = requests.post('https://catbox.moe/user/api.php', files=files)
                if response.status_code == 200 and response.text.startswith('http'):
                    return response.text.strip()
        except Exception as e:
            print(f"Catbox上传失败: {e}")
        return None
    
    def upload_to_fileio(self, file_path: Path) -> Optional[str]:
        """上传到 file.io (14天有效期)"""
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f)}
                response = requests.post('https://file.io/', files=files)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        return data.get('link')
        except Exception as e:
            print(f"File.io上传失败: {e}")
        return None
    
    def upload_to_0x0(self, file_path: Path) -> Optional[str]:
        """上传到 0x0.st (无限制)"""
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f)}
                response = requests.post('https://0x0.st/', files=files)
                if response.status_code == 200:
                    return response.text.strip()
        except Exception as e:
            print(f"0x0.st上传失败: {e}")
        return None
    
    def upload_file(self, file_path: Path, service: str = 'auto') -> Optional[str]:
        """上传文件到云存储"""
        if not file_path.exists():
            print(f"文件不存在: {file_path}")
            return None
        
        file_size = file_path.stat().st_size
        print(f"上传文件: {file_path.name} ({file_size/1024:.1f} KB)")
        
        if service == 'auto':
            # 尝试所有服务
            for service_name, upload_func in self.services.items():
                print(f"尝试 {service_name}...")
                url = upload_func(file_path)
                if url:
                    print(f"✓ 上传成功到 {service_name}: {url}")
                    return url
            return None
        else:
            if service in self.services:
                return self.services[service](file_path)
            else:
                print(f"未知服务: {service}")
                return None

def main():
    if len(sys.argv) < 2:
        print("用法: python cloud_upload.py <文件路径> [服务名称]")
        print("可用服务: catbox, file.io, 0x0.st, auto")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    service = sys.argv[2] if len(sys.argv) > 2 else 'auto'
    
    uploader = CloudUploader()
    url = uploader.upload_file(file_path, service)
    
    if url:
        print(f"\n下载链接: {url}")
        # 复制到剪贴板（macOS）
        if sys.platform == 'darwin':
            import subprocess
            subprocess.run(['pbcopy'], input=url.encode())
            print("链接已复制到剪贴板")
    else:
        print("上传失败，请重试或检查网络连接")
        sys.exit(1)

if __name__ == '__main__':
    main()