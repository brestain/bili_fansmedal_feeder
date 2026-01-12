import asyncio
from hashlib import md5
import hashlib
import os
import random
import sys
import time
import json
import re
from typing import Union
from loguru import logger
from urllib.parse import urlencode, urlparse


from aiohttp import ClientSession

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Crypto:
    APPKEY = "4409e2ce8ffd12b8"
    APPSECRET = "59b43e04ad6965f34319062b478f83dd"

    @staticmethod
    def md5(data: Union[str, bytes]) -> str:
        """generates md5 hex dump of `str` or `bytes`"""
        if type(data) == str:
            return md5(data.encode()).hexdigest()
        return md5(data).hexdigest()

    @staticmethod
    def sign(data: Union[str, dict]) -> str:
        """salted sign funtion for `dict`(converts to qs then parse) & `str`"""
        if isinstance(data, dict):
            _str = urlencode(data)
        elif type(data) != str:
            raise TypeError
        return Crypto.md5(_str + Crypto.APPSECRET)


class SingableDict(dict):
    @property
    def sorted(self):
        """returns a alphabetically sorted version of `self`"""
        return dict(sorted(self.items()))

    @property
    def signed(self):
        """returns our sorted self with calculated `sign` as a new key-value pair at the end"""
        _sorted = self.sorted
        return {**_sorted, "sign": Crypto.sign(_sorted)}


def retry(tries=3, interval=1):
    def decorate(func):
        async def wrapper(*args, **kwargs):
            count = 0
            func.isRetryable = False
            log = logger.bind(user=f"{args[0].u.name}")
            while True:
                try:
                    result = await func(*args, **kwargs)
                except Exception as e:
                    count += 1
                    if type(e) == BiliApiError:
                        if e.code == 1011040:
                            raise e
                        elif e.code == 10030:
                            await asyncio.sleep(10)
                        elif e.code == -504:
                            pass
                        else:
                            raise e
                    if count > tries:
                        log.error(f"API {urlparse(args[1]).path} 调用出现异常: {str(e)}")
                        raise e
                    else:
                        # log.error(f"API {urlparse(args[1]).path} 调用出现异常: {str(e)}，重试中，第{count}次重试")
                        await asyncio.sleep(interval)
                    func.isRetryable = True
                else:
                    if func.isRetryable:
                        pass
                        # log.success(f"重试成功")
                    return result

        return wrapper

    return decorate


def client_sign(data: dict):
    _str = json.dumps(data, separators=(",", ":"))
    for n in ["sha512", "sha3_512", "sha384", "sha3_384", "blake2b"]:
        _str = hashlib.new(n, _str.encode("utf-8")).hexdigest()
    return _str


def randomString(length: int = 16) -> str:
    return "".join(
        random.sample("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", length)
    )


class BiliApiError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg

    def __str__(self):
        return self.msg


class BiliApi:
    headers = {
        "User-Agent": "Mozilla/5.0 BiliDroid/6.73.1 (bbcallen@gmail.com) os/android model/Mi 10 Pro mobi_app/android build/6731100 channel/xiaomi innerVer/6731110 osVer/12 network/2",
    }
    from .user import BiliUser

    def __init__(self, u: BiliUser, s: ClientSession):
        self.u = u
        self.session = s

    def __check_response(self, resp: dict) -> dict:
        if resp["code"] != 0 or ("mode_info" in resp["data"] and resp["message"] != ""):
            raise BiliApiError(resp["code"], resp["message"])
        return resp["data"]

    @retry()
    async def __get(self, *args, **kwargs):
        async with self.session.get(*args, **kwargs) as resp:
            return self.__check_response(await resp.json())

    @retry()
    async def __post(self, *args, **kwargs):
        async with self.session.post(*args, **kwargs) as resp:
            return self.__check_response(await resp.json())

    async def getFansMedalandRoomID(self, verbose: bool = False) -> dict:
        """
        使用 MedalWall 接口获取粉丝牌信息
        """
        url = "https://api.live.bilibili.com/xlive/web-ucenter/user/MedalWall"
        # 使用 app 端认证方式（带签名）
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
            "target_id": self.u.mid,
        }
        log = logger.bind(user=self.u.name if hasattr(self.u, 'name') else 'Unknown')
        if verbose:
            log.debug("[粉丝牌API] 调用 MedalWall (使用 app 端签名认证)")

        # 使用 SingableDict 自动添加签名
        async with self.session.get(url, params=SingableDict(params).signed, headers=self.headers) as resp:
            resp_data = await resp.json()
            if resp_data.get("code") != 0:
                error_msg = resp_data.get("message", "未知错误")
                error_code = resp_data.get("code", -1)
                log.error(f"[粉丝牌API] MedalWall 接口失败: code={error_code}, message={error_msg}")
                raise BiliApiError(error_code, error_msg)

            data = resp_data.get("data", {})
            medal_list = data.get("list", [])

            for item in medal_list:
                medal_info = item.get("medal_info", {})
                target_id = medal_info.get("target_id", 0)
                link = item.get("link", "")
                room_id = self.extractRoomIdFromLink(link)
                converted_item = {
                    "medal": {
                        "target_id": target_id,
                        "level": medal_info.get("level", 0),
                        "medal_name": medal_info.get("medal_name", ""),
                        "today_feed": medal_info.get("today_feed", 0),
                        "intimacy": medal_info.get("intimacy", 0),
                        "next_intimacy": medal_info.get("next_intimacy", 0),
                    },
                    "anchor_info": {
                        "nick_name": item.get("target_name", "未知"),
                        "face": item.get("target_icon", ""),
                    },
                    "room_info": {
                        "room_id": room_id,
                    },
                    "live_status": item.get("live_status", 0),
                }
                yield converted_item



    async def likeInteractV3(self, room_id: int, up_id: int, self_uid: int):
        url = "https://api.live.bilibili.com/xlive/app-ucenter/v1/like_info_v3/like/likeReportV3"
        data = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "click_time": 1,
            "room_id": room_id,
            "anchor_id": up_id,
            "uid": up_id,
        }
        self.headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
            }
        ),
        # for _ in range(3):
        await self.__post(url, data=SingableDict(data).signed, headers=self.headers)

    async def shareRoom(self, room_id: int):
        """
        分享直播间
        """
        url = "https://api.live.bilibili.com/xlive/app-room/v1/index/TrigerInteract"
        data = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
            "interact_type": 3,
            "roomid": room_id,
        }
        self.headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
            }
        ),
        await self.__post(url, data=SingableDict(data).signed, headers=self.headers)

    async def sendDanmaku(self, room_id: int) -> str:
        """
        发送弹幕
        """
        url = "https://api.live.bilibili.com/xlive/app-room/v1/dM/sendmsg"
        danmakus = [
            "(⌒▽⌒).",
            "（￣▽￣）.",
            "(=・ω・=).",
            "(｀・ω・´).",
            "(〜￣△￣)〜.",
            "(･∀･).",
            "(°∀°)ﾉ.",
            "(￣3￣).",
            "╮(￣▽￣)╭.",
            "_(:3」∠)_.",
            "(^・ω・^ ).",
            "(●￣(ｴ)￣●).",
            "ε=ε=(ノ≧∇≦)ノ.",
            "⁄(⁄ ⁄•⁄ω⁄•⁄ ⁄)⁄.",
            "←◡←.",
        ]
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
        }
        data = {
            "cid": room_id,
            "msg": random.choice(danmakus),
            "rnd": int(time.time()),
            "color": "16777215",
            "fontsize": "25",
        }
        self.headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
            }
        ),
        resp = await self.__post(
            url, params=SingableDict(params).signed, data=data, headers=self.headers
        )
        return json.loads(resp["mode_info"]["extra"])["content"]

    async def loginVerift(self):
        """
        登录验证
        """
        url = "https://app.bilibili.com/x/v2/account/mine"
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
        }
        return await self.__get(url, params=SingableDict(params).signed, headers=self.headers)

    async def doSign(self):
        """
        直播区签到
        """
        url = "https://api.live.bilibili.com/rc/v1/Sign/doSign"
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
        }
        return await self.__get(url, params=SingableDict(params).signed, headers=self.headers)

    async def getUserInfo(self):
        """
        用户直播等级
        """
        url = "https://api.live.bilibili.com/xlive/app-ucenter/v1/user/get_user_info"
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
        }
        return await self.__get(url, params=SingableDict(params).signed, headers=self.headers)

    async def getMedalsInfoByUid(self, uid: int):
        """
        用户勋章信息
        """
        url = "https://api.live.bilibili.com/xlive/app-ucenter/v1/fansMedal/fans_medal_info"
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
            "target_id": uid,
        }
        return await self.__get(url, params=SingableDict(params).signed, headers=self.headers)

    async def getUserMedalInfo(self, uid: int, up_uid: int):
        """
        获取用户粉丝牌点亮状态
        :param uid: 用户UID
        :param up_uid: UP主UID
        :return: 返回data中的curr_show的is_light字段，1表示已点亮，0表示未点亮
        """
        url = "https://api.live.bilibili.com/xlive/app-ucenter/v1/fansMedal/user_medal_info"
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
            "uid": uid,
            "up_uid": up_uid,
        }
        return await self.__get(url, params=SingableDict(params).signed, headers=self.headers)

    async def entryRoom(self, room_id: int, up_id: int):
        """
        进入直播间（首次进入时需要调用）
        """
        url = "https://live-trace.bilibili.com/xlive/data-interface/v1/heartbeat/mobileEntry"
        current_time = int(time.time())
        timestamp = current_time - 60  # 开始观看时间戳，当前时间减去60秒
        
        data = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": current_time,
            "platform": "android",
            "uuid": self.u.uuids[0],
            "buvid": randomString(37).upper(),
            "seq_id": "1",
            "room_id": f"{room_id}",
            "parent_id": "6",
            "area_id": "283",
            "timestamp": f"{timestamp}",
            "secret_key": "axoaadsffcazxksectbbb",
            "watch_time": "60",
            "up_id": f"{up_id}",
            "up_level": "40",
            "jump_from": "30000",
            "gu_id": randomString(43).lower(),
            "visit_id": randomString(32).lower(),
            "click_id": self.u.uuids[1],
            "heart_beat": "[]",
            "client_ts": f"{current_time}",
        }
        self.headers.update({
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            result = await self.__post(url, data=SingableDict(data).signed, headers=self.headers)
            log = logger.bind(user=self.u.name if hasattr(self.u, 'name') else 'Unknown')
            log.debug(f"[entryRoom] 进入直播间响应: {result}")
            return result
        except Exception as e:
            log = logger.bind(user=self.u.name if hasattr(self.u, 'name') else 'Unknown')
            log.error(f"[entryRoom] 进入直播间失败: {e}")
            raise

    async def heartbeat(
        self,
        room_id: int,
        up_id: int,
        watch_time: int = 60,
        start_timestamp: int = None,
        seq_id: int = 1,
    ):
        """
        发送心跳包
        :param room_id: 直播间ID
        :param up_id: UP主ID
        :param watch_time: 观看时长（秒），默认60秒
        :param start_timestamp: 开始观看的时间戳，如果为None则使用当前时间减去watch_time
        :param seq_id: 心跳序号，从1开始递增
        """
        url = "https://live-trace.bilibili.com/xlive/data-interface/v1/heartbeat/mobileHeartBeat"
        current_time = int(time.time())
        
        # 优先使用传入的 start_timestamp，确保时间戳连续
        # 如果传入了 start_timestamp，直接使用它（调用方已经确保 timestamp + watch_time = current_time）
        if start_timestamp is not None:
            timestamp = start_timestamp
            # 确保时间戳不会超过当前时间（B站可能不接受未来的时间戳）
            if timestamp > current_time:
                timestamp = current_time - watch_time
            # 确保 timestamp + watch_time 不超过当前时间太多（服务器时间检查）
            if timestamp + watch_time > current_time + 5:  # 允许5秒误差
                timestamp = current_time - watch_time
        else:
            # 如果没有传入 start_timestamp，使用当前时间减去watch_time（向后兼容）
            timestamp = current_time - watch_time
        
        # 记录调试信息（不含敏感字段）
        debug_info = {
            "room_id": room_id,
            "up_id": up_id,
            "seq_id": seq_id,
            "watch_time": watch_time,
            "timestamp": timestamp,
            "now": current_time,
            "drift": current_time - timestamp,
        }

        data = {
            "platform": "android",
            "uuid": self.u.uuids[0],
            "buvid": randomString(37).upper(),
            "seq_id": f"{seq_id}",
            "room_id": f"{room_id}",
            "parent_id": "6",
            "area_id": "283",
            "timestamp": f"{timestamp}",
            "secret_key": "axoaadsffcazxksectbbb",
            "watch_time": f"{watch_time}",
            "up_id": f"{up_id}",
            "up_level": "40",
            "jump_from": "30000",
            "gu_id": randomString(43).lower(),
            "play_type": "0",
            "play_url": "",
            "s_time": "0",
            "data_behavior_id": "",
            "data_source_id": "",
            "up_session": f"l:one:live:record:{room_id}:{timestamp}",
            "visit_id": randomString(32).lower(),
            "watch_status": "%7B%22pk_id%22%3A0%2C%22screen_status%22%3A1%7D",
            "click_id": self.u.uuids[1],
            "session_id": "",
            "player_type": "0",
            "client_ts": f"{current_time}",
        }
        data.update(
            {
                "client_sign": client_sign(data),
                "access_key": self.u.access_key,
                "actionKey": "appkey",
                "appkey": Crypto.APPKEY,
                "ts": int(time.time()),
            }
        )
        self.headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
            }
        ),
        try:
            result = await self.__post(url, data=SingableDict(data).signed, headers=self.headers)
            # 记录心跳包响应（用于调试）
            log = logger.bind(user=self.u.name if hasattr(self.u, 'name') else 'Unknown')
            log.debug(f"[heartbeat] 心跳#{seq_id} 响应: {result}")
            return result
        except Exception as e:
            log = logger.bind(user=self.u.name if hasattr(self.u, 'name') else 'Unknown')
            log.error(f"[heartbeat] 请求失败: {e} | ctx={debug_info}")
            raise

    async def wearMedal(self, medal_id: int):
        """
        佩戴粉丝牌
        """
        url = "https://api.live.bilibili.com/xlive/app-ucenter/v1/fansMedal/wear"
        data = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
            "medal_id": medal_id,
            "platform": "android",
            "type": "1",
            "version": "0",
        }
        self.headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
            }
        ),
        return await self.__post(url, data=SingableDict(data).signed, headers=self.headers)

    async def getGroups(self):
        url = "https://api.vc.bilibili.com/link_group/v1/member/my_groups?build=0&mobi_app=web"
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
        }
        res = await self.__get(url, params=SingableDict(params).signed, headers=self.headers)
        list = res["list"] if "list" in res else []
        for group in list:
            yield group

    async def signInGroups(self, group_id: int, owner_id: int):
        url = "https://api.vc.bilibili.com/link_setting/v1/link_setting/sign_in"
        params = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
            "group_id": group_id,
            "owner_id": owner_id,
        }
        return await self.__get(url, params=SingableDict(params).signed, headers=self.headers)

    async def getOneBattery(self):
        url = "https://api.live.bilibili.com/xlive/app-ucenter/v1/userTask/UserTaskReceiveRewards"
        data = {
            "access_key": self.u.access_key,
            "actionKey": "appkey",
            "appkey": Crypto.APPKEY,
            "ts": int(time.time()),
        }
        return await self.__post(url, data=SingableDict(data).signed, headers=self.headers)

    def extractRoomIdFromLink(self, link: str) -> int:
        """
        从 link 字段中提取直播间 room_id
        link 格式可能是: https://live.bilibili.com/21013446?xxx 或 https://space.bilibili.com/3117538?xxx
        """
        if not link:
            return 0
        
        # 取第一个 "?" 之前的内容
        base_link = link.split('?')[0]
        
        # 尝试从 live.bilibili.com 链接中提取 room_id
        match = re.search(r'live\.bilibili\.com/(\d+)', base_link)
        if match:
            return int(match.group(1))
        
        # 如果不是直播间链接，返回0（需要后续通过其他方式获取）
        return 0

    async def getRoomIdByUid(self, uid: int) -> int:
        """
        通过用户UID获取直播间room_id（备用方法，优先使用 extractRoomIdFromLink）
        """
        try:
            # 方法1: 通过用户空间信息获取
            url = f"https://api.bilibili.com/x/space/acc/info?mid={uid}"
            web_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"https://space.bilibili.com/{uid}",
            }
            async with self.session.get(url, headers=web_headers) as resp:
                resp_data = await resp.json()
                if resp_data.get("code") == 0:
                    data = resp_data.get("data", {})
                    live_room = data.get("live_room", {})
                    room_id = live_room.get("roomid", 0)
                    if room_id:
                        return room_id
        except Exception as e:
            log = logger.bind(user=self.u.name if hasattr(self.u, 'name') else 'Unknown')
            log.debug(f"通过UID {uid} 获取room_id失败: {e}")
        
        # 如果方法1失败，返回0
        return 0

    async def getRoomInfo(self, room_id: int):
        """
        获取直播间信息
        统一返回格式: {"room_info": {"room_id": int, "live_status": int, "title": str}}
        """
        log = logger.bind(user=self.u.name if hasattr(self.u, 'name') else 'Unknown')
        
        try:
            url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
            
            web_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"https://live.bilibili.com/{room_id}",
            }
            
            async with self.session.get(url, headers=web_headers) as resp:
                resp_data = await resp.json()
                
                if resp_data.get("code") == 0:
                    data = resp_data.get("data", {})
                    return {
                        "room_info": {
                            "room_id": data.get("room_id"),
                            "live_status": data.get("live_status", 0),
                            "title": data.get("title", ""),
                        }
                    }
                else:
                    error_code = resp_data.get('code')
                    error_msg = resp_data.get('message', '')
                    log.warning(f"获取直播间 {room_id} 信息失败: code={error_code}, message={error_msg}")
                    return None
        except Exception as e:
            log.error(f"获取直播间 {room_id} 信息异常: {e}")
            return None
