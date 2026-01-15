"""
打包脚本 - 使用 PyInstaller 打包 generate_fansmedal_weight.py 和 main.py
"""
import os
import sys
import shutil
import subprocess

def check_pyinstaller():
    """检查是否安装了 PyInstaller"""
    try:
        import PyInstaller  # type: ignore
        print("✓ PyInstaller 已安装")
        return True
    except ImportError:
        print("✗ PyInstaller 未安装")
        print("正在安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller 安装完成")
        return True

def build_executable(script_name, name, icon=None):
    """构建单个可执行文件"""
    print(f"\n{'='*60}")
    print(f"正在打包: {script_name} -> {name}.exe")
    print(f"{'='*60}")
    
    cmd = [
        "pyinstaller",
        "--onefile",  # 打包成单个文件
        "--console",  # 控制台应用
        "--name", name,
        "--clean",  # 清理临时文件
        "--noconfirm",  # 不询问覆盖
    ]
    
    # 添加图标（如果存在）
    if icon and os.path.exists(icon):
        cmd.extend(["--icon", icon])
        print(f"使用图标: {icon}")
    
    # 添加隐藏导入（可能需要）
    hidden_imports = [
        "yaml",
        "loguru",
        "aiohttp",
        "aiohttp_socks",
        "requests",
        "qrcode",
        "PIL",
    ]
    
    # 如果是 login.py，添加额外的依赖
    if "login" in script_name.lower():
        hidden_imports.extend([
            "ctypes",
            "platform",
        ])
    
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])
    
    # 添加数据文件（如果需要）
    # cmd.extend(["--add-data", "users.yaml.example;."])
    
    # 添加脚本路径
    cmd.append(script_name)
    
    print(f"执行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✓ {name}.exe 打包成功！")
        print(f"  输出位置: dist/{name}.exe")
        return True
    else:
        print(f"✗ {name}.exe 打包失败！")
        print("错误信息:")
        print(result.stderr)
        return False

def main():
    """主函数"""
    print("="*60)
    print("B站粉丝勋章工具 - 打包脚本")
    print("="*60)
    
    # 检查 PyInstaller
    if not check_pyinstaller():
        print("无法继续，请手动安装 PyInstaller: pip install pyinstaller")
        return
    
    # 检查源文件是否存在
    scripts = [
        ("generate_fansmedal_weight.py", "generate_fansmedal_weight"),
        ("main.py", "main"),
        ("logintool/login.py", "login"),
    ]
    
    for script, name in scripts:
        if not os.path.exists(script):
            print(f"✗ 错误: 找不到文件 {script}")
            return
    
    # 检查图标文件
    icon = "bili_fansmedal_feeder_icon.png"
    if not os.path.exists(icon):
        icon = None
        print("⚠ 未找到图标文件，将使用默认图标")
    
    # 清理之前的构建文件
    if os.path.exists("dist"):
        print("\n清理旧的构建文件...")
        shutil.rmtree("dist", ignore_errors=True)
    if os.path.exists("build"):
        shutil.rmtree("build", ignore_errors=True)
    
    # 打包每个脚本
    success_count = 0
    for script, name in scripts:
        if build_executable(script, name, icon):
            success_count += 1
    
    # 总结
    print(f"\n{'='*60}")
    print("打包完成！")
    print(f"{'='*60}")
    print(f"成功打包: {success_count}/{len(scripts)} 个文件")
    
    if success_count == len(scripts):
        print("\n✓ 所有文件打包成功！")
        print("\n可执行文件位置:")
        for _, name in scripts:
            exe_path = f"dist/{name}.exe"
            if os.path.exists(exe_path):
                size = os.path.getsize(exe_path) / (1024 * 1024)  # MB
                print(f"  - {exe_path} ({size:.2f} MB)")
        
        print("\n⚠ 重要提示:")
        print("1. 打包后的 .exe 文件需要与以下文件放在同一目录:")
        print("   - users.yaml (配置文件)")
        print("   - users.yaml.example (示例配置文件)")
        print("   - fansmedal_weight.yaml (权重配置文件，可选)")
        print("\n2. 使用说明:")
        print("   - login.exe: 用于获取 access_key（首次使用或 access_key 过期时）")
        print("   - generate_fansmedal_weight.exe: 生成粉丝牌权重配置文件")
        print("   - main.exe: 运行主程序（自动观看直播）")
        print("\n3. 首次使用前，请确保:")
        print("   - 运行 login.exe 获取 access_key")
        print("   - 配置 users.yaml（将 access_key 填入）")
        print("   - 运行 generate_fansmedal_weight.exe 生成权重配置")
        print("\n4. 如果遇到问题，可以:")
        print("   - 在命令行中运行 .exe 查看错误信息")
        print("   - 检查是否缺少必要的配置文件")
    else:
        print("\n✗ 部分文件打包失败，请检查错误信息")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断打包")
    except Exception as e:
        print(f"\n✗ 打包过程出错: {e}")
        import traceback
        traceback.print_exc()

