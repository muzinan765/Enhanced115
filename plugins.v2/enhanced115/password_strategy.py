"""
密码策略模块
完全复制my_115_app的密码处理逻辑
"""
import random
import string
from typing import Optional

from app.log import logger


class PasswordStrategy:
    """密码策略处理"""
    
    @staticmethod
    def generate_password(strategy: str, value: str, initial_code: str = None) -> Optional[str]:
        """
        根据策略生成密码
        
        :param strategy: 策略类型
          - fixed: 固定密码
          - random_list: 列表随机
          - empty: 无密码
          - keep_initial: 保留初始
          - random_generate: 完全随机生成
        :param value: 密码值（fixed模式的密码，或列表的JSON字符串）
        :param initial_code: 115初始密码
        :return: 最终密码
        """
        try:
            if strategy == 'fixed':
                # 固定密码
                if value and len(value) == 4:
                    return value
                else:
                    logger.warning("【Enhanced115】固定密码长度不是4位，忽略")
                    return None
            
            elif strategy == 'random_list':
                # 列表随机
                import json
                try:
                    password_list = json.loads(value) if isinstance(value, str) else value
                    if isinstance(password_list, list):
                        valid_passwords = [p for p in password_list if isinstance(p, str) and len(p) == 4]
                        if valid_passwords:
                            chosen = random.choice(valid_passwords)
                            logger.debug(f"【Enhanced115】从列表随机选择密码：{chosen}")
                            return chosen
                        else:
                            logger.warning("【Enhanced115】列表中无有效4位密码")
                            return None
                except:
                    logger.error("【Enhanced115】解析密码列表失败")
                    return None
            
            elif strategy == 'empty':
                # 空密码
                return ""
            
            elif strategy == 'keep_initial':
                # 保留初始密码（不修改）
                return initial_code
            
            elif strategy == 'random_generate':
                # 完全随机生成
                return PasswordStrategy._generate_random_password(4)
            
            else:
                logger.warning(f"【Enhanced115】未知密码策略：{strategy}")
                return None
                
        except Exception as e:
            logger.error(f"【Enhanced115】生成密码失败：{e}")
            return None
    
    @staticmethod
    def _generate_random_password(length: int = 4) -> str:
        """
        生成完全随机密码
        由小写字母和数字组成
        """
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    
    @staticmethod
    def parse_password_config(config: dict) -> tuple:
        """
        解析密码配置
        :return: (strategy, value)
        """
        strategy = config.get('password_strategy', 'keep_initial')
        value = config.get('password_value', '')
        return strategy, value

