#!/usr/bin/env python3
"""
图片解析到GitHub Gist集成脚本
将图片上传到图片解析服务，然后将生成的Excel上传到GitHub Gist
"""

import os
import sys
import json
import base64
import requests
from pathlib import Path
from typing import Optional, Dict, Any
import tempfile

# 配置
IMAGE2EXCEL_API = "http://localhost:8000"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")  # 从环境变量读取，避免明文泄露
GIST_API = "https://api.github.com/gists"

class Image2ExcelGistUploader:
    def __init__(self, image2excel_url: str = IMAGE2EXCEL_API, github_token: str = GITHUB_TOKEN):
        self.image2excel_url = image2excel_url.rstrip("/")
        self.github_token = (github_token or "").strip()
        if not self.github_token:
            raise ValueError("GITHUB_TOKEN is empty. Please set environment variable GITHUB_TOKEN.")
        self.headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
    
    def check_service(self) -> bool:
        """检查图片解析服务是否可用"""
        try:
            response = requests.get(f"{self.image2excel_url}/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def upload_image_to_service(self, image_path: Path) -> Optional[Dict[str, Any]]:
        """上传图片到图片解析服务"""
        if not image_path.exists():
            print(f"错误: 图片文件不存在: {image_path}")
            return None
        
        try:
            with open(image_path, 'rb') as f:
                files = {'files': (image_path.name, f, 'image/jpeg')}
                response = requests.post(
                    f"{self.image2excel_url}/api/parse-images",
                    files=files,
                    timeout=30
                )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"图片解析服务错误: {response.status_code}")
                print(f"响应: {response.text[:200]}")
                return None
                
        except Exception as e:
            print(f"上传图片失败: {e}")
            return None
    
    def download_excel_file(self, filename: str) -> Optional[Path]:
        """从图片解析服务下载Excel文件"""
        try:
            response = requests.get(
                f"{self.image2excel_url}/api/download/{filename}",
                timeout=30
            )
            
            if response.status_code == 200:
                # 保存到临时文件
                temp_file = tempfile.NamedTemporaryFile(
                    suffix=".xlsx", 
                    delete=False,
                    prefix="excel_"
                )
                temp_file.write(response.content)
                temp_file.close()
                return Path(temp_file.name)
            else:
                print(f"下载Excel文件失败: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"下载Excel失败: {e}")
            return None
    
    def upload_to_gist(self, file_path: Path, description: str = "Excel报表") -> Optional[str]:
        """上传文件到GitHub Gist"""
        if not file_path.exists():
            print(f"错误: 要上传的文件不存在: {file_path}")
            return None
        
        try:
            # 读取文件内容并base64编码
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # GitHub Gist需要base64编码
            content_base64 = base64.b64encode(file_content).decode('utf-8')
            
            # 准备Gist数据
            gist_data = {
                "description": description,
                "public": True,  # 公开Gist
                "files": {
                    file_path.name: {
                        "content": content_base64,
                        "encoding": "base64"
                    }
                }
            }
            
            # 上传到Gist
            response = requests.post(
                GIST_API,
                headers=self.headers,
                json=gist_data,
                timeout=30
            )
            
            if response.status_code == 201:
                gist_info = response.json()
                gist_id = gist_info.get('id')
                if gist_id:
                    # 构建原始文件下载链接
                    raw_url = f"https://gist.githubusercontent.com/raw/{gist_id}"
                    print(f"✓ 文件已上传到Gist: {gist_info.get('html_url')}")
                    return raw_url
            else:
                print(f"Gist上传失败: {response.status_code}")
                print(f"响应: {response.text[:200]}")
                return None
                
        except Exception as e:
            print(f"上传到Gist失败: {e}")
            return None
    
    def process_image(self, image_path: Path) -> Optional[str]:
        """处理图片并返回Gist下载链接"""
        print(f"处理图片: {image_path.name}")
        
        # 1. 检查服务
        if not self.check_service():
            print("错误: 图片解析服务不可用")
            return None
        
        # 2. 上传图片到解析服务
        print("上传图片到解析服务...")
        result = self.upload_image_to_service(image_path)
        if not result:
            return None
        
        print(f"✓ 图片解析成功: {result.get('success_count', 0)}个商品")
        
        # 3. 获取Excel文件名并下载
        excel_filename = result.get('report_file')
        if not excel_filename:
            print("错误: 未获取到Excel文件名")
            return None
        
        print(f"下载Excel文件: {excel_filename}")
        excel_file = self.download_excel_file(excel_filename)
        if not excel_file:
            return None
        
        print(f"✓ Excel文件已下载: {excel_file}")
        
        # 4. 上传到GitHub Gist
        print("上传到GitHub Gist...")
        gist_url = self.upload_to_gist(excel_file, f"Excel报表 - {image_path.name}")
        
        # 5. 清理临时文件
        try:
            os.unlink(excel_file)
        except:
            pass
        
        return gist_url
    
    def process_image_bytes(self, image_bytes: bytes, filename: str = "image.jpg") -> Optional[str]:
        """处理图片字节数据并返回Gist下载链接"""
        # 保存到临时文件
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="img_") as tmp:
            tmp.write(image_bytes)
            tmp_path = Path(tmp.name)
        
        try:
            result = self.process_image(tmp_path)
        finally:
            # 清理临时图片文件
            try:
                os.unlink(tmp_path)
            except:
                pass
        
        return result

def main():
    if len(sys.argv) < 2:
        print("用法: python image2gist.py <图片路径>")
        print("或者: python image2gist.py --bytes (从标准输入读取图片数据)")
        sys.exit(1)
    
    uploader = Image2ExcelGistUploader()
    
    if sys.argv[1] == "--bytes":
        # 从标准输入读取图片数据
        print("从标准输入读取图片数据...")
        image_bytes = sys.stdin.buffer.read()
        if not image_bytes:
            print("错误: 未读取到图片数据")
            sys.exit(1)
        
        gist_url = uploader.process_image_bytes(image_bytes, "uploaded_image.jpg")
    else:
        # 从文件路径读取
        image_path = Path(sys.argv[1])
        gist_url = uploader.process_image(image_path)
    
    if gist_url:
        print(f"\n✅ 处理完成!")
        print(f"📥 Excel下载链接: {gist_url}")
        print(f"🔗 链接有效期: 永久（除非手动删除）")
        
        # 复制到剪贴板（macOS）
        if sys.platform == 'darwin':
            import subprocess
            subprocess.run(['pbcopy'], input=gist_url.encode())
            print("📋 链接已复制到剪贴板")
    else:
        print("\n❌ 处理失败")
        sys.exit(1)

if __name__ == "__main__":
    main()