"""
任务管理模块 - 管理待处理任务
完全复制my_115_app的任务管理逻辑
"""
from pathlib import Path
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
            'status': 'pending',
            'share_attempts': 0,
            'last_share_time': None,
            'last_fail_reason': '',
            'uploading_files': [],  # 正在上传的文件（持久化）
            'completed_files': [],  # 已完成的文件（持久化）
            'pending_cleanup': [],
            'notification_sent': False,
            'share_history': [],
            'retry_count': 0  # 重试次数
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
    
    def mark_uploading(self, download_hash: str, file_path: str):
        """
        标记文件正在上传（上传开始时调用）
        
        :param download_hash: 任务hash
        :param file_path: 文件路径
        """
        task = self.get_task(download_hash)
        if task:
            uploading = set(task.get('uploading_files') or [])
            uploading.add(file_path)
            task['uploading_files'] = list(uploading)
            self.update_task(download_hash, {'uploading_files': task['uploading_files']})
            logger.debug(f"【Enhanced115】标记正在上传：{Path(file_path).name}")
    
    def mark_completed(self, download_hash: str, file_path: str):
        """
        标记文件已完成（上传成功后调用）
        
        :param download_hash: 任务hash
        :param file_path: 文件路径
        """
        task = self.get_task(download_hash)
        if task:
            # 从uploading移除
            uploading = set(task.get('uploading_files') or [])
            uploading.discard(file_path)
            
            # 加入completed
            completed = set(task.get('completed_files') or [])
            completed.add(file_path)
            
            # 更新计数
            task['actual_count'] = len(completed)
            task['uploading_files'] = list(uploading)
            task['completed_files'] = list(completed)
            
            self.update_task(download_hash, {
                'actual_count': task['actual_count'],
                'uploading_files': task['uploading_files'],
                'completed_files': task['completed_files']
            })
            
            logger.debug(
                f"【Enhanced115】任务进度更新：{task['media_title']}，"
                f"{task['actual_count']}/{task['expected_count']}"
            )
    
    def mark_upload_failed(self, download_hash: str, file_path: str):
        """
        标记上传失败（从uploading中移除）
        
        :param download_hash: 任务hash
        :param file_path: 文件路径
        """
        task = self.get_task(download_hash)
        if task:
            uploading = set(task.get('uploading_files') or [])
            uploading.discard(file_path)
            task['uploading_files'] = list(uploading)
            self.update_task(download_hash, {'uploading_files': task['uploading_files']})
            logger.debug(f"【Enhanced115】标记上传失败：{Path(file_path).name}")
    
    def is_file_uploading(self, download_hash: str, file_path: str) -> bool:
        """
        检查文件是否正在上传
        
        :param download_hash: 任务hash
        :param file_path: 文件路径
        :return: 是否正在上传
        """
        task = self.get_task(download_hash)
        if not task:
            return False
        uploading_files = task.get('uploading_files', [])
        return file_path in uploading_files
    
    def is_file_completed(self, download_hash: str, file_path: str) -> bool:
        """
        检查文件是否已完成
        
        :param download_hash: 任务hash
        :param file_path: 文件路径
        :return: 是否已完成
        """
        task = self.get_task(download_hash)
        if not task:
            return False
        completed_files = task.get('completed_files', [])
        return file_path in completed_files
    
    def clear_uploading_on_startup(self):
        """
        程序启动时清空所有uploading状态
        
        简单粗暴的策略：
        - 清空所有uploading状态
        - 依赖扫描机制自动恢复未完成的任务
        - 可能导致偶尔的重复上传（秒传很快，影响小）
        """
        all_tasks = self.get_all_pending_tasks()
        cleared_count = 0
        
        for download_hash, task in all_tasks.items():
            uploading_files = task.get('uploading_files', [])
            if uploading_files:
                logger.info(
                    f"【Enhanced115】清理uploading状态："
                    f"{task['media_title']}，{len(uploading_files)}个文件"
                )
                self.update_task(download_hash, {'uploading_files': []})
                cleared_count += len(uploading_files)
        
        if cleared_count > 0:
            logger.info(
                f"【Enhanced115】已清理{cleared_count}个uploading状态，"
                f"未完成的任务将在扫描时自动恢复"
            )
    
    def append_cleanup_targets(self, download_hash: str, paths: list):
        """记录待清理的旧文件（STRM/字幕）"""
        if not paths:
            return
        task = self.get_task(download_hash)
        if not task:
            return
        existing = set(task.get('pending_cleanup') or [])
        for p in paths:
            if p:
                existing.add(str(p))
        task['pending_cleanup'] = list(existing)
        self.update_task(download_hash, {'pending_cleanup': task['pending_cleanup']})
    
    def clear_cleanup_targets(self, download_hash: str):
        """清空待清理列表"""
        self.update_task(download_hash, {'pending_cleanup': []})
    
    def record_share_attempt(self, download_hash: str, success: bool, fail_reason: str = ''):
        """记录分享结果"""
        task = self.get_task(download_hash)
        if not task:
            return
        task.setdefault('share_history', [])
        history = task['share_history']
        history.append({
            'time': int(time.time()),
            'success': success,
            'reason': fail_reason
        })
        updates = {
            'share_attempts': task.get('share_attempts', 0) + 1,
            'last_share_time': int(time.time()),
            'last_fail_reason': '' if success else fail_reason,
            'share_history': history
        }
        if success:
            updates['status'] = 'shared'
        self.update_task(download_hash, updates)
    
    def increment_retry_count(self, download_hash: str) -> int:
        """
        增加重试计数
        
        :param download_hash: 任务hash
        :return: 更新后的重试次数
        """
        task = self.get_task(download_hash)
        if not task:
            return 0
        
        retry_count = task.get('retry_count', 0) + 1
        self.update_task(download_hash, {'retry_count': retry_count})
        return retry_count
    
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
        # 注意：get_data()不带key时返回的是list of PluginData对象
        all_data = self.data_ops.get_data() or []
        
        pending_tasks = {}
        
        # 处理list格式（MoviePilot的get_data返回PluginData对象列表）
        if isinstance(all_data, list):
            for item in all_data:
                # item是PluginData对象，有key和value属性
                if hasattr(item, 'key') and hasattr(item, 'value'):
                    key = item.key
                    value = item.value
                    if key.startswith(self._task_key_prefix):
                        download_hash = key[len(self._task_key_prefix):]
                        if isinstance(value, dict) and value.get('status') == 'pending':
                            pending_tasks[download_hash] = value
        # 兼容dict格式（万一将来改变）
        elif isinstance(all_data, dict):
            for key, value in all_data.items():
                if key.startswith(self._task_key_prefix):
                    download_hash = key[len(self._task_key_prefix):]
                    if isinstance(value, dict) and value.get('status') == 'pending':
                        pending_tasks[download_hash] = value
        
        return pending_tasks
    
    def _get_task_key(self, download_hash: str) -> str:
        """生成任务key"""
        return f"{self._task_key_prefix}{download_hash}"
    
    def check_for_timeouts(self, timeout_hours: int = 24):
        """
        检查并清理超时任务（完全复制my_115_app逻辑）
        
        :param timeout_hours: 超时时间（小时）
        """
        all_tasks = self.get_all_pending_tasks()
        if not all_tasks:
            return
        
        current_time = int(time.time())
        timeout_seconds = timeout_hours * 3600
        tasks_to_remove = []
        
        for download_hash, task in all_tasks.items():
            creation_time = task.get('creation_time', current_time)
            if current_time - creation_time > timeout_seconds:
                tasks_to_remove.append(download_hash)
        
        if tasks_to_remove:
            for download_hash in tasks_to_remove:
                task = all_tasks[download_hash]
                media_title = task.get('media_title', '未知')
                logger.warning(
                    f"【Enhanced115】任务超时，将被清理："
                    f"{media_title}，已等待"
                    f"{(current_time - task.get('creation_time', current_time)) / 3600:.1f}小时"
                )
                self.remove_task(download_hash)
            
            logger.info(f"【Enhanced115】已清理{len(tasks_to_remove)}个超时任务")

