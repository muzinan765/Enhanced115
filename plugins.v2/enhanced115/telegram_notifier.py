"""
Telegram通知模块（增强版）
参考my_115_app的notifier.py，适配MoviePilot插件环境
"""
import re
import math
from typing import Dict, Optional

from app.log import logger


class TelegramNotifier:
    """Telegram通知处理类（增强版）"""
    
    def __init__(self, bot_token: str, chat_id: str):
        """
        初始化Telegram通知器
        :param bot_token: Bot Token
        :param chat_id: Chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
    
    @staticmethod
    def _telegram_escape(text: str) -> str:
        """
        对文本进行Telegram MarkdownV2格式的转义
        完全复制my_115_app的逻辑
        """
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)
    
    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        """
        将字节大小格式化为人类可读的字符串
        完全复制my_115_app的逻辑
        """
        if size_bytes <= 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = min(int(math.floor(math.log(size_bytes, 1024))), len(size_name) - 1)
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s}{size_name[i]}"
    
    def _get_tmdb_poster(self, tmdb_id: int, is_movie: bool) -> Optional[str]:
        """
        从TMDB获取海报URL
        使用MoviePilot的TheMovieDbModule
        
        :param tmdb_id: TMDB ID
        :param is_movie: 是否电影
        :return: 海报URL或None
        """
        try:
            from app.modules.themoviedb import TheMovieDbModule
            
            tmdb_module = TheMovieDbModule()
            
            # 根据类型调用不同的API
            if is_movie:
                detail = tmdb_module.movie_detail(tmdbid=tmdb_id)
            else:
                detail = tmdb_module.tv_detail(tmdbid=tmdb_id)
            
            if detail and detail.get('poster_path'):
                # 返回w500大小的海报
                return f"https://image.tmdb.org/t/p/w500{detail['poster_path']}"
            
        except Exception as e:
            logger.debug(f"【Enhanced115】获取TMDB海报失败：{e}")
        
        return None
    
    def _get_total_size(self, download_hash: str) -> int:
        """
        获取任务的总文件大小
        
        :param download_hash: 下载hash
        :return: 总大小（字节）
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            total_size = 0
            for record in records:
                if record.dest_storage == 'u115' and record.dest_fileitem:
                    size = record.dest_fileitem.get('size', 0)
                    if isinstance(size, (int, float)):
                        total_size += int(size)
            
            return total_size
            
        except Exception as e:
            logger.debug(f"【Enhanced115】获取文件大小失败：{e}")
            return 0
    
    def send_share_notification(self, task_info: Dict, share_info: Dict, 
                               download_hash: Optional[str] = None) -> bool:
        """
        发送增强版分享通知
        
        改进：
        1. ✅ 添加TMDB海报图片
        2. ✅ MarkdownV2格式化
        3. ✅ 显示文件总大小
        4. ✅ 更美观的消息格式
        
        :param task_info: 任务信息
        :param share_info: 分享信息
        :param download_hash: 下载hash（可选，用于获取文件大小）
        :return: 是否成功
        """
        if not self.bot_token or not self.chat_id:
            return False
        
        try:
            import httpx
            
            # 基础信息
            media_title = task_info.get('media_title', '未知')
            share_mode = task_info.get('share_mode', 'file')
            tmdb_id = task_info.get('tmdb_id', 0)
            is_movie = task_info.get('is_movie', False)
            share_url = share_info.get('share_url', '')
            password = share_info.get('password', '')
            
            # 构建标题
            media_type = "🎬 电影" if is_movie else "📺 剧集"
            title_line = f"*{self._telegram_escape(media_type)}｜{self._telegram_escape(media_title)}*"
            
            # 构建消息体
            message_lines = [title_line, ""]  # 标题后空一行
            
            # 添加分享模式
            mode_text = "文件夹分享" if share_mode == 'folder' else "文件打包分享"
            message_lines.append(f"▪️ *{self._telegram_escape('模式')}*: `{mode_text}`")
            
            # 添加文件大小（如果有download_hash）
            if download_hash:
                total_size = self._get_total_size(download_hash)
                if total_size > 0:
                    size_str = self._format_bytes(total_size)
                    message_lines.append(f"▪️ *{self._telegram_escape('大小')}*: `{size_str}`")
            
            # 空行
            message_lines.append("")
            
            # 添加分享链接
            final_share_url = f"{share_url}?password={password}" if password else share_url
            link_text = self._telegram_escape("点击转存")
            message_lines.append(f"▪️ *{self._telegram_escape('链接')}*: [{link_text}]({final_share_url})")
            
            # 合并消息
            caption_text = "\n".join(message_lines)
            
            # 尝试获取海报
            poster_url = None
            if tmdb_id and tmdb_id > 0:
                poster_url = self._get_tmdb_poster(tmdb_id, is_movie)
            
            # 发送通知
            import asyncio
            return asyncio.run(self._send_async(caption_text, poster_url))
            
        except Exception as e:
            logger.error(f"【Enhanced115】Telegram通知异常：{e}")
            return False
    
    async def _send_async(self, caption_text: str, poster_url: Optional[str]) -> bool:
        """
        异步发送Telegram消息
        
        :param caption_text: 消息文本
        :param poster_url: 海报URL（可选）
        :return: 是否成功
        """
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
                    logger.info("【Enhanced115】Telegram通知发送成功")
                    return True
                else:
                    logger.error(f"【Enhanced115】Telegram发送失败：{response.status_code}, {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"【Enhanced115】Telegram发送异常：{e}")
            return False
