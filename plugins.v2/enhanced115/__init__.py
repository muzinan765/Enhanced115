"""
Enhanced115 - 115网盘上传助手（基于硬链接）

工作原理：
1. MoviePilot使用硬链接整理（本地→本地，瞬间完成）
2. 插件监听TransferComplete事件
3. 多线程异步上传到115网盘
4. 更新数据库记录（local→u115）
5. 创建115分享（集成my_115_app逻辑）
6. Telegram通知
"""
import queue
import threading
from typing import Optional, List, Dict, Any, Tuple

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType

# 导入子模块
from .uploader import Upload115Handler
from .sharer import Share115Handler
from .database import DatabaseHandler
from .telegram_notifier import TelegramNotifier
from .utils import map_local_to_remote, parse_path_mappings


class Enhanced115(_PluginBase):
    # 插件基本信息
    plugin_name = "Enhanced115网盘助手"
    plugin_desc = "硬链接+多线程上传115，集成分享功能"
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
        self._share_config = {}
        
        # Telegram配置
        self._telegram_enabled = False
        self._telegram_config = {}
        
        # 处理器
        self._p115_client = None
        self._uploader = None
        self._sharer = None
        self._telegram = None
        
        # 上传队列
        self._upload_queue = queue.Queue()
        self._upload_executor = None
        self._stop_event = threading.Event()
        
        # 统计
        self._stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'in_progress': 0,
            'shared': 0
        }

    def init_plugin(self, config: dict = None):
        """初始化插件"""
        if not config:
            return
        
        # 基础配置
        self._enabled = config.get("enabled", False)
        self._p115_cookies = config.get("p115_cookies", "")
        self._upload_threads = int(config.get("upload_threads", 3))
        
        # 路径映射
        self._path_mappings = parse_path_mappings(config.get("path_mappings", ""))
        
        # 分享配置
        self._share_enabled = config.get("share_enabled", False)
        self._share_config = {
            'share_mode': config.get("share_mode", "folder"),
            'share_duration': int(config.get("share_duration", -1)),
            'share_password': config.get("share_password", ""),
            'movie_root_cid': config.get("movie_root_cid", ""),
            'tv_root_cid': config.get("tv_root_cid", "")
        }
        
        # Telegram配置
        self._telegram_enabled = config.get("telegram_enabled", False)
        self._telegram_config = {
            'bot_token': config.get("telegram_bot_token", ""),
            'chat_id': config.get("telegram_chat_id", "")
        }
        
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
            
            if self._share_enabled:
                self._sharer = Share115Handler(self._p115_client, self._share_config)
            
            if self._telegram_enabled:
                self._telegram = TelegramNotifier(
                    self._telegram_config['bot_token'],
                    self._telegram_config['chat_id']
                )
            
            # 启动上传队列
            self._start_upload_workers()
            
            logger.info("【Enhanced115】插件初始化完成")
            
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
            
            # 验证
            user_id = self._p115_client.user_id
            user_key = self._p115_client.user_key
            
            if user_id and user_key:
                logger.info(f"【Enhanced115】115登录成功，User ID：{user_id}")
            else:
                raise Exception("无法获取用户ID或Key")
                
        except ImportError:
            raise Exception("p115client库未安装，请执行: pip install p115client")
        except Exception as e:
            raise Exception(f"115客户端初始化失败：{str(e)}")

    def _start_upload_workers(self):
        """启动上传工作线程"""
        from concurrent.futures import ThreadPoolExecutor
        
        self._stop_event.clear()
        self._upload_executor = ThreadPoolExecutor(
            max_workers=self._upload_threads,
            thread_name_prefix="Enhanced115-Upload"
        )
        
        # 启动工作线程
        for i in range(self._upload_threads):
            self._upload_executor.submit(self._upload_worker)
        
        logger.info(f"【Enhanced115】已启动{self._upload_threads}个上传工作线程")

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event):
        """
        监听整理完成事件
        """
        if not self._enabled or not self._p115_client:
            return
        
        try:
            event_data = event.event_data
            transferinfo = event_data.get('transferinfo')
            
            # 检查是否是本地存储（硬链接后的状态）
            if not transferinfo or not transferinfo.target_item:
                return
            
            if transferinfo.target_item.storage != 'local':
                return
            
            # 映射路径
            local_path = transferinfo.target_item.path
            remote_path = map_local_to_remote(local_path, self._path_mappings)
            
            if not remote_path:
                logger.debug(f"【Enhanced115】路径不在映射配置中：{local_path}")
                return
            
            # 构建上传任务
            from pathlib import Path
            
            upload_task = {
                'local_path': Path(local_path),
                'remote_path': remote_path,
                'download_hash': event_data.get('download_hash'),
                'fileitem': event_data.get('fileitem'),
                'meta': event_data.get('meta'),
                'mediainfo': event_data.get('mediainfo'),
                'transferinfo': transferinfo,
                'downloader': event_data.get('downloader'),
            }
            
            # 加入队列
            self._upload_queue.put(upload_task)
            self._stats['total'] += 1
            
            logger.info(
                f"【Enhanced115】已加入上传队列：{transferinfo.target_item.name}，"
                f"队列长度：{self._upload_queue.qsize()}"
            )
            
        except Exception as e:
            logger.error(f"【Enhanced115】处理事件失败：{e}")

    def _upload_worker(self):
        """上传工作线程"""
        while not self._stop_event.is_set():
            try:
                task = self._upload_queue.get(timeout=1)
            except queue.Empty:
                continue
            
            if not task:
                continue
            
            self._stats['in_progress'] += 1
            
            try:
                self._process_upload_task(task)
            except Exception as e:
                logger.error(f"【Enhanced115】任务处理异常：{e}")
                self._stats['failed'] += 1
            finally:
                self._stats['in_progress'] -= 1
                self._upload_queue.task_done()

    def _process_upload_task(self, task: dict):
        """处理上传任务"""
        local_path = task['local_path']
        remote_path = task['remote_path']
        filename = local_path.name
        
        # 1. 上传到115
        success, file_info = self._uploader.upload_file(local_path, remote_path, filename)
        
        if not success:
            self._stats['failed'] += 1
            logger.error(f"【Enhanced115】上传失败：{filename}")
            return
        
        # 2. 更新数据库
        db_updated = DatabaseHandler.update_transfer_record(
            task['download_hash'],
            remote_path,
            file_info
        )
        
        if not db_updated:
            logger.warning(f"【Enhanced115】数据库更新失败：{filename}")
            # 即使数据库更新失败，文件已在115，继续后续流程
        
        self._stats['success'] += 1
        logger.info(f"【Enhanced115】处理完成：{filename}")
        
        # 3. 创建分享（如果启用）
        if self._share_enabled and self._sharer:
            share_result = self._sharer.create_share(task, file_info)
            if share_result:
                self._stats['shared'] += 1
                
                # 4. Telegram通知
                if self._telegram_enabled and self._telegram:
                    self._telegram.send_share_notification(task, share_result)

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
                                    'text': '⚠️ 重要：MoviePilot必须配置为"硬链接"整理方式！\\n工作流程：硬链接整理(瞬间) → 插件异步上传115 → 更新数据库 → 创建分享'
                                }
                            }]
                        }]
                    },
                    # 启用开关
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 6},
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'enabled',
                                    'label': '启用插件',
                                    'hint': '总开关'
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
                                    'hint': '登录115.com，F12→Network→复制Cookie'
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
                                    'type': 'number',
                                    'hint': '建议3-5个线程'
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
                                    'label': '路径映射（JSON）',
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
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'share_enabled',
                                        'label': '启用自动分享',
                                        'hint': '上传后自动创建115分享'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'share_mode',
                                        'label': '分享模式',
                                        'items': [
                                            {'title': '文件夹分享', 'value': 'folder'},
                                            {'title': '文件打包分享', 'value': 'file'}
                                        ],
                                        'hint': 'folder=分享整个目录，file=打包分享文件'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'share_duration',
                                        'label': '有效期(天)',
                                        'type': 'number',
                                        'hint': '-1=永久'
                                    }
                                }]
                            }
                        ]
                    },
                    # 分享参数
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'share_password',
                                        'label': '提取码',
                                        'hint': '4位字符，留空=无密码'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'movie_root_cid',
                                        'label': '电影根目录CID',
                                        'hint': '115中/Emby/电影的CID'
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'tv_root_cid',
                                        'label': '电视剧根目录CID',
                                        'hint': '115中/Emby/电视剧的CID'
                                    }
                                }]
                            }
                        ]
                    },
                    # Telegram配置
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
                                        'label': '启用Telegram通知',
                                        'hint': '分享完成后发送通知'
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
            'share_mode': 'folder',
            'share_duration': -1,
            'share_password': '',
            'movie_root_cid': '',
            'tv_root_cid': '',
            'telegram_enabled': False,
            'telegram_bot_token': '',
            'telegram_chat_id': ''
        }

    def get_page(self) -> List[dict]:
        """拼装插件详情页面"""
        stats_text = (
            f"总任务：{self._stats['total']}\\n"
            f"成功：{self._stats['success']}\\n"
            f"失败：{self._stats['failed']}\\n"
            f"进行中：{self._stats['in_progress']}\\n"
            f"已分享：{self._stats['shared']}\\n"
            f"队列：{self._upload_queue.qsize()}"
        )
        
        return [
            {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {'cols': 12},
                    'content': [{
                        'component': 'VCard',
                        'props': {'variant': 'tonal'},
                        'content': [
                            {
                                'component': 'VCardTitle',
                                'props': {'text': '上传统计'}
                            },
                            {
                                'component': 'VCardText',
                                'props': {'text': stats_text}
                            }
                        ]
                    }]
                }]
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """注册插件API"""
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        """注册插件服务"""
        return []

    def stop_service(self):
        """停止插件服务"""
        try:
            self._stop_event.set()
            
            if self._upload_executor:
                logger.info("【Enhanced115】正在停止上传线程池...")
                self._upload_executor.shutdown(wait=False)
                self._upload_executor = None
            
            # 清空队列
            while not self._upload_queue.empty():
                try:
                    self._upload_queue.get_nowait()
                    self._upload_queue.task_done()
                except queue.Empty:
                    break
            
            logger.info("【Enhanced115】插件服务已停止")
            
        except Exception as e:
            logger.error(f"【Enhanced115】停止服务时出错：{e}")
