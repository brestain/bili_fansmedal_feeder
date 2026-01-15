import json
import os
import sys
from loguru import logger
import warnings
import asyncio
import aiohttp
import itertools
from src import BiliUser

log = logger.bind(user="B站粉丝勋章自动挂亲密度小助手")
__VERSION__ = "1.0.0"

warnings.filterwarnings(
    "ignore",
    message="The localize method is no longer necessary, as this time zone supports the fold attribute",
)


def _get_base_dir() -> str:
    """
    获取程序基目录（配置文件所在目录）.
    在 PyInstaller 打包后，返回 exe 文件所在目录；
    否则返回脚本所在目录。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的情况
        return os.path.dirname(sys.executable)
    else:
        # 开发环境
        return os.path.dirname(os.path.abspath(__file__))


base_dir = _get_base_dir()
os.chdir(base_dir)

try:
    if os.environ.get("USERS"):
        users = json.loads(os.environ.get("USERS"))
    else:
        import yaml
        config_path = os.path.join(base_dir, "users.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            users = yaml.load(f, Loader=yaml.FullLoader)
    config = {
        "VERBOSE_LOG": users.get("VERBOSE_LOG", 1),  # 默认1表示详细日志
    }
    # 根据 VERBOSE_LOG 配置设置日志级别
    verbose_log = config.get("VERBOSE_LOG", 1)
    log_level = "DEBUG" if verbose_log else "INFO"
    # 重新配置 logger，使用配置的日志级别
    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> <blue> {extra[user]} </blue> <level>{message}</level>",
        backtrace=True,
        diagnose=True,
        level=log_level,
    )
    log = logger.bind(user="B站粉丝勋章自动挂亲密度小助手")
except Exception as e:
    log.error(f"读取配置文件失败,请检查配置文件格式是否正确: {e}")
    exit(1)


def _add_user_file_logger(user_id: int, user_name: str):
    """
    为指定用户添加文件日志处理器
    日志文件名为 {用户ID}.log，追加模式，每次运行前添加两行换行
    """
    log_file = os.path.join(base_dir, f"{user_id}.log")
    
    # 如果文件已存在，先添加两行换行
    if os.path.exists(log_file):
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n\n")
    
    # 添加文件日志处理器，只记录该用户的日志（根据用户名过滤）
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} {extra[user]} {message}",
        level=log_level,
        encoding="utf-8",
        enqueue=True,  # 异步写入，避免阻塞
        filter=lambda record: record["extra"].get("user") == user_name,
    )


@log.catch
async def main():
    messageList = []
    session = aiohttp.ClientSession(trust_env=True)
    biliUsers = []  # 保存 BiliUser 对象引用
    initTasks = []
    startTasks = []
    catchMsg = []
    for user in users["USERS"]:
        if user["access_key"]:
            biliUser = BiliUser(
                user["access_key"],
                user.get("white_uid", ""),
                user.get("banned_uid", ""),
                config,
            )
            biliUsers.append(biliUser)  # 保存引用
            initTasks.append(biliUser.init())
            startTasks.append(biliUser.start())
            catchMsg.append(biliUser.sendmsg())
    try:
        # 先执行初始化任务
        await asyncio.gather(*initTasks)
        
        # 为每个成功登录的用户添加文件日志处理器
        for biliUser in biliUsers:
            if hasattr(biliUser, 'isLogin') and biliUser.isLogin and hasattr(biliUser, 'mid') and biliUser.mid and hasattr(biliUser, 'name') and biliUser.name:
                _add_user_file_logger(biliUser.mid, biliUser.name)
        
        await asyncio.gather(*startTasks)
    except Exception as e:
        log.exception(e)
        # messageList = messageList + list(itertools.chain.from_iterable(await asyncio.gather(*catchMsg)))
        messageList.append(f"任务执行失败: {e}")
    finally:
        messageList = messageList + list(
            itertools.chain.from_iterable(await asyncio.gather(*catchMsg))
        )
    [log.info(message) for message in messageList]
    await session.close()


def run(*args, **kwargs):
    loop = asyncio.new_event_loop()
    # main() 中的 watchinglive() 是无限循环，会一直运行
    loop.run_until_complete(main())
    # 正常情况下不会执行到这里，除非发生异常
    log.warning("任务意外退出。")


if __name__ == "__main__":
    log.info("启动守护模式，任务将持续运行。")
    # 由于 watchinglive() 是无限循环，任务会一直运行，不需要调度器
    # 直接运行一次即可，任务内部会持续执行
    run()
