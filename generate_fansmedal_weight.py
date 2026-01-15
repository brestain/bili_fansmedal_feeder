import asyncio
import json
import os
import shutil
import sys
from typing import Dict, Any, Tuple, Optional

from loguru import logger

from src import BiliUser


log = logger.bind(user="粉丝牌权重生成工具")


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


def _load_users_config() -> Dict[str, Any]:
    """
    加载 users.yaml 或环境变量 USERS.
    """
    try:
        if os.environ.get("USERS"):
            users = json.loads(os.environ.get("USERS"))
        else:
            import yaml
            base_dir = _get_base_dir()
            config_path = os.path.join(base_dir, "users.yaml")
            with open(config_path, "r", encoding="utf-8") as f:
                users = yaml.load(f, Loader=yaml.FullLoader)
        return users
    except Exception as e:  # pragma: no cover - 防御性日志
        log.error(f"读取配置文件失败, 请检查配置文件格式是否正确: {e}")
        raise


async def _collect_medals() -> Dict[int, Dict[str, Any]]:
    """
    使用已有的 BiliUser / BiliApi 逻辑, 获取一次所有账号的粉丝牌列表.

    返回:
         { target_id: { 'up_name': str, 'medal_name': str } }
    """
    users_cfg = _load_users_config()
    medals_map: Dict[int, Dict[str, Any]] = {}

    for user in users_cfg.get("USERS", []):
        access_key = user.get("access_key")
        if not access_key:
            continue

        white_uid = user.get("white_uid", "")
        banned_uid = user.get("banned_uid", "")
        config = {}

        bili_user = BiliUser(access_key, white_uid, banned_uid, config)
        ok = await bili_user.loginVerify()
        if not ok:
            log.warning("账号登录失败，跳过该账号")
            continue

        log.info(f"开始获取账号【{bili_user.name}】的粉丝牌列表")
        async for medal in bili_user.api.getFansMedalandRoomID(verbose=False):
            medal_info = medal.get("medal", {})
            anchor_info = medal.get("anchor_info", {})
            target_id = int(medal_info.get("target_id", 0) or 0)
            if not target_id:
                continue

            up_name = anchor_info.get("nick_name", "未知")
            medal_name = medal_info.get("medal_name", "")

            # 后写覆盖前写无伤大雅, 以最后一次为准
            medals_map[target_id] = {
                "up_name": up_name,
                "medal_name": medal_name,
            }

        await bili_user.session.close()

    return medals_map


def _load_existing_weights(path: str) -> Tuple[Dict[str, Any], bool, Optional[str]]:
    """
    读取已存在的 fansmedal_weight.yaml, 不存在则返回空字典.
    
    返回:
        (data, has_format_error, backup_path)
        - data: 解析后的数据字典，格式错误时返回空字典
        - has_format_error: 是否发生格式错误
        - backup_path: 备份文件路径，如果发生格式错误则返回备份路径，否则返回 None
    """
    if not os.path.exists(path):
        return {}, False, None

    import yaml

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = yaml.load(f, Loader=yaml.FullLoader) or {}
        except Exception as e:  # pragma: no cover
            # 格式错误，备份原文件
            base_dir = os.path.dirname(path)
            backup_path = os.path.join(base_dir, "fansmedal_weight_backup.yaml")
            try:
                shutil.copy2(path, backup_path)
                log.warning(f"检测到 {path} 格式错误，已备份到 {backup_path}")
            except Exception as backup_error:
                log.error(f"备份文件失败: {backup_error}")
                backup_path = None
            return {}, True, backup_path
    if not isinstance(data, dict):
        # 数据格式不正确，也视为格式错误
        base_dir = os.path.dirname(path)
        backup_path = os.path.join(base_dir, "fansmedal_weight_backup.yaml")
        try:
            shutil.copy2(path, backup_path)
            log.warning(f"检测到 {path} 数据格式不正确，已备份到 {backup_path}")
        except Exception as backup_error:
            log.error(f"备份文件失败: {backup_error}")
            backup_path = None
        return {}, True, backup_path
    return data, False, None


def _save_weights(path: str, data: Dict[str, Any]) -> None:
    import yaml

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)


async def main():
    """
    获取一次粉丝牌列表, 生成/更新 fansmedal_weight.yaml.

    YAML 结构示例:

    12345678:
      up_name: 某某
      medal_name: 某某粉丝牌
      weight: 100
    """
    base_dir = _get_base_dir()
    os.chdir(base_dir)
    weight_file = os.path.join(base_dir, "fansmedal_weight.yaml")

    medals_map = await _collect_medals()
    if not medals_map:
        log.warning("未获取到任何粉丝牌, 不生成 fansmedal_weight.yaml")
        print("\n" + "=" * 60)
        print("任务完成")
        print("=" * 60)
        print("未获取到任何粉丝牌，未生成 fansmedal_weight.yaml")
        print("\n按任意键结束...")
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        return

    existing, has_format_error, backup_path = _load_existing_weights(weight_file)
    file_existed = os.path.exists(weight_file)

    updated = False
    new_count = 0
    updated_count = 0
    for target_id, info in medals_map.items():
        key = str(target_id)
        if key not in existing:
            # 新增条目, 默认权重 100
            existing[key] = {
                "up_name": info.get("up_name", "未知"),
                "medal_name": info.get("medal_name", ""),
                "weight": 100,
            }
            updated = True
            new_count += 1
        else:
            # 已存在则仅同步 up_name / medal_name, 保留用户自定义的 weight
            entry = existing[key] or {}
            name_updated = False
            if "up_name" not in entry or entry.get("up_name") != info.get("up_name"):
                entry["up_name"] = info.get("up_name", "未知")
                updated = True
                name_updated = True
            if "medal_name" not in entry or entry.get("medal_name") != info.get("medal_name"):
                entry["medal_name"] = info.get("medal_name", "")
                updated = True
                name_updated = True
            if name_updated:
                updated_count += 1
            existing[key] = entry

    # 保存文件（格式错误时也会覆盖原文件）
    if updated or has_format_error or not file_existed:
        _save_weights(weight_file, existing)
        if has_format_error:
            log.success(f"已重新生成 {weight_file}，共记录 {len(existing)} 个粉丝牌（默认权重为 100）")
        elif not file_existed:
            log.success(f"已生成 {weight_file}，共记录 {len(existing)} 个粉丝牌（默认权重为 100）")
        else:
            log.success(f"已更新 {weight_file}，共记录 {len(existing)} 个粉丝牌（默认权重为 100，未配置也视为 100）")
    else:
        log.info("粉丝牌列表无新增或变更, fansmedal_weight.yaml 无需更新")

    # 打印结果摘要并等待用户按任意键结束
    print("\n" + "=" * 60)
    print("任务完成")
    print("=" * 60)
    
    if has_format_error:
        print("⚠️  检测到原文件格式错误！")
        print(f"原文件: {weight_file}")
        if backup_path:
            backup_full_path = os.path.abspath(backup_path)
            print(f"备份位置: {backup_full_path}")
        print("  - 原文件存在 YAML 格式错误，无法正确解析")
        print("  - 程序已自动备份原文件到上述位置")
        print("  - 原文件已被覆盖，所有粉丝牌已使用默认权重 100")
        print("  - 如果原文件中有自定义权重，请从备份文件中手动恢复")
    elif not file_existed:
        print(f"✅ 已生成新文件: {weight_file}")
        print(f"共记录 {len(existing)} 个粉丝牌（默认权重为 100）")
    elif updated:
        print(f"✅ 已更新文件: {weight_file}")
        print(f"共记录 {len(existing)} 个粉丝牌")
        if new_count > 0:
            print(f"  - 新增 {new_count} 个粉丝牌")
        if updated_count > 0:
            print(f"  - 更新 {updated_count} 个粉丝牌的名称信息")
    else:
        print(f"✅ 文件: {weight_file}")
        print("粉丝牌列表无新增或变更，文件无需更新")
        print(f"共记录 {len(existing)} 个粉丝牌")
    
    print("\n" + "=" * 60)
    print("\n按任意键结束...")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    asyncio.run(main())


