from aiohttp import ClientSession, ClientTimeout
import sys
import os
import asyncio
import uuid
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, Any

import yaml

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 读取配置文件，根据 VERBOSE_LOG 设置日志级别
def _get_log_level_from_config():
    """从配置文件读取 VERBOSE_LOG，返回对应的日志级别"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "users.yaml")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.load(f, Loader=yaml.FullLoader) or {}
                verbose_log = config.get("VERBOSE_LOG", 1)
                return "DEBUG" if verbose_log else "INFO"
    except Exception:
        pass  # 如果读取失败，使用默认值
    # 默认返回 INFO，避免打印过多日志
    return "INFO"

logger.remove()
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> <blue> {extra[user]} </blue> <level>{message}</level>",
    backtrace=True,
    diagnose=True,
    level=_get_log_level_from_config(),  # 根据 VERBOSE_LOG 配置动态设置
)


class BiliUser:
    def __init__(self, access_token: str, whiteUIDs: str = '', bannedUIDs: str = '', config: dict = {}):
        from .api import BiliApi

        self.mid, self.name = 0, ""
        self.access_key = access_token
        try:
            self.whiteList = list(map(lambda x: int(x if x else 0), str(whiteUIDs).split(',')))
            self.bannedList = list(map(lambda x: int(x if x else 0), str(bannedUIDs).split(',')))
        except ValueError:
            raise ValueError("白名单或黑名单格式错误")
        self.config = config
        self.medals = []
        self.medalsNeedDo = []

        self.session = ClientSession(timeout=ClientTimeout(total=3), trust_env = True)
        self.api = BiliApi(self, self.session)

        self.message = []
        self.errmsg = ["错误日志："]
        self.uuids = [str(uuid.uuid4()) for _ in range(2)]

        self.verbose_log = bool(config.get("VERBOSE_LOG", 1))
        self.fansmedal_weights: Dict[str, Any] = self._load_fansmedal_weights()

    def _load_fansmedal_weights(self) -> Dict[str, Any]:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        weight_path = os.path.join(base_dir, "fansmedal_weight.yaml")
        if not os.path.exists(weight_path):
            return {}
        try:
            with open(weight_path, "r", encoding="utf-8") as f:
                data = yaml.load(f, Loader=yaml.FullLoader) or {}
                if not isinstance(data, dict):
                    return {}
                return data
        except Exception as e:
            # 读取失败时不影响主流程, 只打日志
            logger.bind(user="粉丝牌权重").warning(f"读取 fansmedal_weight.yaml 失败: {e}")
            return {}

    def _get_medal_weight(self, medal: dict) -> int:
        medal_info = medal.get("medal", {}) or {}
        target_id = medal_info.get("target_id", 0) or 0
        key_str = str(target_id)
        cfg = self.fansmedal_weights.get(key_str) or {}
        try:
            weight = int(cfg.get("weight", 100))
        except (TypeError, ValueError):
            weight = 100
        return weight

    def _format_watch_time(self, total_seconds: int) -> str:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}分钟{seconds}秒"

    async def loginVerify(self) -> bool:
        loginInfo = await self.api.loginVerift()
        self.mid, self.name = loginInfo['mid'], loginInfo['name']
        self.log = logger.bind(user=self.name)
        if loginInfo['mid'] == 0:
            self.isLogin = False
            return False
        userInfo = await self.api.getUserInfo()
        if userInfo['medal']:
            medalInfo = await self.api.getMedalsInfoByUid(userInfo['medal']['target_id'])
            if medalInfo['has_fans_medal']:
                self.initialMedal = medalInfo['my_fans_medal']
        self.log.log("SUCCESS", str(loginInfo['mid']) + " 登录成功")
        self.isLogin = True
        return True


    async def getMedals(self, verbose: bool = True, show_details: bool = True):
        self.medals.clear()
        self.medalsNeedDo.clear()
        
        if verbose and show_details:
            self.log.info("=" * 60)
            self.log.info("开始获取粉丝牌列表...")
        
        # 获取所有粉丝牌
        medal_count = 0
        skipped_blacklist = 0  # 黑名单跳过计数
        skipped_whitelist = 0  # 白名单跳过计数
        async for medal in self.api.getFansMedalandRoomID(verbose=verbose and show_details):
            medal_count += 1
            anchor_name = medal.get('anchor_info', {}).get('nick_name', '未知')
            medal_info = medal.get('medal', {})
            room_info = medal.get('room_info', {})
            
            level = medal_info.get('level', 0)
            today_feed = medal_info.get('today_feed', 0)
            target_id = medal_info.get('target_id', 0)
            room_id = room_info.get('room_id', 0)
            
            if verbose and show_details:
                self.log.info(f"[粉丝牌 #{medal_count}] {anchor_name}")
                self.log.info(f"  - 等级: {level}")
                self.log.info(f"  - 今日亲密度: {today_feed}/30")
                self.log.info(f"  - 房间ID: {room_id}")
                self.log.info(f"  - 用户ID: {target_id}")
            
            if self.whiteList == [0]:
                if target_id in self.bannedList:
                    skipped_blacklist += 1
                    if verbose and show_details:
                        self.log.warning(f"  - 状态: 在黑名单中，已过滤")
                    continue
                self.medals.append(medal)
                if verbose and show_details:
                    self.log.info(f"  - 状态: 已加入待筛选列表")
            else:
                if target_id in self.whiteList:
                    self.medals.append(medal)
                    if verbose and show_details:
                        self.log.success(f"  - 状态: 在白名单中，已加入待筛选列表")
                else:
                    skipped_whitelist += 1
                    if verbose and show_details:
                        self.log.warning(f"  - 状态: 不在白名单中，跳过")
        
        if verbose and show_details:
            self.log.info(f"共获取到 {medal_count} 个粉丝牌，其中 {len(self.medals)} 个进入筛选流程")
            self.log.info("=" * 60)
            self.log.info("开始检查直播间开播状态...")
        
        # 筛选正在开播且今日亲密度 < 30 的直播间
        checked_count = 0
        skipped_intimacy = 0
        skipped_not_live = 0
        skipped_no_room = 0
        added_count = 0
        
        for medal in self.medals:
            checked_count += 1
            anchor_name = medal.get('anchor_info', {}).get('nick_name', '未知')
            medal_info = medal.get('medal', {})
            room_info = medal.get('room_info', {})
            
            level = medal_info.get('level', 0)
            today_feed = medal_info.get('today_feed', 0)
            target_id = medal_info.get('target_id', 0)
            room_id = room_info.get('room_id', 0)
            live_status = medal.get('live_status', 0)  # 直接使用新接口返回的 live_status
            
            if verbose and show_details:
                self.log.info(f"[检查 #{checked_count}/{len(self.medals)}] {anchor_name} (等级{level}, UID{target_id})")
                self.log.info(f"  - 今日亲密度: {today_feed}")
                self.log.info(f"  - 开播状态: {live_status} (1=正在直播, 0=未开播)")
                self.log.info(f"  - 房间ID: {room_id if room_id > 0 else '未获取'}")
            
            # 检查亲密度
            if today_feed >= 30:
                skipped_intimacy += 1
                if verbose and show_details:
                    self.log.warning(f"  - 结果: 亲密度已满30，跳过")
                continue
            
            # 检查直播间是否正在开播（使用新接口返回的 live_status）
            if live_status != 1:
                skipped_not_live += 1
                if verbose and show_details:
                    self.log.warning(f"  - 结果: ✗ 未开播 (live_status={live_status})")
                continue
            
            # 如果 room_id 为 0，尝试通过 target_id 获取（备用方法）
            if room_id == 0:
                if verbose and show_details:
                    self.log.info(f"  - 房间ID为0，正在通过UID {target_id} 获取房间ID...")
                room_id = await self.api.getRoomIdByUid(target_id)
                if room_id > 0:
                    medal['room_info']['room_id'] = room_id
                    if verbose and show_details:
                        self.log.info(f"  - 成功获取房间ID: {room_id}")
                else:
                    skipped_no_room += 1
                    if verbose and show_details:
                        self.log.warning(f"  - 结果: 无法获取房间ID，跳过")
                    continue
            
            # 计算该粉丝牌权重（若未配置则为 100）
            weight = self._get_medal_weight(medal)
            medal["weight"] = weight

            # 所有条件满足，加入观看列表
            self.medalsNeedDo.append(medal)
            added_count += 1
            if verbose and show_details:
                self.log.success(
                    f"  - 结果: ✓ 正在开播，已加入观看列表 (房间ID: {room_id}, 权重: {weight})"
                )
        
        # 先按权重由高到低, 再按粉丝团等级由高到低排序
        self.medalsNeedDo.sort(
            key=lambda x: (x.get("weight", self._get_medal_weight(x)), x["medal"]["level"]),
            reverse=True,
        )
        
        if verbose:
            self.log.info("=" * 60)
            self.log.info("筛选结果统计:")
            self.log.info(f"  - 总粉丝牌数: {medal_count}")
            if skipped_blacklist > 0:
                self.log.info(f"  - 黑名单跳过: {skipped_blacklist}")
            if skipped_whitelist > 0:
                self.log.info(f"  - 白名单跳过: {skipped_whitelist}")
            self.log.info(f"  - 进入筛选: {len(self.medals)}")
            self.log.info(f"  - 亲密度已满30跳过: {skipped_intimacy}")
            self.log.info(f"  - 未开播跳过: {skipped_not_live}")
            self.log.info(f"  - 无法获取房间ID跳过: {skipped_no_room}")
            self.log.info(f"  - 最终可观看数量: {len(self.medalsNeedDo)}")
            self.log.info("=" * 60)
            
            if self.medalsNeedDo:
                self.log.info(f"共找到 {len(self.medalsNeedDo)} 个正在开播且亲密度<30的直播间:")
                for idx, medal in enumerate(self.medalsNeedDo, 1):
                    anchor_name = medal.get('anchor_info', {}).get('nick_name', '未知')
                    level = medal.get('medal', {}).get('level', 0)
                    today_feed = medal.get('medal', {}).get('today_feed', 0)
                    weight = medal.get("weight", self._get_medal_weight(medal))
                    self.log.info(
                        f"  {idx}. {anchor_name} (权重{weight}, 等级{level}, 亲密度{today_feed})"
                    )
            else:
                self.log.warning("未找到符合条件的直播间！")

    async def init(self):
        if not await self.loginVerify():
            self.log.log("ERROR", "登录失败 可能是 access_key 过期 , 请重新获取")
            self.errmsg.append("登录失败 可能是 access_key 过期 , 请重新获取")
            await self.session.close()
        else:
            # 初始化时获取一次，用于 start() 中判断是否有需要观看的直播间
            # 设置为 verbose=False 避免重复打印详细信息（watchinglive 中会再次获取并打印）
            await self.getMedals(verbose=False)

    async def start(self):
        if self.isLogin:
            if self.medalsNeedDo:
                self.log.log("INFO", f"共有 {len(self.medalsNeedDo)} 个正在开播且亲密度<30的直播间")
            else:
                self.log.log("WARNING", "=" * 60)
                self.log.log("WARNING", "当前没有需要观看的直播间")
                self.log.log("WARNING", "可能的原因:")
                self.log.log("WARNING", "  1. 所有开播直播间的亲密度已满30")
                self.log.log("WARNING", "  2. 没有正在开播的直播间")
                self.log.log("WARNING", "  3. 所有直播间都无法获取开播状态")
                self.log.log("WARNING", "将进入循环模式，每5分钟重新请求接口并筛选")
                self.log.log("WARNING", "=" * 60)
            # 无论是否有可观看的直播间，都进入 watchinglive 循环
            # 这样即使当前没有直播间，也会每5分钟重新请求接口并筛选
            await self.watchinglive()

    async def sendmsg(self):
        if not self.isLogin:
            await self.session.close()
            return self.message + self.errmsg
        
        # 不需要重新获取数据，直接使用已有的 medalsNeedDo
        # 因为 start() 中已经获取过最新数据了
        if self.medalsNeedDo:
            self.message.append(f"【{self.name}】 本次观看任务完成")
            self.message.append(f"共处理 {len(self.medalsNeedDo)} 个正在开播且亲密度<30的直播间")
            self.message.append("观看详情：")
            for medal in self.medalsNeedDo:
                room_name = medal['anchor_info']['nick_name']
                room_level = medal['medal']['level']
                today_feed = medal['medal']['today_feed']
                self.message.append(f"  - {room_name}（等级{room_level}，当前亲密度{today_feed}，预计获得30亲密度）")
        else:
            self.message.append(f"【{self.name}】 没有需要观看的直播间")
        
        await self.session.close()
        return self.message + self.errmsg + ['---']

    async def _get_medal_from_wall(self, target_id: int):
        async for medal in self.api.getFansMedalandRoomID(verbose=False):
            if medal.get("medal", {}).get("target_id") == target_id:
                return medal
        return None

    async def _like_room_30_times(self, room_name: str, room_id: int, target_id: int):
        self.log.log(
            "WARNING",
            f"{room_name} 亲密度没有变化, 怀疑是粉丝勋章熄灭, 现在去点赞直播间30次"
        )
        
        # 点赞30次，每次间隔3秒
        for like_count in range(1, 31):
            try:
                # 使用 likeInteractV3 接口点赞
                await self.api.likeInteractV3(room_id, target_id, self.mid)
                if self.verbose_log:
                    self.log.info(f"{room_name} 点赞第 {like_count} 次成功")
            except Exception as e:
                if self.verbose_log:
                    self.log.warning(f"{room_name} 点赞第 {like_count} 次失败: {e}")
            
            # 每次间隔3秒（最后一次不需要等待）
            if like_count < 30:
                await asyncio.sleep(3)
        
        self.log.log(
            "INFO",
            f"{room_name} 点赞30次完成"
        )
        
        # 等待5秒
        await asyncio.sleep(5)

    async def _watch_room_with_checks(self, medal: dict, position: int, total_candidates: int):
        import time

        room_name = medal["anchor_info"]["nick_name"]
        room_level = medal["medal"]["level"]
        today_feed = medal["medal"]["today_feed"]
        target_id = medal["medal"]["target_id"]
        room_id = medal["room_info"]["room_id"]

        self.log.log(
            "INFO",
            f"开始观看 {room_name}（等级{room_level}，当前亲密度{today_feed}）",
        )

        heart_num = 0
        room_start_time = int(time.time())  # 每个5分钟周期的开始时间
        has_entered_room = False  # 标记是否已进入房间
        heartbeat_interval = 30
        cycle_heart_num = 0  # 当前周期内的心跳计数（每5分钟重置）
        last_heartbeat_time = None  # 上次心跳的时间戳，用于计算增量时长
        entry_timestamp = None  # entryRoom 返回的时间戳，用于第一次心跳
        initial_intimacy = today_feed  # 记录初始亲密度，用于对比变化

        while True:
            # 每5分钟重置观看开始时间和心跳计数
            room_start_time = int(time.time())
            cycle_heart_num = 0
            last_heartbeat_time = None  # 重置上次心跳时间
            entry_timestamp = None  # 重置 entryRoom 时间戳
            self.log.debug(f"{room_name} 开始新的5分钟周期，重置观看开始时间: {room_start_time}")
            
            # 先观看 5 分钟（11 个心跳，每个 30 秒）
            # 使用更短的心跳间隔（30秒）来确保B站能正确累计观看时长
            for heartbeat_index in range(11):  # 11个心跳，从0分钟0秒到5分钟0秒
                heart_num += 1
                cycle_heart_num += 1
                seq_id = heart_num
                is_last_heartbeat = (heartbeat_index == 10)  # 第11次心跳（索引10）是最后一次
                
                try:
                    # 第一次心跳前，先进入房间
                    if not has_entered_room:
                        try:
                            entry_result = await self.api.entryRoom(room_id, target_id)
                            has_entered_room = True
                            self.log.info(f"{room_name} 已进入直播间，entryRoom响应: {entry_result}")
                            if isinstance(entry_result, dict) and 'heartbeat_interval' in entry_result:
                                server_interval = entry_result.get('heartbeat_interval', 60)
                                heartbeat_interval = min(server_interval, 30)
                                self.log.info(f"{room_name} 使用心跳间隔: {heartbeat_interval}秒（服务器建议: {server_interval}秒）")
                            # 保存 entryRoom 返回的时间戳，用于第一次心跳
                            if isinstance(entry_result, dict) and 'timestamp' in entry_result:
                                entry_timestamp = entry_result.get('timestamp')
                            # 进入房间后稍等一下再发送心跳
                            await asyncio.sleep(2)
                        except Exception as e:
                            self.log.warning(f"{room_name} 进入房间失败: {e}，继续尝试心跳")
                    
                    current_time = int(time.time())
                    
                    if last_heartbeat_time is not None:
                        actual_elapsed = current_time - last_heartbeat_time
                        watch_time = max(1, min(heartbeat_interval, actual_elapsed))
                        timestamp = current_time - watch_time
                    elif entry_timestamp is not None:
                        actual_elapsed = current_time - entry_timestamp
                        watch_time = max(1, min(heartbeat_interval, actual_elapsed))
                        if actual_elapsed <= 1:
                            timestamp = current_time - watch_time
                        else:
                            timestamp = min(entry_timestamp, current_time - watch_time)
                    else:
                        watch_time = max(1, heartbeat_interval)
                        timestamp = current_time - watch_time
                    
                    heartbeat_result = await self.api.heartbeat(
                        room_id,
                        target_id,
                        watch_time=watch_time,
                        start_timestamp=timestamp,
                        seq_id=seq_id,
                    )
                    
                    # 心跳成功后，更新上次心跳时间
                    last_heartbeat_time = current_time
                    
                    # 尝试从心跳响应中更新heartbeat_interval
                    if isinstance(heartbeat_result, dict) and 'heartbeat_interval' in heartbeat_result:
                        server_interval = heartbeat_result.get('heartbeat_interval', 60)
                        # 使用服务器返回的间隔，但不大于30秒
                        new_interval = min(server_interval, 30)
                        if new_interval != heartbeat_interval:
                            heartbeat_interval = new_interval
                            self.log.info(f"{room_name} 更新心跳间隔为: {heartbeat_interval}秒")
                    
                    # 心跳后打印观看时长（心跳完成时的状态）
                    # 已观看时长 = (cycle_heart_num - 1) * heartbeat_interval
                    # 第1次心跳后：0分钟0秒，第2次心跳后：0分钟30秒，...，第11次心跳后：5分钟0秒
                    cycle_watched_seconds = (cycle_heart_num - 1) * heartbeat_interval
                    cycle_watched_str = self._format_watch_time(cycle_watched_seconds)
                    self.log.info(
                        f"{room_name} 本周期已观看 {cycle_watched_str}"
                    )
                except Exception as e:
                    # 记录详细上下文以便排查
                    current_time_on_error = int(time.time())
                    if last_heartbeat_time is not None:
                        drift = current_time_on_error - last_heartbeat_time
                    else:
                        drift = current_time_on_error - room_start_time
                    self.log.error(
                        f"{room_name} 心跳#{seq_id} 失败: {e} | "
                        f"room_id={room_id}, up_id={target_id}, "
                        f"timestamp={timestamp if 'timestamp' in locals() else 'N/A'}, "
                        f"watch_time={watch_time if 'watch_time' in locals() else 'N/A'}, "
                        f"now={current_time_on_error}, drift={drift}s"
                    )
                    # 如果心跳失败，返回None让上层重新获取列表
                    return None
                
                # 如果不是最后一次心跳，等待心跳间隔
                if not is_last_heartbeat:
                    await asyncio.sleep(heartbeat_interval)

            # 5分钟周期结束，等待5秒后重新获取接口信息
            actual_watch_time = int(time.time()) - room_start_time
            watched_time_str = self._format_watch_time(actual_watch_time)
            self.log.log(
                "INFO",
                f"{room_name} 本周期观看完成（实际时长：{watched_time_str}），等待5秒后重新获取接口信息...",
            )
            
            # 等待5秒
            await asyncio.sleep(5)
            

            try:
                current_medal = await self._get_medal_from_wall(target_id)
                if current_medal:
                    current_intimacy = current_medal.get("medal", {}).get("today_feed", 0)
                    intimacy_change = current_intimacy - initial_intimacy
                    if intimacy_change > 0:
                        self.log.info(
                            f"{room_name} 本日亲密度变化: {initial_intimacy} -> {current_intimacy} (增加了 {intimacy_change})"
                        )
                    elif intimacy_change < 0:
                        self.log.warning(
                            f"{room_name} 本日亲密度变化: {initial_intimacy} -> {current_intimacy} (减少了 {abs(intimacy_change)})"
                        )
                    else:
                        self.log.info(
                            f"{room_name} 本日亲密度: {current_intimacy} (无变化)"
                        )
                    # 更新初始亲密度为当前值，用于下次对比
                    initial_intimacy = current_intimacy
                else:
                    self.log.debug(f"{room_name} 无法获取最新亲密度信息")
            except Exception as e:
                self.log.warning(f"{room_name} 检查亲密度变化时出错: {e}")
            
            
            # 5分钟周期结束，返回信号让上层重新筛选直播间
            self.log.info(f"{room_name} 5分钟周期结束，重新筛选直播间")
            return "rescreen"

    async def watchinglive(self):
        watched_rooms = 0
        first_run = True
        last_room_id = None  # 记录上一次观看的直播间ID

        while True:
            # 根据配置决定是否打印详细信息
            await self.getMedals(verbose=self.verbose_log and first_run, show_details=self.verbose_log and first_run)
            first_run = False

            if not self.medalsNeedDo:
                # 没有需要观看的直播间，每5分钟重新请求接口并筛选一次
                self.log.warning("当前没有在观看的直播，将在5分钟后重新请求接口并筛选...")
                await asyncio.sleep(300)  # 等待5分钟（300秒）
                # 继续循环，重新请求接口并筛选
                continue

            # 有可观看的直播间，开始观看流程
            current_medal = self.medalsNeedDo[0]
            current_room_id = current_medal["room_info"]["room_id"]
            current_target_id = current_medal["medal"]["target_id"]
            room_name = current_medal["anchor_info"]["nick_name"]
            
            # 每次更换观看直播间时，等待10秒（第一次观看时不需要等待）
            if last_room_id is not None and current_room_id != last_room_id:
                self.log.info(f"更换观看直播间（从 {last_room_id} 切换到 {current_room_id}），等待10秒...")
                await asyncio.sleep(10)
            
            # 在开始观看前，检查粉丝牌是否已点亮
            try:
                medal_info = await self.api.getUserMedalInfo(self.mid, current_target_id)
                curr_show = medal_info.get("data", {}).get("curr_show", {})
                is_light = curr_show.get("is_light", 1)  # 默认为1（已点亮），避免误判
                
                if is_light == 0:
                    # 未点亮，执行点赞30次
                    self.log.warning(f"{room_name} 粉丝牌未点亮，开始点赞30次...")
                    await self._like_room_30_times(room_name, current_room_id, current_target_id)
                else:
                    self.log.debug(f"{room_name} 粉丝牌已点亮（is_light={is_light}）")
            except Exception as e:
                self.log.warning(f"{room_name} 检查粉丝牌点亮状态失败: {e}，继续观看流程")
            
            watched_rooms += 1
            last_room_id = current_room_id  # 更新上一次观看的直播间ID

            result = await self._watch_room_with_checks(current_medal, watched_rooms, len(self.medalsNeedDo))
            
            # 如果观看过程中出错（返回None），立即重新请求接口并筛选
            if result is None:
                self.log.warning("观看过程中出现错误，立即重新请求接口并筛选直播间")
                continue
            
            # 5分钟周期结束，重新筛选直播间
            if result == "rescreen":
                self.log.info("5分钟周期结束，重新请求接口并筛选直播间")
                # 重新请求接口并筛选，如果配置了VERBOSE_LOG，打印筛选结果统计（不打印详细检查信息）
                await self.getMedals(verbose=self.verbose_log, show_details=False)
                continue

        self.log.log("SUCCESS", f"观看直播任务完成，共尝试 {watched_rooms} 个直播间")
