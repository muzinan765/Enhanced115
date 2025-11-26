"""
黑名单管理模块
管理违规TMDB ID的黑名单，支持多种处理策略
"""
from typing import Dict, Any, Optional, List
import time

from app.log import logger


class BlacklistManager:
    """黑名单管理器"""
    
    # 支持的处理策略
    STRATEGIES = {
        "skip_share": {
            "name": "跳过分享",
            "description": "仅上传，不创建分享链接"
        },
        "alternative_share": {
            "name": "备用分享方式",
            "description": "使用其他分享渠道（预留）"
        },
        "delayed_share": {
            "name": "延迟分享",
            "description": "N天后重试正常分享"
        }
    }
    
    def __init__(self, plugin_data_ops):
        """
        初始化黑名单管理器
        :param plugin_data_ops: 插件数据操作对象（用于save_data/get_data）
        """
        self.data_ops = plugin_data_ops
        self._blacklist_key = "violation_blacklist"
    
    def is_blacklisted(self, tmdb_id: int) -> bool:
        """
        检查TMDB ID是否在黑名单中
        :param tmdb_id: TMDB ID
        :return: 是否在黑名单中
        """
        blacklist = self._load_blacklist()
        return str(tmdb_id) in blacklist.get("tmdb_ids", {})
    
    def get_blacklist_entry(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        """
        获取黑名单条目详情
        :param tmdb_id: TMDB ID
        :return: 黑名单条目，不存在则返回None
        """
        blacklist = self._load_blacklist()
        return blacklist.get("tmdb_ids", {}).get(str(tmdb_id))
    
    def add_to_blacklist(self, tmdb_id: int, info: Dict[str, Any]) -> bool:
        """
        添加到黑名单
        :param tmdb_id: TMDB ID
        :param info: 违规信息
            - media_title: 媒体标题
            - violation_time: 违规时间
            - violation_message: 违规消息
        :return: 是否成功添加
        """
        blacklist = self._load_blacklist()
        
        tmdb_id_str = str(tmdb_id)
        if tmdb_id_str in blacklist.get("tmdb_ids", {}):
            logger.info(f"【Enhanced115】TMDB ID {tmdb_id} 已在黑名单中")
            return False
        
        # 创建黑名单条目
        entry = {
            "tmdb_id": tmdb_id,
            "media_title": info.get("media_title", "未知"),
            "violation_time": info.get("violation_time", ""),
            "violation_message": info.get("violation_message", ""),
            "added_time": int(time.time()),
            
            # 默认策略
            "strategy": "skip_share",
            "strategy_config": {
                "retry_after_days": 30,
                "notify_admin": True
            },
            
            # 违规历史
            "violation_history": [{
                "time": info.get("violation_time", ""),
                "message": info.get("violation_message", ""),
                "action": "加入黑名单"
            }]
        }
        
        # 添加到黑名单
        if "tmdb_ids" not in blacklist:
            blacklist["tmdb_ids"] = {}
        
        blacklist["tmdb_ids"][tmdb_id_str] = entry
        self._save_blacklist(blacklist)
        
        logger.warning(
            f"【Enhanced115】已将 {entry['media_title']} (TMDB:{tmdb_id}) 加入黑名单，"
            f"违规时间：{entry['violation_time']}"
        )
        
        return True
    
    def remove_from_blacklist(self, tmdb_id: int) -> bool:
        """
        从黑名单移除
        :param tmdb_id: TMDB ID
        :return: 是否成功移除
        """
        blacklist = self._load_blacklist()
        tmdb_id_str = str(tmdb_id)
        
        if tmdb_id_str in blacklist.get("tmdb_ids", {}):
            entry = blacklist["tmdb_ids"][tmdb_id_str]
            del blacklist["tmdb_ids"][tmdb_id_str]
            self._save_blacklist(blacklist)
            logger.info(f"【Enhanced115】已将 {entry['media_title']} (TMDB:{tmdb_id}) 移出黑名单")
            return True
        
        return False
    
    def update_strategy(self, tmdb_id: int, strategy: str, config: Optional[Dict] = None) -> bool:
        """
        更新黑名单条目的处理策略
        :param tmdb_id: TMDB ID
        :param strategy: 新策略
        :param config: 策略配置
        :return: 是否成功更新
        """
        if strategy not in self.STRATEGIES:
            logger.error(f"【Enhanced115】未知策略：{strategy}")
            return False
        
        blacklist = self._load_blacklist()
        tmdb_id_str = str(tmdb_id)
        
        if tmdb_id_str not in blacklist.get("tmdb_ids", {}):
            logger.error(f"【Enhanced115】TMDB ID {tmdb_id} 不在黑名单中")
            return False
        
        entry = blacklist["tmdb_ids"][tmdb_id_str]
        entry["strategy"] = strategy
        
        if config:
            entry["strategy_config"].update(config)
        
        self._save_blacklist(blacklist)
        logger.info(f"【Enhanced115】已更新 {entry['media_title']} 的策略为：{strategy}")
        
        return True
    
    def get_all_blacklist(self) -> List[Dict[str, Any]]:
        """
        获取所有黑名单条目
        :return: 黑名单列表
        """
        blacklist = self._load_blacklist()
        return list(blacklist.get("tmdb_ids", {}).values())
    
    def _load_blacklist(self) -> Dict[str, Any]:
        """加载黑名单数据"""
        blacklist = self.data_ops.get_data(self._blacklist_key) or {}
        
        # 确保数据结构
        if "tmdb_ids" not in blacklist:
            blacklist["tmdb_ids"] = {}
        
        return blacklist
    
    def _save_blacklist(self, blacklist: Dict[str, Any]):
        """保存黑名单数据"""
        self.data_ops.save_data(self._blacklist_key, blacklist)

