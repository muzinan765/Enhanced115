"""
Telegram通知模块
"""
from typing import Dict

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
    
    def send_share_notification(self, task_info: Dict, share_info: Dict) -> bool:
        """
        发送分享通知
        
        :param task_info: 任务信息
        :param share_info: 分享信息
        :return: 是否成功
        """
        if not self.bot_token or not self.chat_id:
            return False
        
        try:
            import requests
            
            media_title = task_info.get('media_title', '未知')
            share_mode = task_info.get('share_mode', 'file')
            share_url = share_info.get('share_url', '')
            receive_code = share_info.get('receive_code', '无')
            
            # 构建消息
            mode_text = "文件夹分享" if share_mode == 'folder' else "文件打包分享"
            
            message = f"📺 *{media_title}* 已分享\\n\\n"
            message += f"模式：{mode_text}\\n"
            message += f"链接：{share_url}\\n"
            message += f"提取码：{receive_code}\\n"
            
            # 发送
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                logger.info("【Enhanced115】Telegram通知已发送")
                return True
            else:
                logger.error(f"【Enhanced115】Telegram失败：{response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"【Enhanced115】Telegram通知异常：{e}")
            return False
