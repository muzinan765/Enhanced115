"""
任务管理模块 - 管理待处理任务
完全复制my_115_app的任务管理逻辑
"""
from typing import Dict, Any, Optional
import time

from app.log import logger


class TaskManager:
    """任务管理器"""
    
    def __init__(self, plugin_data_ops):
        """
        初始化任务管理器
        :param plugin_data_ops: 插件数据操作对象（用于save_data/get_data）
        """
        self.data_ops = plugin_data_ops
        self._task_key_prefix = "pending_task_"
    
    def create_task(self, download_hash: str, share_mode: str, expected_count: int,
                   tmdb_id: int, media_title: str, is_movie: bool, 
                   season: int = None, **kwargs) -> bool:
        """
        创建新任务
        
        :param download_hash: 下载hash（任务唯一标识）
        :param share_mode: 分享模式（folder/file）
        :param expected_count: 预期文件数
        :param tmdb_id: TMDB ID
        :param media_title: 媒体标题
        :param is_movie: 是否电影
        :param season: 季数（电视剧）
        :return: 是否成功创建
        """
        task_key = self._get_task_key(download_hash)
        
        # 检查任务是否已存在
        existing_task = self.data_ops.get_data(task_key)
        if existing_task:
            logger.warning(f"【Enhanced115】任务已存在：{media_title}，跳过")
            return False
        
        # 创建新任务
        new_task = {
            'download_hash': download_hash,
            'share_mode': share_mode,
            'expected_count': expected_count,
            'actual_count': 0,
            'tmdb_id': tmdb_id,
            'media_title': media_title,
            'is_movie': is_movie,
            'season': season,
            'creation_time': int(time.time()),
            'status': 'pending'
        }
        
        # 保存任务
        self.data_ops.save_data(task_key, new_task)
        
        logger.info(
            f"【Enhanced115】新任务：{media_title}，"
            f"模式={share_mode}，预期={expected_count}个文件"
        )
        
        return True
    
    def get_task(self, download_hash: str) -> Optional[Dict[str, Any]]:
        """获取任务"""
        task_key = self._get_task_key(download_hash)
        return self.data_ops.get_data(task_key)
    
    def update_task(self, download_hash: str, updates: dict):
        """更新任务"""
        task_key = self._get_task_key(download_hash)
        task = self.data_ops.get_data(task_key)
        
        if task:
            task.update(updates)
            self.data_ops.save_data(task_key, task)
    
    def increment_actual_count(self, download_hash: str):
        """增加实际完成数量"""
        task = self.get_task(download_hash)
        if task:
            task['actual_count'] = task.get('actual_count', 0) + 1
            task_key = self._get_task_key(download_hash)
            self.data_ops.save_data(task_key, task)
            
            logger.debug(
                f"【Enhanced115】任务进度更新：{task['media_title']}，"
                f"{task['actual_count']}/{task['expected_count']}"
            )
    
    def is_task_complete(self, download_hash: str) -> bool:
        """检查任务是否完成"""
        task = self.get_task(download_hash)
        if not task:
            return False
        
        return task.get('actual_count', 0) >= task.get('expected_count', 0)
    
    def remove_task(self, download_hash: str):
        """移除任务"""
        task_key = self._get_task_key(download_hash)
        task = self.data_ops.get_data(task_key)
        
        if task:
            logger.info(f"【Enhanced115】移除已完成任务：{task.get('media_title')}")
            self.data_ops.del_data(task_key)
    
    def get_all_pending_tasks(self) -> Dict[str, Any]:
        """获取所有待处理任务"""
        # 获取所有以task_前缀开头的数据
        all_data = self.data_ops.get_data() or {}
        
        pending_tasks = {}
        for key, value in all_data.items():
            if key.startswith(self._task_key_prefix):
                download_hash = key[len(self._task_key_prefix):]
                if isinstance(value, dict) and value.get('status') == 'pending':
                    pending_tasks[download_hash] = value
        
        return pending_tasks
    
    def _get_task_key(self, download_hash: str) -> str:
        """生成任务key"""
        return f"{self._task_key_prefix}{download_hash}"

