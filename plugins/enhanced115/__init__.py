"""
Enhanced115 - 增强型115网盘插件
功能：
1. 多线程异步上传到115网盘（解决单线程上传阻塞问题）
2. 增强站点资源缓存（更大容量、更智能的缓存策略）
"""
import queue
import threading
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import TransferInterceptEventData, Notification, NotificationType
from app.schemas.types import EventType, ChainEventType


class Enhanced115(_PluginBase):
    # 插件基本信息
    plugin_name = "增强型115网盘"
    plugin_desc = "多线程上传115 + 增强资源缓存"
    plugin_icon = "https://img.icons8.com/color/96/google-cloud.png"
    plugin_version = "1.0.0"
    plugin_author = "muzinan765"
    author_url = "https://github.com/muzinan765/Enhanced115"
    plugin_config_prefix = "enhanced115_"
    plugin_order = 1
    
    # 插件配置项
    auth_level = 2  # 需要站点认证（使用p115client需要认证）
    
    def __init__(self):
        super().__init__()
        
        # 配置
        self._enabled = False
        self._upload_enabled = False
        self._cache_enabled = False
        self._p115_cookies = None
        self._upload_threads = 3
        self._cache_size = 1000
        
        # 115客户端
        self._p115_client = None
        
        # 上传队列
        self._upload_queue = queue.Queue()
        self._upload_executor = None
        self._upload_threads_list = []
        
        # 停止标志
        self._stop_event = threading.Event()
        
        # 统计信息
        self._upload_stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'in_progress': 0
        }
        
        # 增强缓存
        self._enhanced_cache: Dict[str, List[Any]] = {}
        self._cache_lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        """初始化插件"""
        if not config:
            return
        
        # 读取配置
        self._enabled = config.get("enabled", False)
        self._upload_enabled = config.get("upload_enabled", False)
        self._cache_enabled = config.get("cache_enabled", False)
        self._p115_cookies = config.get("p115_cookies", "")
        self._upload_threads = int(config.get("upload_threads", 3))
        self._cache_size = int(config.get("cache_size", 1000))
        
        # 停止旧服务
        self.stop_service()
        
        if not self._enabled:
            logger.info("Enhanced115 插件未启用")
            return
        
        # 初始化115客户端
        if self._upload_enabled:
            if not self._p115_cookies:
                logger.error("【Enhanced115】未配置115 Cookies，无法启用上传功能")
                self._upload_enabled = False
            else:
                try:
                    self._init_p115_client()
                    logger.info(f"【Enhanced115】115客户端初始化成功")
                except Exception as e:
                    logger.error(f"【Enhanced115】115客户端初始化失败：{e}")
                    self._upload_enabled = False
        
        # 启动上传队列
        if self._upload_enabled:
            self._start_upload_workers()
            logger.info(f"【Enhanced115】上传队列已启动，线程数：{self._upload_threads}")
        
        # 启用资源缓存增强
        if self._cache_enabled:
            logger.info(f"【Enhanced115】资源缓存增强已启用，缓存容量：{self._cache_size}")
        
        logger.info("【Enhanced115】插件初始化完成")

    def _init_p115_client(self):
        """初始化p115客户端"""
        try:
            from p115client import P115Client
            
            # 使用cookie初始化客户端
            self._p115_client = P115Client(
                self._p115_cookies,
                check_for_relogin=True
            )
            
            # 验证客户端：user_id和user_key是属性，直接访问
            user_id = self._p115_client.user_id
            user_key = self._p115_client.user_key
            
            if user_id and user_key:
                logger.info(f"【Enhanced115】115客户端初始化成功，User ID：{user_id}")
            else:
                raise Exception("无法获取用户ID或Key")
                
        except ImportError:
            raise Exception("p115client库未安装，请执行: pip install p115client")
        except Exception as e:
            raise Exception(f"115客户端初始化失败：{str(e)}")

    def _start_upload_workers(self):
        """启动上传工作线程"""
        self._stop_event.clear()
        self._upload_executor = ThreadPoolExecutor(
            max_workers=self._upload_threads,
            thread_name_prefix="Enhanced115-Upload"
        )
        logger.info(f"【Enhanced115】上传线程池已创建，最大并发数：{self._upload_threads}")

    @eventmanager.register(ChainEventType.TransferIntercept)
    def on_transfer_intercept(self, event: Event):
        """
        拦截文件整理事件，接管115上传
        """
        if not self._enabled or not self._upload_enabled:
            return
        
        event_data: TransferInterceptEventData = event.event_data
        
        # 只处理115存储的上传
        if event_data.target_storage != "115":
            return
        
        # 取消原有的上传操作
        event_data.cancel = True
        event_data.source = "Enhanced115Plugin"
        event_data.reason = "使用多线程异步上传队列"
        
        # 添加到上传队列
        upload_task = {
            'fileitem': event_data.fileitem,
            'target_path': event_data.target_path,
            'target_storage': event_data.target_storage,
            'transfer_type': event_data.transfer_type,
            'mediainfo': event_data.mediainfo,
            'options': event_data.options
        }
        
        self._upload_queue.put(upload_task)
        self._upload_stats['total'] += 1
        
        # 提交到线程池处理
        future = self._upload_executor.submit(self._process_upload_task)
        
        logger.info(
            f"【Enhanced115】文件已加入异步上传队列：{event_data.fileitem.name}，"
            f"队列长度：{self._upload_queue.qsize()}"
        )

    def _process_upload_task(self):
        """处理上传任务（在工作线程中执行）"""
        try:
            # 从队列获取任务
            task = self._upload_queue.get(timeout=1)
        except queue.Empty:
            return
        
        fileitem = task['fileitem']
        target_path = task['target_path']
        
        self._upload_stats['in_progress'] += 1
        
        try:
            logger.info(f"【Enhanced115】开始上传：{fileitem.name}")
            
            # 执行上传
            success = self._upload_to_115(
                local_path=Path(fileitem.path),
                remote_path=Path(target_path),
                filename=fileitem.name
            )
            
            if success:
                self._upload_stats['success'] += 1
                logger.info(f"【Enhanced115】上传成功：{fileitem.name}")
                
                # 发送成功通知
                self.post_message(Notification(
                    mtype=NotificationType.Manual,
                    title=f"{fileitem.name} 上传成功",
                    text=f"已上传到115网盘：{target_path}"
                ))
            else:
                self._upload_stats['failed'] += 1
                logger.error(f"【Enhanced115】上传失败：{fileitem.name}")
                
        except Exception as e:
            self._upload_stats['failed'] += 1
            logger.error(f"【Enhanced115】上传异常：{fileitem.name}，错误：{e}")
        finally:
            self._upload_stats['in_progress'] -= 1
            self._upload_queue.task_done()

    def _upload_to_115(self, local_path: Path, remote_path: Path, filename: str) -> bool:
        """
        使用p115client上传文件到115网盘
        """
        try:
            from p115client.tool import P115MultipartUpload
            
            if not local_path.exists():
                logger.error(f"【Enhanced115】本地文件不存在：{local_path}")
                return False
            
            # 获取或创建远程目录
            remote_dir = remote_path.parent
            pid = self._get_or_create_remote_dir(remote_dir)
            if not pid:
                logger.error(f"【Enhanced115】无法创建远程目录：{remote_dir}")
                return False
            
            # 初始化上传
            logger.info(f"【Enhanced115】正在初始化上传：{filename}")
            uploader = P115MultipartUpload.from_path(
                path=str(local_path),
                pid=pid,
                filename=filename,
                user_id=self._p115_client.user_id,
                user_key=self._p115_client.user_key
            )
            
            # 检查是否秒传
            if isinstance(uploader, dict):
                logger.info(f"【Enhanced115】{filename} 秒传成功")
                return True
            
            # 分片上传
            logger.info(f"【Enhanced115】开始分片上传：{filename}")
            file_size = local_path.stat().st_size
            uploaded = 0
            
            for part_info in uploader.iter_upload():
                uploaded += part_info.get('Size', 0)
                progress = (uploaded / file_size * 100) if file_size > 0 else 0
                
                if uploaded % (10 * 1024 * 1024) == 0:  # 每10MB记录一次
                    logger.debug(
                        f"【Enhanced115】上传进度：{filename} - {progress:.1f}%"
                    )
            
            # 完成上传
            result = uploader.complete()
            
            if result.get('state'):
                logger.info(f"【Enhanced115】{filename} 上传完成")
                return True
            else:
                logger.error(f"【Enhanced115】{filename} 上传失败：{result.get('error', 'Unknown')}")
                return False
                
        except Exception as e:
            logger.error(f"【Enhanced115】上传异常：{filename}，错误：{e}")
            return False

    def _get_or_create_remote_dir(self, remote_path: Path) -> Optional[int]:
        """
        获取或创建远程目录，返回目录ID
        """
        try:
            # 使用fs_makedirs_app创建目录（会自动创建中间目录）
            # 参数：目录路径, 父目录ID（0表示根目录）
            result = self._p115_client.fs_makedirs_app(
                str(remote_path),
                pid=0
            )
            
            if result and result.get('cid'):
                return int(result['cid'])
            
            logger.error(f"【Enhanced115】无法获取目录ID：{remote_path}，响应：{result}")
            return None
            
        except Exception as e:
            logger.error(f"【Enhanced115】创建远程目录失败：{remote_path}，错误：{e}")
            return None

    @eventmanager.register(EventType.SiteRefreshed)
    def on_site_refreshed(self, event: Event):
        """
        站点刷新完成后，增强资源缓存
        """
        if not self._enabled or not self._cache_enabled:
            return
        
        try:
            from app.chain.torrents import TorrentsChain
            
            # 读取原始缓存
            torrents_chain = TorrentsChain()
            original_cache = torrents_chain.get_torrents()
            
            # 扩展缓存
            with self._cache_lock:
                for domain, contexts in original_cache.items():
                    if domain not in self._enhanced_cache:
                        self._enhanced_cache[domain] = []
                    
                    # 合并缓存，去重
                    existing_signatures = {
                        f"{c.torrent_info.title}{c.torrent_info.description}"
                        for c in self._enhanced_cache[domain]
                    }
                    
                    for context in contexts:
                        signature = f"{context.torrent_info.title}{context.torrent_info.description}"
                        if signature not in existing_signatures:
                            self._enhanced_cache[domain].append(context)
                            existing_signatures.add(signature)
                    
                    # 按发布时间降序排序
                    self._enhanced_cache[domain].sort(
                        key=lambda x: x.torrent_info.pubdate or '',
                        reverse=True
                    )
                    
                    # 保留最新的N条
                    if len(self._enhanced_cache[domain]) > self._cache_size:
                        self._enhanced_cache[domain] = self._enhanced_cache[domain][:self._cache_size]
                    
                    logger.debug(
                        f"【Enhanced115】{domain} 增强缓存更新，"
                        f"当前数量：{len(self._enhanced_cache[domain])}"
                    )
        
        except Exception as e:
            logger.error(f"【Enhanced115】资源缓存增强失败：{e}")

    def get_state(self) -> bool:
        """获取插件运行状态"""
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                            'hint': '开启后插件才会生效',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '功能说明：\n1. 多线程异步上传115网盘（解决单线程阻塞问题）\n2. 增强站点资源缓存（更大容量、更智能）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'upload_enabled',
                                            'label': '启用多线程上传',
                                            'hint': '拦截115上传，使用多线程异步队列',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'cache_enabled',
                                            'label': '启用资源缓存增强',
                                            'hint': '扩展站点资源缓存容量和智能度',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'upload_threads',
                                            'label': '上传线程数',
                                            'type': 'number',
                                            'hint': '建议3-5个线程',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cache_size',
                                            'label': '缓存容量',
                                            'type': 'number',
                                            'hint': '每个站点保留的资源数量',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'p115_cookies',
                                            'label': '115网盘 Cookies',
                                            'rows': 3,
                                            'hint': '从浏览器开发者工具中复制115网盘的Cookie',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '注意：\n1. 需要安装 p115client 库：pip install p115client\n2. Cookie获取方法：登录115网盘 -> F12开发者工具 -> Network -> 复制Cookie请求头'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            'enabled': False,
            'upload_enabled': False,
            'cache_enabled': False,
            'upload_threads': 3,
            'cache_size': 1000,
            'p115_cookies': ''
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面
        """
        # 构建统计信息
        stats_text = (
            f"总任务数：{self._upload_stats['total']}\n"
            f"成功：{self._upload_stats['success']}\n"
            f"失败：{self._upload_stats['failed']}\n"
            f"进行中：{self._upload_stats['in_progress']}\n"
            f"队列长度：{self._upload_queue.qsize()}"
        )
        
        cache_text = "\n".join([
            f"{domain}: {len(contexts)} 条"
            for domain, contexts in self._enhanced_cache.items()
        ]) if self._enhanced_cache else "暂无缓存数据"
        
        return [
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 6},
                        'content': [
                            {
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
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 6},
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {'variant': 'tonal'},
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {'text': '增强缓存统计'}
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {'text': cache_text}
                                    }
                                ]
                            }
                        ]
                    }
                ]
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
            # 设置停止标志
            self._stop_event.set()
            
            # 关闭上传线程池
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

