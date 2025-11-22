"""
Telegram通知模块
完全复制my_115_app的notifier.py逻辑（一点不差）
"""
import re
import math
from typing import Dict, Optional, List, Any, Tuple

from app.log import logger


# 标签黑名单（完全复制my_115_app）
TAG_BLACKLIST = {"官方", "原创", "官字组", "禁转", "限转", "首发", "应求", "零魔"}


class TelegramNotifier:
    """Telegram通知处理类（完全复制my_115_app）"""
    
    def __init__(self, bot_token: str, chat_id: str):
        """
        初始化Telegram通知器
        :param bot_token: Bot Token
        :param chat_id: Chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        
        # 初始化TMDB客户端
        self.tmdb_tv = None
        self.tmdb_movie = None
        self._init_tmdb()
    
    def _init_tmdb(self):
        """初始化TMDB客户端（完全复制my_115_app）"""
        try:
            from tmdbv3api import TMDb, TV, Movie
            
            # 从MoviePilot获取TMDB配置
            from app.core.config import settings
            
            if settings.TMDB_API_KEY:
                tmdb = TMDb()
                tmdb.api_key = settings.TMDB_API_KEY
                tmdb.language = 'zh-CN'
                self.tmdb_tv = TV()
                self.tmdb_movie = Movie()
                logger.info("【Enhanced115】TMDB服务初始化成功")
            else:
                logger.warning("【Enhanced115】未配置TMDB API Key")
        except Exception as e:
            logger.warning(f"【Enhanced115】TMDB初始化失败：{e}")
    
    @staticmethod
    def _telegram_escape(text: str) -> str:
        """对文本进行Telegram MarkdownV2格式的转义（完全复制my_115_app）"""
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)
    
    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        """将字节大小格式化为人类可读的字符串（完全复制my_115_app）"""
        if size_bytes <= 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = min(int(math.floor(math.log(size_bytes, 1024))), len(size_name) - 1)
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s}{size_name[i]}"
    
    @staticmethod
    def _parse_size_to_bytes(size_val: Any) -> int:
        """将大小字符串转换为字节（完全复制my_115_app）"""
        if isinstance(size_val, (int, float)):
            return int(size_val)
        if not isinstance(size_val, str):
            return 0
        
        size_str = size_val.upper().strip()
        units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
        unit_char = ""
        
        if size_str.endswith("B"):
            size_str = size_str[:-1]
        if size_str and size_str[-1] in units:
            unit_char = size_str[-1]
            num_str = size_str[:-1].strip()
        else:
            num_str = size_str
        
        try:
            num = float(num_str)
            multiplier = units.get(unit_char, 1)
            return int(num * multiplier)
        except (ValueError, TypeError):
            return 0
    
    def get_notification_context(self, download_hash: str, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取通知上下文（完全复制my_115_app的_get_notification_context）
        """
        context = {}
        
        # 步骤1：获取TMDB海报
        try:
            tmdb_id_str = task_info.get('tmdb_id')
            is_movie = task_info.get('is_movie', False)
            
            if tmdb_id_str and (self.tmdb_tv or self.tmdb_movie):
                tmdb_id = int(tmdb_id_str)
                details = None
                
                # 根据类型调用不同的TMDB API
                if is_movie and self.tmdb_movie:
                    details = self.tmdb_movie.details(tmdb_id)
                elif not is_movie and self.tmdb_tv:
                    details = self.tmdb_tv.details(tmdb_id)
                
                # 如果成功获取到详情且海报路径存在
                if details and hasattr(details, 'poster_path') and details.poster_path:
                    context['image_url'] = f"https://image.tmdb.org/t/p/w500{details.poster_path}"
                    logger.info(f"【Enhanced115】成功获取TMDB海报")
                else:
                    context['image_url'] = None
            else:
                context['image_url'] = None
        except Exception as e:
            logger.warning(f"【Enhanced115】获取TMDB海报失败：{e}")
            context['image_url'] = None
        
        # 步骤2：从message表获取并重组通知文本
        try:
            from app.db import SessionFactory
            from sqlalchemy import text
            
            with SessionFactory() as session:
                # 2.1: 获取torrent_name
                sql_get_torrent = text("""
                    SELECT torrent_name FROM downloadhistory 
                    WHERE download_hash = :hash LIMIT 1
                """)
                result = session.execute(sql_get_torrent, {'hash': download_hash})
                dh_record = result.fetchone()
                
                if not dh_record or not dh_record[0]:
                    return context
                
                torrent_name = dh_record[0]
                
                # 2.2: 查找message（完全复制my_115_app的SQL）
                sql_find_message = text("""
                    SELECT title, text, image
                    FROM message
                    WHERE mtype = '资源下载' AND text LIKE '%' || '*原始名称*｜' || :torrent_name || '%'
                    ORDER BY reg_time DESC LIMIT 1
                """)
                result = session.execute(sql_find_message, {'torrent_name': torrent_name})
                msg_record = result.fetchone()
                
                if msg_record:
                    # 解析message内容（完全复制my_115_app的逻辑）
                    raw_title = msg_record[0] or ''
                    text_content = msg_record[1] or ''
                    image_url = msg_record[2] or ''
                    
                    # 提取标题（移除"*下载开始*｜"前缀）
                    title_text = re.sub(r'^.*?\*下载开始\*\s*｜\s*', '', raw_title).strip()
                    
                    text_lines = text_content.split('\n')
                    new_title_line = ""
                    other_lines = []
                    has_tag_line = False
                    
                    for line in text_lines:
                        # 移除所有旧的星号
                        line_stripped = line.strip().replace('*', '')
                        if not line_stripped:
                            continue
                        
                        # 解析"类型｜"行
                        if '类型｜' in line_stripped:
                            try:
                                parts = line_stripped.split('类型｜')
                                original_emoji = parts[0].strip()
                                type_content = parts[1].strip()
                                
                                # 提取括号内容
                                match = re.search(r'[（\(](.*?)[）\)]', type_content)
                                extracted_type = match.group(1) if match else type_content
                                
                                new_title_line = f"{original_emoji} {extracted_type}｜{title_text}"
                            except Exception as e:
                                logger.warning(f"【Enhanced115】解析类型行失败：{e}")
                                new_title_line = line_stripped
                        
                        # 过滤"原始名称"和"内容简介"
                        elif '原始名称｜' in line_stripped:
                            continue
                        elif '内容简介｜' in line_stripped:
                            continue
                        
                        # 解析标签行
                        elif '标签｜' in line_stripped:
                            has_tag_line = True
                            try:
                                parts = line_stripped.split('｜', 1)
                                key = parts[0].strip()
                                value = parts[1].strip()
                                
                                # 过滤黑名单标签
                                tags = [t.strip() for t in value.split() 
                                       if t.strip() and t.strip() not in TAG_BLACKLIST]
                                
                                if tags:
                                    other_lines.append(f"{key}｜{' '.join(tags)}")
                            except Exception as e:
                                logger.warning(f"【Enhanced115】解析标签行失败：{e}")
                        
                        # 保留其他所有行
                        else:
                            other_lines.append(line_stripped)
                    
                    # 动态生成标签（如果message中没有）
                    if not has_tag_line:
                        match = re.search(r'\[([^\]]+)\]\s*$', torrent_name)
                        if match:
                            tags_content = match.group(1)
                            tags = [t.strip() for t in tags_content.split('|') 
                                   if t.strip() and t.strip() not in TAG_BLACKLIST]
                            if tags:
                                other_lines.append(f"🏷️ 标签｜{' '.join(tags)}")
                    
                    # 格式化：使用占位符标记加粗
                    formatted_other_lines = []
                    for line in other_lines:
                        parts = line.split('｜', 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip()
                            formatted_other_lines.append(f"__BOLD_START__{key}__BOLD_END__｜{value}")
                        else:
                            formatted_other_lines.append(line)
                    
                    # 标记标题行
                    if new_title_line:
                        new_title_line = f"__BOLD_START__{new_title_line}__BOLD_END__"
                    else:
                        new_title_line = f"__BOLD_START__{title_text}__BOLD_END__"
                    
                    # 拼接：标题 + 空行 + 信息块
                    context['notification_text'] = f"{new_title_line}\n\n" + "\n".join(formatted_other_lines)
                    
                    # 备用图片
                    if not context.get('image_url') and image_url:
                        context['image_url'] = image_url
        
        except Exception as e:
            logger.error(f"【Enhanced115】获取通知上下文失败：{e}")
        
        return context
    
    def send_share_notification(self, task_info: Dict, share_info: Dict, 
                               download_hash: Optional[str] = None) -> bool:
        """
        发送分享通知（完全复制my_115_app的send_telegram_notification）
        
        :param task_info: 任务信息
        :param share_info: 分享信息
        :param download_hash: 下载hash（必需）
        :return: 是否成功
        """
        if not self.bot_token or not self.chat_id:
            return False
        
        if not download_hash:
            logger.warning("【Enhanced115】缺少download_hash，无法构建完整通知")
            return False
        
        try:
            # 获取完整的通知上下文（完全复制my_115_app）
            task_context = self.get_notification_context(download_hash, task_info)
            
            caption_text = ""
            poster_url = task_context.get('image_url', '')
            title_for_log = task_info.get('media_title', '未知')
            
            # 使用notification_text（完全复制my_115_app的逻辑）
            if task_context.get('notification_text'):
                # 1. 获取包含占位符的原始文本
                raw_notification_text = task_context['notification_text']
                
                # 2. 先转义
                escaped_text = self._telegram_escape(raw_notification_text)
                
                # 3. 后替换占位符
                caption_text = escaped_text.replace(r"\_\_BOLD\_START\_\_", "*").replace(r"\_\_BOLD\_END\_\_", "*")
                
                # 4. 加空行
                caption_text += "\n\n"
            else:
                # 备用：简单格式
                logger.warning("【Enhanced115】未获取到notification_text，使用简单格式")
                media_title = task_info.get('media_title', '未知')
                share_mode = task_info.get('share_mode', 'file')
                mode_text = "文件夹分享" if share_mode == 'folder' else "文件打包分享"
                
                caption_text = f"*{self._telegram_escape(media_title)}*\n\n"
                caption_text += f"▪️ *{self._telegram_escape('模式')}*: `{mode_text}`\n\n"
            
            # 拼接分享链接（完全复制my_115_app）
            share_url = share_info.get("share_url", "")
            share_password = share_info.get("password", "")
            
            if share_password and share_password not in ["无", "无 (已尝试设置)"]:
                final_share_url = f"{share_url}?password={share_password}"
            else:
                final_share_url = share_url
            
            caption_text += f"▪️ *{self._telegram_escape('链接')}*: [{self._telegram_escape('点击转存')}]({final_share_url})"
            
            # 发送通知（完全复制my_115_app）
            import asyncio
            return asyncio.run(self._send_async(caption_text, poster_url, title_for_log))
            
        except Exception as e:
            logger.error(f"【Enhanced115】Telegram通知异常：{e}")
            return False
    
    async def _send_async(self, caption_text: str, poster_url: Optional[str], title_for_log: str) -> bool:
        """异步发送Telegram消息（完全复制my_115_app）"""
        try:
            import httpx
            
            async with httpx.AsyncClient(timeout=30) as client:
                if poster_url:
                    # 发送图片+文本
                    api_url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
                    payload = {
                        'chat_id': self.chat_id,
                        'photo': poster_url,
                        'caption': caption_text,
                        'parse_mode': 'MarkdownV2'
                    }
                else:
                    # 只发送文本
                    api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                    payload = {
                        'chat_id': self.chat_id,
                        'text': caption_text,
                        'parse_mode': 'MarkdownV2'
                    }
                
                response = await client.post(api_url, json=payload)
                
                if response.status_code == 200:
                    logger.info(f"【Enhanced115】成功为任务 '{title_for_log}' 发送Telegram通知")
                    return True
                else:
                    logger.error(f"【Enhanced115】发送Telegram通知失败：{response.text}")
                    logger.error(f"【Enhanced115】失败的Payload (已截断): {str(payload)[:500]}")
                    return False
                    
        except Exception as e:
            logger.error(f"【Enhanced115】发送Telegram通知时发生异常：{e}")
            return False
