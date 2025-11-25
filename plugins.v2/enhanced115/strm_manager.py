"""
STRM文件管理器
独立管理strm文件的生成、洗版、清理等功能
"""
from pathlib import Path
from typing import Optional
from queue import Queue
from threading import Thread
try:
    from itertools import batched
except ImportError:  # Python < 3.12
    from itertools import islice

    def batched(iterable, n):
        """
        Backport of itertools.batched for Python < 3.12.

        :param iterable: 任意可迭代对象
        :param n: 批大小，必须为正整数
        """
        if n <= 0:
            raise ValueError("batch size must be positive")

        iterator = iter(iterable)
        while True:
            batch = tuple(islice(iterator, n))
            if not batch:
                break
            yield batch
from time import perf_counter

from app.log import logger

from .strm_helper import StrmHelper, SUBTITLE_EXTS


class StrmManager:
    """STRM文件管理器"""
    
    def __init__(self, client, emby_local_path: str = "/Emby", overwrite_mode: str = "auto"):
        """
        初始化STRM管理器
        
        :param client: p115client实例
        :param emby_local_path: 本地Emby目录路径
        :param overwrite_mode: 覆盖模式（never/always/auto）
        """
        self.client = client
        self.emby_local_path = Path(emby_local_path)
        self.overwrite_mode = overwrite_mode
        self.helper = StrmHelper()
    
    def handle_upload_success(self, local_path: Path, remote_path: str, 
                              file_info: dict, is_movie: bool) -> bool:
        """
        处理文件上传成功后的strm操作
        
        :param local_path: 本地文件路径（/media）
        :param remote_path: 115远程路径（/Emby）
        :param file_info: 上传后的文件信息（包含fileid、pickcode）
        :param is_movie: 是否电影
        :return: 是否成功
        """
        try:
            fileid = file_info.get('fileid')
            pickcode = file_info.get('pickcode', '')
            
            if not fileid:
                logger.warning(f"【Enhanced115】fileid为空，无法生成strm")
                return False
            
            remote_path_obj = Path(remote_path)
            
            # 构建本地/Emby的完整路径
            relative_path = str(remote_path_obj).lstrip('/')
            if relative_path.startswith('Emby/'):
                relative_path = relative_path[5:]  # 去掉"Emby/"
            
            target_path = self.emby_local_path / relative_path
            
            # 字幕：生成真实扩展名的占位文件
            if local_path.suffix.lower() in SUBTITLE_EXTS:
                return self.helper.generate_subtitle_placeholder(
                    target_path,
                    fileid,
                    pickcode
                )
            
            # 视频：生成strm文件
            strm_path = target_path.with_suffix(target_path.suffix + '.strm')
            return self.helper.generate_strm(strm_path, fileid, pickcode)
            
        except Exception as e:
            logger.error(f"【Enhanced115】处理上传后strm生成失败：{e}")
            return False
    
    def check_and_delete_old_version(self, remote_path: str, is_movie: bool) -> tuple:
        """
        检查115上的旧版本文件（不删除，只返回）
        
        :param remote_path: 新文件的115路径
        :param is_movie: 是否电影
        :return: (旧文件数量, 旧strm列表)
        """
        try:
            # 计算strm目录
            remote_path_obj = Path(remote_path)
            filename = remote_path_obj.name
            
            # 提取集数
            episode_id = self.helper.extract_episode_id(filename) if not is_movie else None
            
            # 构建本地/Emby目录路径
            relative_path = str(remote_path_obj.parent).lstrip('/')
            if relative_path.startswith('Emby/'):
                relative_path = relative_path[5:]
            
            strm_dir = self.emby_local_path / relative_path
            
            # 查找需要删除的旧strm
            old_strms = self.helper.find_old_strms(strm_dir, episode_id, is_movie)
            
            if old_strms:
                logger.info(
                    f"【Enhanced115】检测到洗版，找到{len(old_strms)}个旧版本，"
                    f"将在上传成功后删除"
                )
            
            # 返回旧strm列表（不使用实例变量，避免多线程竞态）
            return len(old_strms), old_strms
            
        except Exception as e:
            logger.error(f"【Enhanced115】检查旧版本失败：{e}")
            return 0, []
    
    def delete_old_versions(self, old_strms: list) -> int:
        """
        删除指定的旧版本文件
        
        :param old_strms: 旧strm列表
        :return: 删除成功的数量
        """
        if not old_strms:
            return 0
        
        return self.helper.delete_old_files(self.client, old_strms)
    
    def full_sync(self, root_cid: str, target_dir: str, pan_media_dir: str, 
                  progress_callback=None) -> dict:
        """
        全量同步115文件到本地strm（完全参考p115strmhelper架构）
        
        :param root_cid: 115根目录CID
        :param target_dir: 本地目标目录（/Emby）
        :param pan_media_dir: 115媒体目录前缀（/Emby）
        :param progress_callback: 进度回调函数
        :return: 同步结果统计
        """
        logger.info(f"【Enhanced115】full_sync方法被调用")
        logger.info(f"【Enhanced115】参数 - root_cid：{root_cid}")
        logger.info(f"【Enhanced115】参数 - target_dir：{target_dir}")
        logger.info(f"【Enhanced115】参数 - pan_media_dir：{pan_media_dir}")
        
        try:
            from p115client.tool.iterdir import iter_files_with_path
            
            logger.info(f"【Enhanced115】开始全量同步，CID：{root_cid}")
            
            stats = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}
            target_dir_path = Path(target_dir)
            start_time = perf_counter()
            
            # 写入队列和结果队列（参考p115strmhelper）
            write_queue = Queue(maxsize=4096)
            result_queue = Queue()
            
            # 启动写入线程（参考p115strmhelper的writer_worker）
            def writer_worker():
                while True:
                    task = write_queue.get()
                    if task is None:
                        result_queue.put(None)
                        break
                    
                    strm_path, fileid, pickcode = task
                    try:
                        if self.helper.generate_strm(strm_path, fileid, pickcode):
                            result_queue.put(('success', strm_path))
                        else:
                            result_queue.put(('failed', strm_path))
                    except Exception as e:
                        result_queue.put(('failed', strm_path))
                    finally:
                        write_queue.task_done()
            
            # 结果收集线程（参考p115strmhelper的result_collector）
            def result_collector():
                while True:
                    result = result_queue.get()
                    if result is None:
                        break
                    status, path = result
                    if status == 'success':
                        stats['success'] += 1
                    else:
                        stats['failed'] += 1
                    result_queue.task_done()
            
            # 启动工作线程
            logger.info(f"【Enhanced115】启动写入线程")
            writer_thread = Thread(target=writer_worker, daemon=True)
            writer_thread.start()
            
            logger.info(f"【Enhanced115】启动收集线程")
            collector_thread = Thread(target=result_collector, daemon=True)
            collector_thread.start()
            
            # 递归遍历115（参考p115strmhelper的参数）
            logger.info(f"【Enhanced115】开始遍历115目录，CID：{root_cid}")
            
            batch_count = 0
            for batch in batched(
                iter_files_with_path(
                    self.client,
                    cid=root_cid,
                    with_ancestors=True,
                    cooldown=1.5
                ),
                1000  # 每批处理1000个文件
            ):
                batch_count += 1
                logger.info(f"【Enhanced115】处理第{batch_count}批文件，包含{len(batch)}个项目")
                for item in batch:
                    stats['total'] += 1
                    
                    try:
                        # 跳过目录
                        if item.get('is_directory', False):
                            stats['skipped'] += 1
                            continue
                        
                        # 提取信息
                        fileid = str(item.get('id', ''))
                        pickcode = item.get('pickcode', item.get('pick_code', ''))
                        item_path = item.get('path', '')
                        
                        # 验证pickcode
                        if not pickcode:
                            stats['skipped'] += 1
                            continue
                        
                        # 路径过滤
                        if not item_path.startswith(pan_media_dir):
                            stats['skipped'] += 1
                            continue
                        
                        # 计算strm路径
                        path_obj = Path(item_path)
                        file_path = target_dir_path / path_obj.relative_to(pan_media_dir)
                        suffix_lower = path_obj.suffix.lower()
                        
                        # 字幕文件：直接生成占位字幕
                        if suffix_lower in SUBTITLE_EXTS:
                            try:
                                if file_path.exists():
                                    if self.overwrite_mode == 'never':
                                        stats['skipped'] += 1
                                        continue
                                    elif self.overwrite_mode == 'auto':
                                        existing_content = file_path.read_text(encoding='utf-8').strip()
                                        if 'fileid=' in existing_content:
                                            stats['skipped'] += 1
                                            continue
                                if self.helper.generate_subtitle_placeholder(file_path, fileid, pickcode):
                                    stats['success'] += 1
                                else:
                                    stats['failed'] += 1
                                continue
                            except Exception as sub_err:
                                logger.error(f"【Enhanced115】生成字幕占位失败：{file_path}，{sub_err}")
                                stats['failed'] += 1
                                continue
                        
                        strm_path = file_path.with_name(file_path.name + '.strm')
                        
                        # 覆盖模式检查
                        if strm_path.exists():
                            if self.overwrite_mode == 'never':
                                stats['skipped'] += 1
                                continue
                            elif self.overwrite_mode == 'auto':
                                existing_content = strm_path.read_text(encoding='utf-8').strip()
                                if existing_content.startswith('fileid='):
                                    stats['skipped'] += 1
                                    continue
                        
                        # 加入写入队列
                        write_queue.put((strm_path, fileid, pickcode))
                        
                    except Exception as e:
                        logger.error(f"【Enhanced115】处理文件失败：{e}")
                        stats['failed'] += 1
                
                # 进度回调
                if progress_callback:
                    progress_callback(stats)
            
            # 等待队列完成
            logger.info(f"【Enhanced115】遍历完成，开始等待写入队列完成，共处理{batch_count}批")
            write_queue.put(None)
            logger.info(f"【Enhanced115】等待写入队列join...")
            write_queue.join()
            logger.info(f"【Enhanced115】等待写入线程join...")
            writer_thread.join()
            
            logger.info(f"【Enhanced115】等待结果队列join...")
            result_queue.put(None)
            result_queue.join()
            logger.info(f"【Enhanced115】等待收集线程join...")
            collector_thread.join()
            
            logger.info(f"【Enhanced115】所有线程已完成")
            
            elapsed = perf_counter() - start_time
            logger.info(
                f"【Enhanced115】全量同步完成 | "
                f"总数={stats['total']} | 成功={stats['success']} | "
                f"失败={stats['failed']} | 跳过={stats['skipped']} | 耗时={elapsed:.1f}秒"
            )
            
            logger.info(f"【Enhanced115】full_sync方法返回，stats：{stats}")
            return stats
            
        except Exception as e:
            logger.error(f"【Enhanced115】全量同步异常：{e}", exc_info=True)
            logger.info(f"【Enhanced115】full_sync方法异常返回")
            return {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}

