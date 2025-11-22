"""
Telegram通知模块
"""
from typing import Optional, Dict, Any

from app.log import logger


class TelegramNotifier:
    """Telegram通知处理类"""
    
    def __init__(self, bot_token: str, chat_id: str):
        """
        初始化Telegram通知器
        :param bot_token: Bot Token
        :param chat_id: Chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
    
    def send_share_notification(self, task: dict, share_info: dict) -> bool:
        """
        发送分享通知
        
        :param task: 上传任务信息
        :param share_info: 分享信息 {share_url, receive_code, ...}
        :return: 是否成功
        """
        if not self.bot_token or not self.chat_id:
            return False
        
        try:
            import requests
            
            mediainfo = task['mediainfo']
            meta = task['meta']
            
            # 构建消息
            title = mediainfo.title_year
            mtype = "电影" if mediainfo.type.value == '电影' else f"剧集 {meta.season or ''}"
            share_url = share_info.get('share_url', '')
            password = share_info.get('receive_code', '无')
            
            message = f"📺 *{title}* 已分享\\n\\n"
            message += f"类型：{mtype}\\n"
            message += f"链接：{share_url}\\n"
            message += f"提取码：{password}\\n"
            
            # 添加评分信息（如果有）
            if hasattr(mediainfo, 'vote_average') and mediainfo.vote_average:
                message += f"评分：⭐ {mediainfo.vote_average}\\n"
            
            # 发送消息
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': False
            }
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                logger.info("【Enhanced115】Telegram通知已发送")
                return True
            else:
                logger.error(f"【Enhanced115】Telegram通知发送失败：{response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"【Enhanced115】Telegram通知失败：{e}")
            return False

