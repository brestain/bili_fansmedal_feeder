#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili 登录工具 (终端版 - 修复 86039 错误)
通过二维码登录获取 access_key
"""

import hashlib
import json
import os
import time
import sys
import platform
from urllib.parse import urlencode, quote
from typing import Dict, Tuple, Optional

# 依赖检查
missing_deps = []
try:
    import requests
except ImportError:
    missing_deps.append("requests")
try:
    import qrcode
    from qrcode import QRCode
except ImportError:
    missing_deps.append("qrcode")

if missing_deps:
    print("错误: 缺少必要的库。请运行以下命令安装：")
    print(f"pip install {' '.join(missing_deps)}")
    exit(1)


# B站 API 密钥
APPKEY = "4409e2ce8ffd12b8"
APPSECRET = "59b43e04ad6965f34319062b478f83dd"


class BiliLogin:
    def __init__(self):
        self.access_key = ""
        self.csrf = ""
        self.cookies = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def _signature(self, params: Dict[str, str]) -> str:
        """生成签名"""
        params_with_appkey = params.copy()
        params_with_appkey["appkey"] = APPKEY
        sorted_keys = sorted(params_with_appkey.keys())
        query_parts = []
        for k in sorted_keys:
            encoded_value = quote(str(params_with_appkey[k]), safe='')
            query_parts.append(f"{k}={encoded_value}")
        
        query = "&".join(query_parts) + APPSECRET
        sign = hashlib.md5(query.encode('utf-8')).hexdigest()
        return sign

    def get_tv_qrcode_url_and_auth_code(self) -> Tuple[str, str]:
        """获取二维码 URL 和授权码"""
        api = "http://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
        data = {
            "local_id": "0",
            "ts": str(int(time.time()))
        }
        data_for_sign = data.copy()
        sign = self._signature(data_for_sign)
        data["appkey"] = APPKEY
        data["sign"] = sign

        try:
            response = self.session.post(
                api,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            result = response.json()
            if result.get("code") == 0:
                qrcode_url = result["data"]["url"]
                auth_code = result["data"]["auth_code"]
                return qrcode_url, auth_code
            else:
                raise Exception(f"获取二维码失败: {result}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求失败: {e}")

    def verify_login(self, auth_code: str) -> bool:
        """轮询验证登录状态"""
        api = "http://passport.bilibili.com/x/passport-tv-login/qrcode/poll"
        print("\n等待扫码登录...")
        
        while True:
            data = {
                "auth_code": auth_code,
                "local_id": "0",
                "ts": str(int(time.time()))
            }
            data_for_sign = data.copy()
            sign = self._signature(data_for_sign)
            data["appkey"] = APPKEY
            data["sign"] = sign
            
            try:
                response = self.session.post(
                    api,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                result = response.json()
                code = result.get("code", -1)
                
                if code == 0:
                    # --- 登录成功 ---
                    self.access_key = result["data"].get("access_token", "")
                    if "cookie_info" in result["data"]:
                        cookies_info = result["data"]["cookie_info"].get("cookies", [])
                        for cookie in cookies_info:
                            name = cookie.get("name", "")
                            value = cookie.get("value", "")
                            self.cookies[name] = value
                            if name == "bili_jct":
                                self.csrf = value
                    print("\n✅ 登录成功！")
                    self._save_login_info(result["data"])
                    return True
                
                elif code == 86101:
                    # --- 等待扫码 ---
                    # 保持静默或打点，避免刷屏
                    time.sleep(2)
                
                elif code == 86090:
                    # --- 已扫码，等待确认 ---
                    print("⚡ 二维码已扫描，请在手机上点击确认...", end="\r")
                    time.sleep(2)

                elif code == 86039:
                    # --- 【修复点】 尚未确认 (与 86090 类似) ---
                    # 有时候 API 会返回这个码，表示需要继续等待
                    print("⚡ 请在手机上点击确认登录... (86039)", end="\r")
                    time.sleep(2)

                elif code == 86038:
                    print("\n❌ 二维码已过期，请重新运行脚本。")
                    return False

                else:
                    # --- 其他真正的错误 ---
                    error_msg = result.get("message", "未知错误")
                    print(f"\n❌ 登录失败: {error_msg} (code: {code})")
                    return False

            except Exception as e:
                print(f"\n❌ 请求错误: {e}")
                time.sleep(3)

    def _save_login_info(self, data: dict):
        """保存登录信息到文件"""
        if self.access_key:
            with open("access_key.txt", "w", encoding="utf-8") as f:
                f.write(self.access_key)
            print(f"access_key 已保存到 access_key.txt")
        
        login_data = {
            "code": 0,
            "data": data,
            "ts": int(time.time())
        }
        with open("login_info.json", "w", encoding="utf-8") as f:
            json.dump(login_data, f, ensure_ascii=False, indent=2)

    def is_login(self) -> Tuple[bool, str]:
        """验证当前登录状态"""
        api = "https://api.bilibili.com/x/web-interface/nav"
        try:
            response = self.session.get(api, cookies=self.cookies)
            result = response.json()
            if result.get("code") == 0:
                if result.get("data", {}).get("isLogin"):
                    uname = result.get("data", {}).get("uname", "用户")
                    return True, uname
            return False, ""
        except Exception:
            return False, ""

    def load_login_info(self) -> bool:
        """从文件加载登录信息"""
        filename = "login_info.json"
        if not os.path.exists(filename):
            return False
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            saved_ts = data.get("ts", 0)
            if int(time.time()) - saved_ts > 30 * 24 * 60 * 60:
               return False

            self.access_key = data.get("data", {}).get("access_token", "")
            cookies_info = data.get("data", {}).get("cookie_info", {}).get("cookies", [])
            for cookie in cookies_info:
                name = cookie.get("name", "")
                value = cookie.get("value", "")
                self.cookies[name] = value
                if name == "bili_jct":
                    self.csrf = value
            return True
        except Exception:
            return False

    def show_qrcode(self, url: str):
        """仅在终端打印二维码"""
        qr = QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1, 
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        print("\n" + "=" * 40)
        print(f"登录链接: {url}")
        print("=" * 40)
        print("\n")

        try:
            if sys.stdout.isatty():
                qr.print_tty() 
            else:
                raise Exception("非 TTY 环境")
        except Exception:
             qr.print_ascii(invert=True)
        print("\n")

    def login(self):
        """主登录流程"""
        if self.load_login_info():
            is_valid, name = self.is_login()
            if is_valid:
                print(f"✅ 已登录: {name}")
                print(f"access_key: {self.access_key}")
                return

        self.login_bili()

    def login_bili(self):
        """执行二维码登录"""
        print("\n" + "!" * 50)
        print("【请注意】")
        print("由于终端字体和行高限制，二维码可能显示不全或变形。")
        print(">>> 请务必全屏/最大化当前终端窗口 <<<")
        print("!" * 50 + "\n")
        
        input("准备好后，请按回车键生成二维码...")
        
        try:
            login_url, auth_code = self.get_tv_qrcode_url_and_auth_code()
            self.show_qrcode(login_url)
            self.verify_login(auth_code)
            
        except KeyboardInterrupt:
            print("\n\n用户取消登录")
        except Exception as e:
            print(f"\n❌ 登录过程出错: {e}")


def main():
    if platform.system() == 'Windows':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except:
            pass

    print("=" * 50)
    print("Bilibili 登录工具 (修复版)")
    print("=" * 50)
    
    login_tool = BiliLogin()
    login_tool.login()
    
    print("\n按回车键退出...")
    input()


if __name__ == "__main__":
    main()