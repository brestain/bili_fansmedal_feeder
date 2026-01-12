import json
import os
import sys
from loguru import logger
import warnings
import asyncio
import aiohttp
import itertools
from src import BiliUser

log = logger.bind(user="B站粉丝牌助手")
__VERSION__ = "0.3.8"

warnings.filterwarnings(
    "ignore",
    message="The localize method is no longer necessary, as this time zone supports the fold attribute",
)
os.chdir(os.path.dirname(os.path.abspath(__file__)).split(__file__)[0])

try:
    if os.environ.get("USERS"):
        users = json.loads(os.environ.get("USERS"))
    else:
        import yaml

        with open("users.yaml", "r", encoding="utf-8") as f:
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
    log = logger.bind(user="B站粉丝牌助手")
except Exception as e:
    log.error(f"读取配置文件失败,请检查配置文件格式是否正确: {e}")
    exit(1)


@log.catch
async def main():
    messageList = []
    session = aiohttp.ClientSession(trust_env=True)
    try:
        log.warning("当前版本为: " + __VERSION__)
        resp = await (
            await session.get(
                "http://version.fansmedalhelper.1961584514352337.cn-hangzhou.fc.devsapp.net/"
            )
        ).json()
        if resp["version"] != __VERSION__:
            log.warning("新版本为: " + resp["version"] + ",请更新")
            log.warning("更新内容: " + resp["changelog"])
            messageList.append(f"当前版本: {__VERSION__} ,最新版本: {resp['version']}")
            messageList.append(f"更新内容: {resp['changelog']} ")
        if resp["notice"]:
            log.warning("公告: " + resp["notice"])
            messageList.append(f"公告: {resp['notice']}")
    except Exception as ex:
        messageList.append(f"检查版本失败，{ex}")
        log.warning(f"检查版本失败，{ex}")
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
            initTasks.append(biliUser.init())
            startTasks.append(biliUser.start())
            catchMsg.append(biliUser.sendmsg())
    try:
        await asyncio.gather(*initTasks)
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
