"""
Enhanced115 - 115网盘助手（完全集成my_115_app）

完整流程：
1. 监听DownloadComplete（下载完成）→ 智能判断并创建任务
2. 监听TransferComplete（整理完成）→ 上传+统计+判断是否完成
3. 所有文件完成后 → 自动分享
4. Telegram通知

智能判断逻辑（完全复制my_115_app）：
- 电影：固定folder模式
- 电视剧：分析episodes、种子描述、种子名称、消息记录
  三个条件（全集 AND 多集 AND 从第1集开始）→ folder
  否则 → file（单集、补集等）
"""
import queue
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any, Tuple
import time

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType

# 导入子模块
from .uploader import Upload115Handler
from .sharer import Share115Handler
from .database import DatabaseHandler
from .telegram_notifier import TelegramNotifier
from .task_analyzer import TaskAnalyzer
from .task_manager import TaskManager
from .password_strategy import PasswordStrategy
from .strm_manager import StrmManager
from .utils import map_local_to_remote, parse_path_mappings


class Enhanced115(_PluginBase):
    # 插件基本信息
    plugin_name = "Enhanced115网盘助手"
    plugin_desc = "硬链接+多线程上传+智能分享（完全集成my_115_app逻辑）"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/cloud.png"
    plugin_version = "2.0.0"
    plugin_author = "muzinan765"
    author_url = "https://github.com/muzinan765/Enhanced115"
    plugin_config_prefix = "enhanced115_"
    plugin_order = 1
    auth_level = 2
    
    def __init__(self):
        super().__init__()
        
        # 配置
        self._enabled = False
        self._p115_cookies = None
        self._upload_threads = 3
        self._path_mappings = []
        
        # 分享配置
        self._share_enabled = False
        self._share_modify_enabled = True  # 是否修改分享设置
        self._file_duration = 15  # file模式有效期
        self._folder_duration = -1  # folder模式有效期
        self._password_strategy = 'keep_initial'  # 密码策略
        self._password_value = ''  # 密码值
        self._receive_user_limit = 0  # 接收次数限制
        self._skip_login_enabled = False  # 免登录下载
        self._skip_login_limit = ''  # 流量限制
        self._access_user_ids = ''  # 指定接收者
        
        # Telegram配置
        self._telegram_enabled = False
        self._telegram_bot_token = None
        self._telegram_chat_id = None
        
        # 115根目录配置
        self._movie_root_cid = None
        self._tv_root_cid = None
        
        # 删除配置
        self._delete_after_upload = False  # 上传后删除本地文件
        self._scan_interval = 1800  # 扫描间隔（秒）
        
        # STRM配置
        self._strm_enabled = False  # 是否启用strm管理
        self._emby_local_path = "/Emby"  # 本地Emby目录路径
        self._strm_overwrite_mode = "auto"  # strm覆盖模式：never/always/auto
        
        # 处理器
        self._p115_client = None
        self._uploader = None
        self._sharer = None
        self._telegram = None
        self._task_manager = None
        self._strm_manager = None
        
        # 上传队列
        self._upload_queue = queue.Queue()
        self._upload_executor = None
        self._stop_event = threading.Event()
        
        # 统计
        self._stats = {
            'total_tasks': 0,
            'uploaded': 0,
            'shared': 0,
            'failed': 0,
            'queue_size': 0
        }

    def init_plugin(self, config: dict = None):
        """初始化插件"""
        if not config:
            return
        
        # 基础配置
        self._enabled = config.get("enabled", False)
        self._p115_cookies = config.get("p115_cookies", "")
        self._upload_threads = int(config.get("upload_threads", 3))
        self._path_mappings = parse_path_mappings(config.get("path_mappings", ""))
        
        # 分享配置（完整）
        self._share_enabled = config.get("share_enabled", False)
        self._share_modify_enabled = config.get("share_modify_enabled", True)
        self._file_duration = int(config.get("file_duration", 15))
        self._folder_duration = int(config.get("folder_duration", -1))
        self._password_strategy = config.get("password_strategy", "keep_initial")
        self._password_value = config.get("password_value", "")
        self._receive_user_limit = int(config.get("receive_user_limit", 0))
        self._skip_login_enabled = config.get("skip_login_enabled", False)
        self._skip_login_limit = config.get("skip_login_limit", "")
        self._access_user_ids = config.get("access_user_ids", "")
        self._movie_root_cid = config.get("movie_root_cid", "")
        self._tv_root_cid = config.get("tv_root_cid", "")
        
        # Telegram配置
        self._telegram_enabled = config.get("telegram_enabled", False)
        self._telegram_bot_token = config.get("telegram_bot_token", "")
        self._telegram_chat_id = config.get("telegram_chat_id", "")
        
        # 删除配置
        self._delete_after_upload = config.get("delete_after_upload", False)
        self._scan_interval = int(config.get("scan_interval", 1800))
        
        # STRM配置
        self._strm_enabled = config.get("strm_enabled", False)
        self._emby_local_path = config.get("emby_local_path", "/Emby")
        self._strm_overwrite_mode = config.get("strm_overwrite_mode", "auto")
        
        # 停止旧服务
        self.stop_service()
        
        if not self._enabled:
            logger.info("【Enhanced115】插件未启用")
            return
        
        # 初始化115客户端
        if not self._p115_cookies:
            logger.error("【Enhanced115】未配置115 Cookies")
            return
        
        try:
            self._init_p115_client()
            
            # 初始化处理器
            self._uploader = Upload115Handler(self._p115_client)
            self._task_manager = TaskManager(self)
            
            if self._share_enabled:
                share_config = {
                    'share_modify_enabled': self._share_modify_enabled,
                    'file_duration': self._file_duration,
                    'folder_duration': self._folder_duration,
                    'password_strategy': self._password_strategy,
                    'password_value': self._password_value,
                    'receive_user_limit': self._receive_user_limit,
                    'skip_login_enabled': self._skip_login_enabled,
                    'skip_login_limit': self._skip_login_limit,
                    'access_user_ids': self._access_user_ids,
                    'movie_root_cid': self._movie_root_cid,
                    'tv_root_cid': self._tv_root_cid
                }
                self._sharer = Share115Handler(self._p115_client, share_config)
            
            if self._telegram_enabled:
                self._telegram = TelegramNotifier(
                    self._telegram_bot_token,
                    self._telegram_chat_id
                )
            
            # 初始化STRM管理器
            if self._strm_enabled:
                self._strm_manager = StrmManager(
                    self._p115_client,
                    self._emby_local_path,
                    self._strm_overwrite_mode
                )
                logger.info("【Enhanced115】STRM管理器已初始化")
            
            # 启动上传队列
            self._start_upload_workers()
            
            logger.info("【Enhanced115】插件初始化完成（完全集成my_115_app逻辑）")
            
        except Exception as e:
            logger.error(f"【Enhanced115】插件初始化失败：{e}")

    def _init_p115_client(self):
        """初始化p115客户端"""
        try:
            from p115client import P115Client
            
            self._p115_client = P115Client(
                self._p115_cookies,
                check_for_relogin=True
            )
            
            user_id = self._p115_client.user_id
            user_key = self._p115_client.user_key
            
            if user_id and user_key:
                logger.info(f"【Enhanced115】115登录成功，User ID：{user_id}")
            else:
                raise Exception("无法获取用户ID或Key")
                
        except ImportError:
            raise Exception("p115client库未安装")
        except Exception as e:
            raise Exception(f"115客户端初始化失败：{str(e)}")

    def _start_upload_workers(self):
        """启动上传工作线程"""
        self._stop_event.clear()
        self._upload_executor = ThreadPoolExecutor(
            max_workers=self._upload_threads,
            thread_name_prefix="Enhanced115-Upload"
        )
        
        for i in range(self._upload_threads):
            self._upload_executor.submit(self._upload_worker)
        
        logger.info(f"【Enhanced115】已启动{self._upload_threads}个上传工作线程")

    @eventmanager.register(EventType.DownloadAdded)
    def on_download_added(self, event: Event):
        """
        监听下载添加事件 → 创建任务
        完全复制my_115_app的find_new_tasks逻辑
        """
        if not self._enabled:
            return
        
        try:
            event_data = event.event_data
            download_hash = event_data.get('hash')
            
            if not download_hash:
                return
            
            # 检查是否已处理
            existing_task = self._task_manager.get_task(download_hash)
            if existing_task:
                logger.debug(f"【Enhanced115】任务已存在，跳过：{download_hash}")
                return
            
            # 从downloadhistory表查询完整信息
            from app.db.downloadhistory_oper import DownloadHistoryOper
            
            download_oper = DownloadHistoryOper()
            download_history = download_oper.get_by_hash(download_hash)
            
            if not download_history:
                logger.debug(f"【Enhanced115】未找到下载记录：{download_hash}")
                return
            
            # 查询message表获取文本（用于判断"完结"）
            message_text = TaskAnalyzer.query_message_text(download_history)
            
            # 智能判断分享模式（核心逻辑）
            share_mode, expected_count = TaskAnalyzer.analyze_share_mode(
                download_history,
                message_text
            )
            
            if not share_mode or expected_count == 0:
                logger.debug("【Enhanced115】无法判断分享模式，跳过")
                return
            
            # 创建任务
            self._task_manager.create_task(
                download_hash=download_hash,
                share_mode=share_mode,
                expected_count=expected_count,
                tmdb_id=download_history.tmdbid or 0,
                media_title=f"{download_history.title} ({download_history.year})",
                is_movie=(download_history.type == '电影'),
                season=download_history.seasons
            )
            
            self._stats['total_tasks'] += 1
            
        except Exception as e:
            logger.error(f"【Enhanced115】处理DownloadAdded事件失败：{e}")

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event):
        """
        监听整理完成事件 → 上传并检查是否所有文件完成
        完全复制my_115_app的check_completed_tasks逻辑
        """
        if not self._enabled or not self._p115_client:
            return
        
        try:
            event_data = event.event_data
            transferinfo = event_data.get('transferinfo')
            download_hash = event_data.get('download_hash')
            
            if not transferinfo or not transferinfo.target_item:
                return
            
            if transferinfo.target_item.storage != 'local':
                return
            
            # 如果没有download_hash（手动整理或重新整理），通过savepath + episodes匹配
            if not download_hash:
                try:
                    from app.db.transferhistory_oper import TransferHistoryOper
                    from app.db.downloadhistory_oper import DownloadHistoryOper
                    
                    transferhis = TransferHistoryOper()
                    # 用dest路径查询当前成功记录
                    record = transferhis.get_by_dest(transferinfo.target_item.path)
                    
                    if record:
                        # 先尝试直接获取download_hash
                        if record.download_hash:
                            download_hash = record.download_hash
                            logger.info(f"【Enhanced115】从记录恢复download_hash：{download_hash[:8]}...")
                        else:
                            # download_hash为空，通过savepath + episodes匹配
                            src_fileitem = record.src_fileitem
                            episodes = record.episodes
                            
                            if src_fileitem and isinstance(src_fileitem, dict) and episodes:
                                original_src_path = src_fileitem.get('path')
                                
                                if original_src_path:
                                    # 提取种子目录（savepath）
                                    savepath = str(Path(original_src_path).parent)
                                    
                                    # 查询这个种子的所有文件
                                    download_oper = DownloadHistoryOper()
                                    download_files = download_oper.get_files_by_savepath(savepath)
                                    
                                    if download_files:
                                        # 在文件列表中匹配episodes
                                        for df in download_files:
                                            # 检查文件名是否包含episodes
                                            if episodes in df.filepath or episodes in df.fullpath:
                                                # 验证这个download_hash在pending_tasks中
                                                pending_tasks = self._task_manager.get_all_pending_tasks()
                                                if df.download_hash in pending_tasks:
                                                    download_hash = df.download_hash
                                                    logger.info(
                                                        f"【Enhanced115】通过savepath+episodes匹配到download_hash："
                                                        f"{download_hash[:8]}...，文件：{transferinfo.target_item.name}"
                                                    )
                                                    break
                            
                            if not download_hash:
                                logger.debug(f"【Enhanced115】无法匹配download_hash，跳过")
                                return
                    else:
                        logger.debug(f"【Enhanced115】无法查询到整理记录，跳过")
                        return
                except Exception as e:
                    logger.warning(f"【Enhanced115】查询download_hash失败：{e}")
                    return
            
            # 检查是否有对应的任务
            task = self._task_manager.get_task(download_hash)
            if not task:
                # 没有任务记录，可能不是需要分享的下载
                logger.debug(f"【Enhanced115】无对应任务，跳过：{download_hash}")
                return
            
            # 映射路径
            local_path = transferinfo.target_item.path
            remote_path = map_local_to_remote(local_path, self._path_mappings)
            
            if not remote_path:
                logger.warning(f"【Enhanced115】路径映射失败：{local_path}")
                return
            
            # 构建上传任务
            upload_task = {
                'local_path': Path(local_path),
                'remote_path': remote_path,
                'download_hash': download_hash,
                'task_info': task,
                'fileitem': event_data.get('fileitem'),
                'meta': event_data.get('meta'),
                'mediainfo': event_data.get('mediainfo'),
            }
            
            # 加入上传队列
            self._upload_queue.put(upload_task)
            self._stats['queue_size'] = self._upload_queue.qsize()
            
            logger.info(
                f"【Enhanced115】加入上传队列：{transferinfo.target_item.name}，"
                f"任务：{task['media_title']} ({task['actual_count']}/{task['expected_count']})"
            )
            
        except Exception as e:
            logger.error(f"【Enhanced115】处理TransferComplete事件失败：{e}")

    def _upload_worker(self):
        """上传工作线程"""
        from pathlib import Path
        
        while not self._stop_event.is_set():
            try:
                task = self._upload_queue.get(timeout=1)
            except queue.Empty:
                continue
            
            if not task:
                continue
            
            try:
                self._process_upload_task(task)
            except Exception as e:
                logger.error(f"【Enhanced115】任务处理异常：{e}")
                self._stats['failed'] += 1
            finally:
                self._upload_queue.task_done()
                self._stats['queue_size'] = self._upload_queue.qsize()

    def _process_upload_task(self, upload_task: dict):
        """处理上传任务"""
        local_path = upload_task['local_path']
        remote_path = upload_task['remote_path']
        download_hash = upload_task['download_hash']
        task_info = upload_task['task_info']
        filename = local_path.name
        
        # 提取src_path（兼容dict和对象）
        fileitem = upload_task['fileitem']
        if isinstance(fileitem, dict):
            src_path = fileitem['path']
        else:
            src_path = fileitem.path
        
        # 1. 记录已完成文件
        if self._task_manager:
            self._task_manager.increment_actual_count(download_hash, str(local_path))
        
        # 2. 检查是否是替换操作（洗版）
        # 如果启用strm，使用strm方式检测；否则使用数据库方式
        old_version_count = 0
        if self._strm_enabled and self._strm_manager:
            # STRM模式：检查旧版本strm（不删除，等上传成功后删除）
            is_movie = task_info.get('is_movie', False)
            old_version_count = self._strm_manager.check_and_delete_old_version(remote_path, is_movie)
        else:
            # 传统模式：通过数据库检测并删除
            old_file_id = self._check_and_delete_old_file(src_path)
            if old_file_id:
                logger.info(f"【Enhanced115】检测到替换操作，已删除115上的旧文件：{filename}")
        
        # 3. 上传到115
        success, file_info = self._uploader.upload_file(local_path, remote_path, filename)
        
        if not success:
            logger.error(f"【Enhanced115】上传失败：{filename}")
            self._stats['failed'] += 1
            return
        
        # 4. 更新数据库（local→u115）
        # ⚠️ 关键：传入src_path，只更新当前文件的记录
        # src_path已在上面提取
        db_updated = DatabaseHandler.update_transfer_record(
            src_path,
            download_hash,
            remote_path,
            file_info
        )
        
        if db_updated:
            self._stats['uploaded'] += 1
            logger.info(f"【Enhanced115】上传并更新数据库成功：{filename}")
            
            # STRM功能：生成strm文件
            if self._strm_enabled and self._strm_manager:
                # 删除115上的旧版本（如果有）
                if old_version_count > 0:
                    deleted_count = self._strm_manager.delete_pending_old_versions()
                    if deleted_count > 0:
                        logger.info(f"【Enhanced115】已删除{deleted_count}个旧版本")
                
                # 生成新strm
                is_movie = task_info.get('is_movie', False)
                self._strm_manager.handle_upload_success(local_path, remote_path, file_info, is_movie)
            
            # 上传成功后删除本地文件（如果配置开启）
            if self._delete_after_upload:
                try:
                    if local_path.exists():
                        local_path.unlink()
                        logger.info(f"【Enhanced115】已删除本地文件：{filename}")
                except Exception as del_err:
                    logger.warning(f"【Enhanced115】删除本地文件失败：{filename}，错误：{del_err}")
        else:
            logger.warning(f"【Enhanced115】数据库更新失败：{filename}")
            return
        
        # 5. 查询数据库真实完成数量（不用内存计数）
        actual_count = self._count_completed_files(download_hash)
        expected_count = task_info.get('expected_count', 0)
        
        logger.info(
            f"【Enhanced115】任务进度：{task_info['media_title']}，"
            f"已完成={actual_count}/{expected_count}"
        )
        
        # 6. 检查任务是否完成（基于数据库真实count）
        if actual_count >= expected_count:
            logger.info(
                f"【Enhanced115】任务完成：{task_info['media_title']}，"
                f"开始分享（模式={task_info['share_mode']}）"
            )
            
            # 5. 创建分享
            if self._share_enabled and self._sharer:
                current_task = self._task_manager.get_task(download_hash)
                if not current_task:
                    logger.warning(f"【Enhanced115】任务不存在，跳过分享：{download_hash}")
                    return
                
                if current_task.get('status') != 'pending':
                    logger.info(
                        f"【Enhanced115】任务已进入{current_task.get('status')}状态，"
                        f"跳过重复分享：{current_task.get('media_title')}"
                    )
                    return
                
                self._task_manager.update_task(
                    download_hash,
                    {
                        'status': 'sharing',
                        'last_share_request': int(time.time())
                    }
                )
                
                share_result = self._sharer.create_share(
                    current_task,
                    download_hash,
                    upload_task.get('mediainfo')
                )
                
                if share_result:
                    self._stats['shared'] += 1
                    self._task_manager.record_share_attempt(download_hash, True)
                    
                    # 6. Telegram通知（增强版：传递download_hash获取文件大小）
                    if self._telegram_enabled and self._telegram:
                        self._telegram.send_share_notification(
                            current_task,
                            share_result,
                            download_hash
                        )
                    
                    # 7. 分享成功才移除任务
                    self._task_manager.remove_task(download_hash)
                    logger.info(f"【Enhanced115】任务已完成并移除：{task_info['media_title']}")
                else:
                    # 分享失败，保留任务，等待下次重试
                    logger.warning(f"【Enhanced115】分享失败，任务保留：{task_info['media_title']}")
                    self._task_manager.record_share_attempt(
                        download_hash,
                        False,
                        fail_reason="share_failed"
                    )
                    self._task_manager.update_task(download_hash, {'status': 'pending'})
            else:
                # 未启用分享，直接移除任务
                self._task_manager.remove_task(download_hash)

    def _check_pending_tasks(self):
        """
        定时检查所有待处理任务（核心自愈机制）
        完全复制my_115_app的check_completed_tasks逻辑
        
        功能：
        1. 获取所有pending任务
        2. 查询数据库真实完成数量（不依赖内存count）
        3. 对比expected_count，达到则触发分享
        4. 程序重启后会自动恢复pending任务
        """
        if not self._enabled or not self._p115_client:
            return
        
        try:
            # 获取所有pending任务
            pending_tasks = self._task_manager.get_all_pending_tasks()
            
            if not pending_tasks:
                logger.debug("【Enhanced115】定时检查：无待处理任务")
                return
            
            logger.info(f"【Enhanced115】定时检查：发现{len(pending_tasks)}个待处理任务")
            
            for download_hash, task_info in pending_tasks.items():
                try:
                    # 查询数据库真实完成数量
                    actual_count = self._count_completed_files(download_hash)
                    expected_count = task_info.get('expected_count', 0)
                    share_mode = task_info.get('share_mode', 'unknown')
                    media_title = task_info.get('media_title', '未知')
                    
                    # 获取episodes信息（直接从downloadhistory）
                    episodes_info = self._get_episodes_from_downloadhistory(download_hash)
                    
                    # 判断是否完成
                    if actual_count >= expected_count:
                        logger.info(
                            f"【Enhanced115】定时检查发现完成任务 | "
                            f"{media_title} {episodes_info} | "
                            f"模式={share_mode} | "
                            f"已完成{actual_count}/{expected_count}集 | "
                            f"准备分享"
                        )
                        
                        # 触发分享
                        self._trigger_share(download_hash, task_info)
                    else:
                        logger.debug(
                            f"【Enhanced115】定时检查 | "
                            f"{media_title} {episodes_info} | "
                            f"模式={share_mode} | "
                            f"进度={actual_count}/{expected_count}"
                        )
                        
                except Exception as e:
                    logger.error(f"【Enhanced115】检查任务{download_hash}时出错：{e}")
                    
        except Exception as e:
            logger.error(f"【Enhanced115】定时检查异常：{e}")

    def _count_completed_files(self, download_hash: str) -> int:
        """
        查询数据库真实完成数量
        完全复制my_115_app的逻辑：SELECT COUNT(*) FROM transferhistory
        
        优势：
        - 不依赖内存计数（准确）
        - 程序重启后依然正确
        - 避免并发问题
        
        :param download_hash: 下载hash
        :return: 已上传到115的文件数量
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            # 统计dest_storage='u115'的记录数
            count = sum(1 for record in records 
                       if record.dest_storage == 'u115' and record.status)
            
            return count
            
        except Exception as e:
            logger.error(f"【Enhanced115】统计完成文件数失败：{e}")
            return 0
    
    def _get_episodes_from_downloadhistory(self, download_hash: str) -> str:
        """
        从downloadhistory获取episodes字段（任务的集数信息）
        
        :param download_hash: 下载hash
        :return: episodes字符串（如"E01-E16"、"E08"等）
        """
        try:
            from app.db.downloadhistory_oper import DownloadHistoryOper
            
            download_oper = DownloadHistoryOper()
            download_history = download_oper.get_by_hash(download_hash)
            
            if download_history and download_history.episodes:
                return download_history.episodes
            
            return ""
            
        except Exception as e:
            logger.debug(f"【Enhanced115】获取episodes信息失败：{e}")
            return ""
    
    def _check_and_delete_old_file(self, src_path: str) -> Optional[str]:
        """
        检查是否是替换操作（洗版），如果是则删除115上的旧文件
        
        :param src_path: 源文件路径
        :return: 旧文件的fileid（如果删除成功）
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            transferhis = TransferHistoryOper()
            
            # 查询是否已有记录
            existing_record = transferhis.get_by_src(src_path, storage='local')
            
            # 如果记录存在且已上传到115，说明这是替换操作
            if existing_record and existing_record.dest_storage == 'u115':
                dest_fileitem = existing_record.dest_fileitem
                
                if dest_fileitem and isinstance(dest_fileitem, dict):
                    old_fileid = dest_fileitem.get('fileid')
                    
                    if old_fileid:
                        logger.info(f"【Enhanced115】检测到替换操作，旧文件ID：{old_fileid}")
                        
                        # 删除115上的旧文件
                        try:
                            delete_result = self._p115_client.fs_delete(old_fileid)
                            if delete_result and delete_result.get('state'):
                                logger.info(f"【Enhanced115】已删除115上的旧文件：{old_fileid}")
                                return old_fileid
                            else:
                                logger.warning(f"【Enhanced115】删除115旧文件失败：{delete_result}")
                        except Exception as del_err:
                            logger.error(f"【Enhanced115】删除115旧文件异常：{del_err}")
            
            return None
            
        except Exception as e:
            logger.error(f"【Enhanced115】检查旧文件失败：{e}")
            return None
    
    def _scan_and_clean_uploaded_files(self):
        """
        扫描/media目录，清理已上传的文件或重新上传未成功的文件
        
        逻辑：
        1. 扫描/media目录下的所有媒体文件
        2. 查询transferhistory表检查状态
        3. dest_storage='u115'且fileid存在 → 删除本地文件
        4. dest_storage='local'或fileid为null → 重新上传
        """
        if not self._enabled or not self._p115_client:
            return
        
        try:
            from pathlib import Path
            from app.db.transferhistory_oper import TransferHistoryOper
            
            logger.info("【Enhanced115】开始扫描/media目录...")
            
            # 获取/media路径（从path_mappings提取）
            media_paths = []
            for mapping in self._path_mappings:
                local_path = mapping.get('local')
                if local_path and 'media' in local_path.lower():
                    media_paths.append(Path(local_path))
            
            if not media_paths:
                logger.warning("【Enhanced115】未找到/media路径配置")
                return
            
            transferhis = TransferHistoryOper()
            deleted_count = 0
            reupload_count = 0
            
            for media_path in media_paths:
                if not media_path.exists():
                    continue
                
                # 递归扫描所有媒体文件
                video_exts = {'.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.iso'}
                for file_path in media_path.rglob('*'):
                    if not file_path.is_file():
                        continue
                    
                    if file_path.suffix.lower() not in video_exts:
                        continue
                    
                    # 查询数据库记录（文件在/media，但transferhistory记录的dest是/media的local路径）
                    # 注意：整理后的文件路径在dest字段，src是downloads路径
                    record = transferhis.get_by_dest(str(file_path))
                    
                    if not record:
                        continue
                    
                    # 检查上传状态
                    if record.dest_storage == 'u115':
                        # 检查是否真的上传成功（fileid存在）
                        dest_fileitem = record.dest_fileitem
                        if dest_fileitem and isinstance(dest_fileitem, dict):
                            fileid = dest_fileitem.get('fileid')
                            if fileid:
                                # 已上传成功，删除本地文件
                                try:
                                    file_path.unlink()
                                    deleted_count += 1
                                    logger.info(f"【Enhanced115】已删除已上传文件：{file_path.name}")
                                except Exception as del_err:
                                    logger.warning(f"【Enhanced115】删除文件失败：{file_path.name}，{del_err}")
                            else:
                                # fileid为null，是脏数据，需要重新上传
                                logger.info(f"【Enhanced115】发现脏数据（fileid=null），准备重新上传：{file_path.name}")
                                self._reupload_file(record, file_path)
                                reupload_count += 1
                        else:
                            # dest_fileitem为空，是脏数据
                            logger.info(f"【Enhanced115】发现脏数据（dest_fileitem=null），准备重新上传：{file_path.name}")
                            self._reupload_file(record, file_path)
                            reupload_count += 1
                    elif record.dest_storage == 'local':
                        # 未上传，重新上传
                        logger.info(f"【Enhanced115】发现未上传文件，准备上传：{file_path.name}")
                        self._reupload_file(record, file_path)
                        reupload_count += 1
            
            logger.info(
                f"【Enhanced115】扫描完成 | "
                f"已删除={deleted_count}个 | "
                f"重新上传={reupload_count}个"
            )
            
        except Exception as e:
            logger.error(f"【Enhanced115】扫描清理异常：{e}")
    
    def _reupload_file(self, record, file_path: Path):
        """
        重新上传文件
        
        :param record: transferhistory记录
        :param file_path: 本地文件路径
        """
        try:
            # 获取download_hash
            download_hash = record.download_hash
            
            # 如果download_hash为null，通过savepath + episodes匹配
            if not download_hash:
                src_fileitem = record.src_fileitem
                episodes = record.episodes
                
                if src_fileitem and isinstance(src_fileitem, dict) and episodes:
                    original_src_path = src_fileitem.get('path')
                    
                    if original_src_path:
                        from app.db.downloadhistory_oper import DownloadHistoryOper
                        from pathlib import Path
                        
                        # 提取种子目录（savepath）
                        savepath = str(Path(original_src_path).parent)
                        
                        # 查询这个种子的所有文件
                        download_oper = DownloadHistoryOper()
                        download_files = download_oper.get_files_by_savepath(savepath)
                        
                        if download_files:
                            # 在文件列表中匹配episodes
                            for df in download_files:
                                # 检查文件名是否包含episodes
                                if episodes in df.filepath or episodes in df.fullpath:
                                    # 验证这个download_hash在pending_tasks中
                                    pending_tasks = self._task_manager.get_all_pending_tasks()
                                    if df.download_hash in pending_tasks:
                                        download_hash = df.download_hash
                                        logger.info(
                                            f"【Enhanced115】通过savepath+episodes匹配到download_hash："
                                            f"{download_hash[:8]}...，文件：{file_path.name}"
                                        )
                                        break
            
            # 如果还是没有download_hash，无法处理
            if not download_hash:
                logger.debug(f"【Enhanced115】无法匹配download_hash，跳过：{file_path.name}")
                return
            
            # 获取任务信息
            task = self._task_manager.get_task(download_hash)
            
            if not task:
                # 任务已移除，说明已完成并分享
                # 检查文件是否真的已上传到115
                if record.dest_storage == 'u115':
                    dest_fileitem = record.dest_fileitem
                    if dest_fileitem and isinstance(dest_fileitem, dict) and dest_fileitem.get('fileid'):
                        # 已上传，删除本地文件
                        try:
                            file_path.unlink()
                            logger.info(f"【Enhanced115】任务已完成，删除已上传文件：{file_path.name}")
                        except Exception as del_err:
                            logger.warning(f"【Enhanced115】删除文件失败：{file_path.name}，{del_err}")
                    else:
                        # fileid不存在但任务已完成，说明是历史遗留问题
                        # 尝试删除本地文件（任务已完成说明已分享，应该已上传）
                        try:
                            file_path.unlink()
                            logger.info(f"【Enhanced115】任务已完成（清理遗留文件）：{file_path.name}")
                        except Exception as del_err:
                            logger.warning(f"【Enhanced115】删除文件失败：{file_path.name}，{del_err}")
                else:
                    # dest_storage='local'但任务已完成
                    # 说明文件还没上传，但任务已分享（可能是脏数据或count统计错了）
                    logger.warning(
                        f"【Enhanced115】任务已完成但记录显示未上传（数据异常），"
                        f"删除本地文件：{file_path.name}"
                    )
                    try:
                        file_path.unlink()
                    except Exception as del_err:
                        logger.warning(f"【Enhanced115】删除文件失败：{file_path.name}，{del_err}")
                return
            
            # 去重检查：文件是否已在处理中（已加入队列或正在上传）
            completed_files = task.get('completed_files', [])
            file_key = str(file_path)
            
            if file_key in completed_files:
                # 双重验证：检查数据库状态
                # 如果在completed_files中但数据库显示未上传，说明是中断任务
                if record.dest_storage == 'u115':
                    # 数据库确认已上传，真的在处理中或已完成
                    logger.debug(f"【Enhanced115】文件已上传，跳过重复添加：{file_path.name}")
                    return
                else:
                    # 在completed_files中但数据库显示未上传，说明上传中断了
                    # 清理completed_files，允许重新上传
                    logger.info(f"【Enhanced115】检测到中断任务，清理并重新上传：{file_path.name}")
                    completed_files.remove(file_key)
                    task['completed_files'] = completed_files
                    self._task_manager.update_task(download_hash, {'completed_files': completed_files})
                    # 继续执行后面的上传逻辑
            
            # 映射远程路径
            remote_path = map_local_to_remote(str(file_path), self._path_mappings)
            if not remote_path:
                logger.warning(f"【Enhanced115】路径映射失败：{file_path}")
                return
            
            # 构建上传任务
            upload_task = {
                'local_path': file_path,
                'remote_path': remote_path,
                'download_hash': download_hash,
                'task_info': task,
                'fileitem': {'path': record.src},  # 从记录重建fileitem
                'meta': None,
                'mediainfo': None,
            }
            
            # 加入上传队列
            self._upload_queue.put(upload_task)
            logger.info(f"【Enhanced115】已加入重新上传队列：{file_path.name}")
            
        except Exception as e:
            logger.error(f"【Enhanced115】重新上传失败：{e}")

    def _trigger_share(self, download_hash: str, task_info: dict):
        """
        触发分享（从定时检查调用）
        
        :param download_hash: 下载hash
        :param task_info: 任务信息
        """
        try:
            if not self._share_enabled or not self._sharer:
                logger.debug("【Enhanced115】未启用分享，跳过")
                self._task_manager.remove_task(download_hash)
                return
            
            # 创建分享
            share_result = self._sharer.create_share(
                task_info,
                download_hash,
                None  # mediainfo在定时检查时不可用
            )
            
            if share_result:
                self._stats['shared'] += 1
                
                # Telegram通知（增强版：传递download_hash）
                if self._telegram_enabled and self._telegram:
                    self._telegram.send_share_notification(
                        task_info,
                        share_result,
                        download_hash
                    )
                
                # 分享成功才移除任务
                self._task_manager.remove_task(download_hash)
                logger.info(f"【Enhanced115】任务已完成并移除：{task_info.get('media_title')}")
            else:
                # 分享失败，保留任务，下次重试
                logger.warning(f"【Enhanced115】分享失败，任务保留：{task_info.get('media_title')}")
                
        except Exception as e:
            logger.error(f"【Enhanced115】触发分享失败：{e}")

    def get_state(self) -> bool:
        """获取插件运行状态"""
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面"""
        return [
            {
                'component': 'VForm',
                'content': [
                    # 说明
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '完全集成my_115_app逻辑！\\n1. 智能判断分享模式（整季/单集/补集）\\n2. 自动统计完成数量\\n3. 所有文件完成后自动分享\\n\\n⚠️ MoviePilot必须配置为"硬链接"整理'
                                }
                            }]
                        }]
                    },
                    # 启用
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 6},
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'enabled',
                                    'label': '启用插件'
                                }
                            }]
                        }]
                    },
                    # 115配置
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'p115_cookies',
                                    'label': '115网盘 Cookies',
                                    'rows': 2,
                                    'hint': 'F12→Network→复制Cookie'
                                }
                            }]
                        }]
                    },
                    # 上传配置
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 6},
                            'content': [{
                                'component': 'VTextField',
                                'props': {
                                    'model': 'upload_threads',
                                    'label': '上传线程数',
                                    'type': 'number'
                                }
                            }]
                        }]
                    },
                    # 路径映射
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'path_mappings',
                                    'label': '路径映射(JSON)',
                                    'rows': 2,
                                    'hint': '[{"local":"/media","remote":"/Emby"}]'
                                }
                            }]
                        }]
                    },
                    # 分享配置
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'share_enabled',
                                        'label': '启用自动分享',
                                        'hint': '上传完成后自动创建分享'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'share_modify_enabled',
                                        'label': '启用分享修改',
                                        'hint': '关闭则使用115默认设置'
                                    }
                                }]
                            }
                        ]
                    },
                    # 有效期配置
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'file_duration',
                                        'label': 'File模式有效期(天)',
                                        'type': 'number',
                                        'hint': '文件打包分享的有效期，-1=永久'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'folder_duration',
                                        'label': 'Folder模式有效期(天)',
                                        'type': 'number',
                                        'hint': '文件夹分享的有效期，-1=永久'
                                    }
                                }]
                            }
                        ]
                    },
                    # 密码策略
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'password_strategy',
                                        'label': '密码策略',
                                        'items': [
                                            {'title': '保留初始密码', 'value': 'keep_initial'},
                                            {'title': '固定密码', 'value': 'fixed'},
                                            {'title': '列表随机', 'value': 'random_list'},
                                            {'title': '无密码', 'value': 'empty'},
                                            {'title': '完全随机', 'value': 'random_generate'}
                                        ],
                                        'hint': '选择密码生成策略'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'password_value',
                                        'label': '密码值',
                                        'hint': '固定: "1234", 列表: ["1111","2222"]'
                                    }
                                }]
                            }
                        ]
                    },
                    # 高级限制
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'receive_user_limit',
                                        'label': '接收次数限制',
                                        'type': 'number',
                                        'hint': '0=不限制'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'skip_login_enabled',
                                        'label': '启用免登录下载'
                                    }
                                }]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'skip_login_limit',
                                        'label': '免登录流量限制(字节)',
                                        'hint': '空=不限，或如：10737418240(10GB)'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'access_user_ids',
                                        'label': '指定接收者ID',
                                        'hint': '空=所有人，或"id1,id2"'
                                    }
                                }]
                            }
                        ]
                    },
                    # 115根目录
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'movie_root_cid',
                                        'label': '电影根目录CID'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'tv_root_cid',
                                        'label': '电视剧根目录CID'
                                    }
                                }]
                            }
                        ]
                    },
                    # 删除配置
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'delete_after_upload',
                                        'label': '上传后删除本地文件',
                                        'hint': '开启后会删除/media中已上传的文件，节省空间'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'scan_interval',
                                        'label': '扫描间隔(秒)',
                                        'type': 'number',
                                        'hint': '扫描清理文件的间隔时间，默认1800秒（30分钟）'
                                    }
                                }]
                            }
                        ]
                    },
                    # STRM配置
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'strm_enabled',
                                        'label': '启用STRM管理',
                                        'hint': '生成strm文件映射115文件，支持洗版管理'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'emby_local_path',
                                        'label': '本地Emby目录',
                                        'hint': '容器内路径，默认/Emby'
                                    }
                                }]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 6},
                            'content': [{
                                'component': 'VSelect',
                                'props': {
                                    'model': 'strm_overwrite_mode',
                                    'label': 'STRM覆盖模式',
                                    'items': [
                                        {'title': '自动（检查格式）', 'value': 'auto'},
                                        {'title': '总是覆盖', 'value': 'always'},
                                        {'title': '从不覆盖', 'value': 'never'}
                                    ],
                                    'hint': 'auto=检查是否插件格式，always=强制覆盖，never=跳过'
                                }
                            }]
                        }]
                    },
                    # Telegram
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'telegram_enabled',
                                        'label': '启用Telegram'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'telegram_bot_token',
                                        'label': 'Bot Token'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'telegram_chat_id',
                                        'label': 'Chat ID'
                                    }
                                }]
                            }
                        ]
                    }
                ]
            }
        ], {
            'enabled': False,
            'p115_cookies': '',
            'upload_threads': 3,
            'path_mappings': '[{"local":"/media","remote":"/Emby"}]',
            'share_enabled': False,
            'share_modify_enabled': True,
            'file_duration': 15,
            'folder_duration': -1,
            'password_strategy': 'keep_initial',
            'password_value': '',
            'receive_user_limit': 0,
            'skip_login_enabled': False,
            'skip_login_limit': '',
            'access_user_ids': '',
            'movie_root_cid': '',
            'tv_root_cid': '',
            'delete_after_upload': False,
            'scan_interval': 1800,
            'strm_enabled': False,
            'emby_local_path': '/Emby',
            'strm_overwrite_mode': 'auto',
            'telegram_enabled': False,
            'telegram_bot_token': '',
            'telegram_chat_id': ''
        }

    def get_page(self) -> List[dict]:
        """拼装插件详情页面"""
        logger.info("【Enhanced115】get_page被调用")
        
        try:
            # 获取任务信息
            pending_tasks = self._task_manager.get_all_pending_tasks() if self._task_manager else {}
            logger.info(f"【Enhanced115】pending_tasks数量：{len(pending_tasks)}")
            
            # 兼容性优先：使用简洁的文本卡片
            task_lines = [
                f"{task['media_title']}：{task['actual_count']}/{task['expected_count']} [{task['share_mode']}]"
                for task in pending_tasks.values()
            ]
            tasks_text = "\\n".join(task_lines) if task_lines else "无待处理任务"
            
            stats_text = (
                f"总任务：{self._stats['total_tasks']}  ｜  "
                f"已上传：{self._stats['uploaded']}  ｜  "
                f"已分享：{self._stats['shared']}  ｜  "
                f"失败：{self._stats['failed']}  ｜  "
                f"队列：{self._stats['queue_size']}"
            )
            
            container_content = [
                {
                    'component': 'VRow',
                    'content': [{
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [{
                            'component': 'VAlert',
                            'props': {
                                'color': 'primary',
                                'variant': 'tonal',
                                'title': '任务统计',
                                'text': stats_text,
                                'class': 'text-pre-wrap text-body-2'
                            }
                        }]
                    }]
                },
                {
                    'component': 'VRow',
                    'content': [{
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [{
                            'component': 'VAlert',
                            'props': {
                                'color': 'secondary',
                                'variant': 'tonal',
                                'title': '待处理任务',
                                'text': tasks_text,
                                'class': 'text-pre-wrap text-body-2'
                            }
                        }]
                    }]
                }
            ]
            
            # 如果启用STRM，添加全量同步按钮
            logger.info(f"【Enhanced115】_strm_enabled={self._strm_enabled}")
            if self._strm_enabled:
                strm_info = [
                    {'title': '本地目录', 'value': self._emby_local_path},
                    {'title': '覆盖模式', 'value': self._strm_overwrite_mode},
                    {'title': '字幕策略', 'value': '真实扩展 + fileid/pickcode 占位'}
                ]
                
                strm_card = {
                    'component': 'VCard',
                    'props': {'variant': 'flat', 'class': 'pa-4'},
                    'content': [
                        {
                            'component': 'VCardTitle',
                            'props': {'text': 'STRM 管理'}
                        },
                        {
                            'component': 'VCardSubtitle',
                            'props': {'text': 'STRM 文件映射到 115，自动处理洗版与字幕占位'}
                        },
                        {
                            'component': 'VCardText',
                            'content': [{
                                'component': 'VList',
                                'props': {'density': 'compact'},
                                'content': [{
                                    'component': 'VListItem',
                                    'props': {
                                        'title': info['title'],
                                        'subtitle': info['value']
                                    }
                                } for info in strm_info]
                            }]
                        },
                        {
                            'component': 'VCardActions',
                            'content': [{
                                'component': 'VSpacer'
                            }, {
                                'component': 'VBtn',
                                'props': {
                                    'color': 'primary',
                                    'variant': 'elevated',
                                    'prependIcon': 'mdi-sync',
                                    'text': '全量同步 STRM'
                                },
                                'events': {
                                    'click': {
                                        'api': 'plugin/Enhanced115/strm_full_sync',
                                        'method': 'post'
                                    }
                                }
                            }]
                        }
                    ]
                }
                
                container_content.append({
                    'component': 'VRow',
                    'content': [{
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [strm_card]
                    }]
                })
            
            page_content = [{
                'component': 'VContainer',
                'props': {'fluid': True},
                'content': container_content
            }]
            
            logger.info(f"【Enhanced115】page_content长度：{len(page_content)}")
            logger.info(f"【Enhanced115】page_content类型：{type(page_content)}")
            return page_content
            
        except Exception as e:
            logger.error(f"【Enhanced115】构建详情页面失败：{e}")
            return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册插件API"""
        return [{
            "path": "/strm_full_sync",
            "endpoint": self.strm_full_sync,
            "methods": ["POST"],
            "summary": "全量同步115到STRM",
            "description": "扫描115指定目录，生成本地strm映射文件",
            "auth": "bear"
        }]
    
    def strm_full_sync(self, root_cid: str = None, scope: str = "both") -> dict:
        """
        全量同步API接口
        
        :param root_cid: 115根目录CID（可选，默认使用tv_root_cid）
        :return: 同步结果
        """
        if not self._strm_enabled:
            return {"success": False, "message": "STRM功能未启用"}
        
        if not self._strm_manager:
            return {"success": False, "message": "STRM管理器未初始化"}
        
        roots = []
        scope = (scope or "both").lower()
        if root_cid:
            roots = [root_cid]
        else:
            if scope in ("both", "movie"):
                if self._movie_root_cid:
                    roots.append(self._movie_root_cid)
            if scope in ("both", "tv"):
                if self._tv_root_cid:
                    roots.append(self._tv_root_cid)
        
        if not roots:
            return {"success": False, "message": "未配置根目录CID"}
        
        aggregated = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}
        details = []
        errors = []
        
        for cid in roots:
            try:
                stats = self._strm_manager.full_sync(
                    root_cid=cid,
                    target_dir=self._emby_local_path,
                    pan_media_dir="/Emby"
                )
                details.append({'cid': cid, 'stats': stats})
                for key in aggregated:
                    aggregated[key] += stats.get(key, 0)
            except Exception as e:
                logger.error(f"【Enhanced115】全量同步子任务失败，CID={cid}，错误：{e}")
                errors.append({'cid': cid, 'error': str(e)})
        
        logger.info(
            f"【Enhanced115】全量同步汇总 | 目录数={len(roots)} | "
            f"总数={aggregated['total']} | 成功={aggregated['success']} | "
            f"失败={aggregated['failed']} | 跳过={aggregated['skipped']}"
        )
        
        success = not errors
        message = "同步完成" if success else "部分目录同步失败"
        return {
            "success": success,
            "message": message,
            "stats": aggregated,
            "details": details,
            "errors": errors
        }

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件定时服务
        每5分钟检查一次pending任务，实现自愈能力
        """
        if not self._enabled:
            return []
        
        services = [{
            "id": "Enhanced115.check_pending_tasks",
            "name": "检查待处理任务",
            "trigger": "interval",
            "func": self._check_pending_tasks,
            "kwargs": {
                "seconds": 300  # 每5分钟执行一次
            }
        }]
        
        # 如果开启了删除功能，添加目录扫描服务
        if self._delete_after_upload:
            services.append({
                "id": "Enhanced115.scan_and_clean",
                "name": "扫描清理已上传文件",
                "trigger": "interval",
                "func": self._scan_and_clean_uploaded_files,
                "kwargs": {
                    "seconds": self._scan_interval  # 使用配置的间隔时间
                }
            })
        
        return services

    def stop_service(self):
        """停止插件服务"""
        try:
            self._stop_event.set()
            
            if self._upload_executor:
                logger.info("【Enhanced115】正在停止...")
                self._upload_executor.shutdown(wait=False)
                self._upload_executor = None
            
            while not self._upload_queue.empty():
                try:
                    self._upload_queue.get_nowait()
                    self._upload_queue.task_done()
                except queue.Empty:
                    break
            
            logger.info("【Enhanced115】已停止")
            
        except Exception as e:
            logger.error(f"【Enhanced115】停止服务时出错：{e}")

            logger.error(f"【Enhanced115】停止服务时出错：{e}")
