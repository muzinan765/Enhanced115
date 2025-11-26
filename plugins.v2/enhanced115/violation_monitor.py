"""
违规监控模块
定期检查115系统通知中的分享违规消息，自动加入黑名单
"""
from typing import Dict, Any, List, Optional
import re
import time
from datetime import datetime

from app.log import logger


class ViolationMonitor:
    """违规监控器"""
    
    def __init__(self, p115_client, blacklist_manager, plugin_data_ops):
        """
        初始化违规监控器
        :param p115_client: p115客户端
        :param blacklist_manager: 黑名单管理器
        :param plugin_data_ops: 插件数据操作对象
        """
        self.client = p115_client
        self.blacklist_manager = blacklist_manager
        self.data_ops = plugin_data_ops
        self._state_key = "violation_check_state"
    
    def check_violations(self) -> Dict[str, Any]:
        """
        检查违规通知
        :return: 检查结果统计
        """
        logger.info("【Enhanced115】开始检查分享违规通知...")
        
        stats = {
            "total_messages": 0,
            "new_violations": 0,
            "blacklisted": 0,
            "failed": 0
        }
        
        try:
            # 获取已处理消息ID列表
            state = self._load_state()
            processed_ids = set(state.get("processed_message_ids", []))
            
            # 获取系统消息
            resp = self.client.msg_contacts_ls({
                "limit": 100,
                "skip": 0,
                "t": 1
            })
            
            if not resp.get("state"):
                logger.error(f"【Enhanced115】获取系统消息失败：{resp}")
                return stats
            
            messages = resp.get("data", {}).get("list", [])
            stats["total_messages"] = len(messages)
            
            logger.info(f"【Enhanced115】获取到 {len(messages)} 条系统消息")
            
            # 过滤已处理消息和违规消息
            violation_messages = []
            new_processed_ids = set(processed_ids)
            
            for msg in messages:
                # 使用c_id作为唯一标识，如果没有则使用send_time
                msg_id = msg.get("c_id") or str(msg.get("send_time", ""))
                msg_content = msg.get("b", "")
                msg_time = msg.get("send_time", 0)
                
                # 测试阶段：暂时不跳过已处理的消息，以便测试
                # TODO: 测试完成后恢复已处理消息过滤
                # if msg_id in processed_ids:
                #     logger.debug(f"【Enhanced115】跳过已处理消息：{msg_id}")
                #     continue
                
                # 检查是否为违规消息
                if self._is_violation_message(msg_content):
                    msg_time_str = datetime.fromtimestamp(msg_time).strftime("%Y-%m-%d %H:%M:%S") if msg_time > 0 else "未知"
                    logger.info(
                        f"【Enhanced115】识别到违规消息（ID={msg_id}，时间={msg_time_str}）："
                        f"{msg_content[:100]}..."
                    )
                    violation_messages.append(msg)
                    stats["new_violations"] += 1
                    # 标记为已处理
                    new_processed_ids.add(msg_id)
                else:
                    logger.debug(f"【Enhanced115】非违规消息，跳过：{msg_content[:50]}...")
            
            logger.info(f"【Enhanced115】发现 {len(violation_messages)} 条新违规消息")
            
            # 处理违规消息
            for msg in violation_messages:
                if self._process_violation_message(msg):
                    stats["blacklisted"] += 1
                else:
                    stats["failed"] += 1
            
            # 更新已处理消息ID列表（限制最大数量，避免无限增长）
            max_processed_ids = 1000
            if len(new_processed_ids) > max_processed_ids:
                # 保留最新的1000个ID
                processed_list = sorted(list(new_processed_ids), reverse=True)[:max_processed_ids]
                new_processed_ids = set(processed_list)
                logger.debug(f"【Enhanced115】已处理消息ID列表已满，保留最新的{max_processed_ids}条")
            
            # 保存状态
            state["processed_message_ids"] = list(new_processed_ids)
            state["last_check_time"] = int(time.time())
            self._save_state(state)
            
            logger.info(
                f"【Enhanced115】违规检查完成，"
                f"新增黑名单：{stats['blacklisted']}，"
                f"处理失败：{stats['failed']}"
            )
            
            return stats
            
        except Exception as e:
            logger.error(f"【Enhanced115】检查违规通知失败：{e}", exc_info=True)
            return stats
    
    def _is_violation_message(self, content: str) -> bool:
        """
        判断是否为违规消息
        :param content: 消息内容
        :return: 是否为违规消息
        """
        keywords = ["违规", "分享的文件", "违反", "已被"]
        return any(keyword in content for keyword in keywords)
    
    def _process_violation_message(self, msg: Dict[str, Any]) -> bool:
        """
        处理违规消息
        :param msg: 消息对象
        :return: 是否成功处理
        """
        try:
            content = msg.get("b", "")
            send_time = msg.get("send_time", 0)
            
            # 解析违规信息
            violation_info = self._parse_violation_message(content, send_time)
            
            if not violation_info:
                logger.warning(f"【Enhanced115】无法解析违规消息：{content}")
                return False
            
            logger.info(
                f"【Enhanced115】解析到违规分享："
                f"时间={violation_info['share_time_str']}，"
                f"首字={violation_info['first_char']}，"
                f"扩展名={violation_info['extension']}"
            )
            
            # 尝试匹配分享记录
            tmdb_id = self._match_share_record(violation_info)
            
            if tmdb_id:
                # 加入黑名单
                blacklist_info = {
                    "media_title": violation_info.get("media_title", "未知"),
                    "violation_time": violation_info["share_time_str"],
                    "violation_message": content
                }
                
                self.blacklist_manager.add_to_blacklist(tmdb_id, blacklist_info)
                return True
            else:
                logger.warning(
                    f"【Enhanced115】无法匹配分享记录："
                    f"时间={violation_info['share_time_str']}，"
                    f"首字={violation_info['first_char']}"
                )
                return False
                
        except Exception as e:
            logger.error(f"【Enhanced115】处理违规消息失败：{e}", exc_info=True)
            return False
    
    def _parse_violation_message(self, content: str, send_time: int) -> Optional[Dict[str, Any]]:
        """
        解析违规消息内容
        :param content: 消息内容
        :param send_time: 消息时间
        :return: 解析结果
        """
        try:
            # 提取分享时间（格式：你在2025-11-25 10:06:39 分享的文件）
            time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', content)
            if not time_match:
                logger.debug(f"【Enhanced115】时间匹配失败，消息内容：{content[:100]}")
                return None
            
            share_time_str = time_match.group(1)
            logger.debug(f"【Enhanced115】提取到分享时间：{share_time_str}")
            
            # 转换为时间戳
            try:
                dt = datetime.strptime(share_time_str, "%Y-%m-%d %H:%M:%S")
                share_timestamp = int(dt.timestamp())
            except Exception as e:
                logger.error(f"【Enhanced115】时间转换失败：{e}")
                return None
            
            # 提取文件名信息（格式："东***.mkv" 或 "东***.mkv"）
            # 匹配所有可能的引号类型：ASCII引号 " 和中文引号 " "
            # 文件名可能包含星号等特殊字符，使用非贪婪匹配
            file_match = re.search(r'["""]([^"""\n]+?\.\w+)["""]', content)
            if not file_match:
                logger.warning(f"【Enhanced115】无法提取文件名，消息内容：{content}")
                return None
            
            file_name = file_match.group(1)
            logger.debug(f"【Enhanced115】提取到文件名：{file_name[:50]}...")
            
            # 提取首字和扩展名
            first_char = file_name[0] if file_name else ""
            extension_match = re.search(r'\.(\w+)$', file_name)
            extension = f".{extension_match.group(1)}" if extension_match else ""
            
            if not extension:
                logger.warning(f"【Enhanced115】无法提取扩展名，文件名：{file_name}")
                return None
            
            logger.info(
                f"【Enhanced115】成功解析违规消息："
                f"时间={share_time_str}，首字={first_char}，扩展名={extension}"
            )
            
            return {
                "share_time_str": share_time_str,
                "share_timestamp": share_timestamp,
                "first_char": first_char,
                "extension": extension,
                "file_name_pattern": file_name
            }
            
        except Exception as e:
            logger.error(f"【Enhanced115】解析违规消息失败：{e}", exc_info=True)
            return None
    
    def _match_share_record(self, violation_info: Dict[str, Any]) -> Optional[int]:
        """
        根据违规信息匹配分享记录，获取TMDB ID
        :param violation_info: 违规信息
        :return: TMDB ID，未找到返回None
        """
        share_timestamp = violation_info["share_timestamp"]
        
        # 从分享记录中查找
        share_history = self.data_ops.get_data("share_history") or {}
        
        # 精确匹配时间戳
        if str(share_timestamp) in share_history:
            record = share_history[str(share_timestamp)]
            logger.info(f"【Enhanced115】通过时间戳精确匹配到：{record.get('media_title')}")
            return record.get("tmdb_id")
        
        # 如果没有精确匹配，尝试时间窗口匹配（前后5分钟）
        time_window = 300
        matched_records = []
        
        for timestamp_str, record in share_history.items():
            record_time = int(timestamp_str)
            if abs(record_time - share_timestamp) <= time_window:
                matched_records.append({
                    "record": record,
                    "time_diff": abs(record_time - share_timestamp)
                })
        
        if not matched_records:
            logger.warning("【Enhanced115】未找到匹配的分享记录（时间窗口±5分钟）")
            return None
        
        # 按时间差排序，取最接近的
        matched_records.sort(key=lambda x: x["time_diff"])
        best_match = matched_records[0]["record"]
        
        if len(matched_records) > 1:
            logger.warning(
                f"【Enhanced115】找到 {len(matched_records)} 条匹配记录，"
                f"选择时间最接近的：{best_match.get('media_title')}，"
                f"时间差：{matched_records[0]['time_diff']}秒"
            )
        else:
            logger.info(
                f"【Enhanced115】通过时间窗口匹配到：{best_match.get('media_title')}，"
                f"时间差：{matched_records[0]['time_diff']}秒"
            )
        
        return best_match.get("tmdb_id")
    
    def _load_state(self) -> Dict[str, Any]:
        """加载检查状态"""
        state = self.data_ops.get_data(self._state_key) or {}
        
        # 初始化已处理消息ID列表
        if "processed_message_ids" not in state:
            state["processed_message_ids"] = []
        
        # 初始化最后检查时间
        if "last_check_time" not in state:
            state["last_check_time"] = 0
        
        return state
    
    def _save_state(self, state: Dict[str, Any]):
        """保存检查状态"""
        self.data_ops.save_data(self._state_key, state)

