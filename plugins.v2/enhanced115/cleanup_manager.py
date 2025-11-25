"""
清理和重试管理器
处理下载任务的自动清理和失败重试逻辑
"""
import time
from typing import Set, Dict, Optional
from pathlib import Path

from app.log import logger
from app.db.transferhistory_oper import TransferHistoryOper
from app.chain import ChainBase


class CleanupManager:
    """清理和重试管理器"""
    
    def __init__(self, plugin_instance, cleanup_tag: str = "已整理"):
        """
        初始化清理管理器
        
        :param plugin_instance: 插件实例，用于访问配置和保存数据
        :param cleanup_tag: 整理完成标签名称（默认：已整理）
        """
        self.plugin = plugin_instance
        self._cleanup_tag = cleanup_tag
        self._pending_hashes: Set[str] = set()  # 待检查的download_hash集合
        self._last_check_time: Dict[str, float] = {}  # 记录每个hash的最后检查时间
        
    def add_to_check_queue(self, download_hash: str):
        """
        添加download_hash到待检查队列
        
        :param download_hash: 种子hash
        """
        if not download_hash:
            return
        
        self._pending_hashes.add(download_hash)
        logger.debug(f"【Enhanced115】已加入清理检查队列：{download_hash}")
    
    def check_and_cleanup(self, subscribe_downloader: Optional[str] = None, brush_downloader: Optional[str] = None):
        """
        批量检查待处理的download_hash并执行清理或重试
        
        :param subscribe_downloader: 订阅下载器名称
        :param brush_downloader: 刷流下载器名称
        """
        logger.info(f"【Enhanced115】清理检查服务已触发，订阅下载器：{subscribe_downloader}，刷流下载器：{brush_downloader}")
        
        # 如果配置了下载冲突解决，优先处理
        if subscribe_downloader and brush_downloader:
            try:
                self._resolve_download_conflicts(subscribe_downloader, brush_downloader)
            except Exception as e:
                logger.error(f"【Enhanced115】解决下载冲突异常：{e}")
        
        if not self._pending_hashes:
            logger.debug("【Enhanced115】清理检查队列为空")
            return
        
        logger.info(f"【Enhanced115】开始检查{len(self._pending_hashes)}个下载任务...")
        
        # 复制集合避免迭代时修改
        hashes_to_check = list(self._pending_hashes)
        
        for download_hash in hashes_to_check:
            try:
                self._process_single_task(download_hash)
            except Exception as e:
                logger.error(f"【Enhanced115】处理任务失败：{download_hash}，错误：{e}")
        
        logger.info(f"【Enhanced115】清理检查完成")
    
    def _process_single_task(self, download_hash: str):
        """
        处理单个下载任务
        
        :param download_hash: 种子hash
        """
        # 查询该任务的所有整理记录
        transferhis = TransferHistoryOper()
        records = transferhis.list_by_hash(download_hash)
        
        if not records:
            logger.debug(f"【Enhanced115】未找到整理记录：{download_hash}")
            self._pending_hashes.discard(download_hash)
            return
        
        # 统计成功/失败情况
        total = len(records)
        success_count = sum(1 for r in records if r.status)
        failed_count = total - success_count
        
        # 获取下载器信息
        downloader = records[0].downloader if records else None
        
        if failed_count == 0:
            # 全部成功 - 执行清理
            logger.info(f"【Enhanced115】任务全部整理成功（{total}/{total}）：{download_hash}")
            self._cleanup_completed_task(download_hash, downloader)
            self._pending_hashes.discard(download_hash)
            
        else:
            # 有失败 - 检查是否需要重试
            logger.warning(f"【Enhanced115】任务有{failed_count}个文件整理失败（{success_count}/{total}）：{download_hash}")
            
            # 检查种子是否已被标记
            if self._has_finished_tag(download_hash, downloader):
                logger.info(f"【Enhanced115】发现异常状态（失败但已标记），触发重试：{download_hash}")
                self._trigger_retry(download_hash, downloader, records)
            else:
                logger.debug(f"【Enhanced115】等待主程序首次整理：{download_hash}")
                # 保留在队列中，下次继续检查
    
    def _cleanup_completed_task(self, download_hash: str, downloader: Optional[str]):
        """
        清理已完成的下载任务
        
        :param download_hash: 种子hash
        :param downloader: 下载器名称
        """
        if not downloader:
            logger.warning(f"【Enhanced115】未找到下载器信息：{download_hash}")
            return
        
        try:
            # 删除种子和源文件
            result = ChainBase().remove_torrents(
                hashs=download_hash,
                delete_file=True,
                downloader=downloader
            )
            
            if result:
                logger.info(f"【Enhanced115】已删除种子和源文件：{download_hash}")
            else:
                logger.error(f"【Enhanced115】删除失败：{download_hash}")
                
        except Exception as e:
            logger.error(f"【Enhanced115】清理任务异常：{download_hash}，错误：{e}")
    
    def _trigger_retry(self, download_hash: str, downloader: Optional[str], records: list):
        """
        触发失败文件的重试
        
        :param download_hash: 种子hash
        :param downloader: 下载器名称
        :param records: 整理记录列表
        """
        if not downloader:
            logger.warning(f"【Enhanced115】未找到下载器信息：{download_hash}")
            return
        
        try:
            # 1. 删除失败的整理记录
            transferhis = TransferHistoryOper()
            deleted_count = 0
            for record in records:
                if not record.status:
                    transferhis.delete(record.id)
                    deleted_count += 1
                    logger.debug(f"【Enhanced115】已删除失败记录：{record.id} - {record.src}")
            
            if deleted_count > 0:
                logger.info(f"【Enhanced115】已删除{deleted_count}条失败记录")
            
            # 2. 删除种子的"已整理"标签
            self._remove_finished_tag(download_hash, downloader)
            
            logger.info(f"【Enhanced115】已触发重试，等待主程序重新整理：{download_hash}")
            
        except Exception as e:
            logger.error(f"【Enhanced115】触发重试异常：{download_hash}，错误：{e}")
    
    def _has_finished_tag(self, download_hash: str, downloader: Optional[str]) -> bool:
        """
        检查种子是否有"已整理"标签
        
        :param download_hash: 种子hash
        :param downloader: 下载器名称
        :return: 是否有标签
        """
        if not downloader:
            return False
        
        try:
            # 使用模块类获取种子信息（遵循MoviePilot规范）
            from app.modules.qbittorrent import QbittorrentModule
            
            qb_module = QbittorrentModule()
            server = qb_module.get_instance(downloader)
            
            if not server:
                logger.debug(f"【Enhanced115】获取下载器实例失败：{downloader}")
                return False
            
            # 获取种子信息
            torrents, _ = server.get_torrents(ids=download_hash)
            
            if not torrents:
                logger.debug(f"【Enhanced115】未找到种子：{download_hash}")
                return False
            
            torrent = torrents[0]
            tags = torrent.get('tags', '')
            
            if isinstance(tags, str):
                tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
            
            return self._cleanup_tag in tags
            
        except Exception as e:
            logger.error(f"【Enhanced115】检查标签异常：{download_hash}，错误：{e}")
            return False
    
    def _remove_finished_tag(self, download_hash: str, downloader: Optional[str]) -> bool:
        """
        删除种子的"已整理"标签
        
        :param download_hash: 种子hash
        :param downloader: 下载器名称
        :return: 是否成功
        """
        if not downloader:
            return False
        
        try:
            # 使用模块类访问下载器（遵循MoviePilot规范）
            from app.modules.qbittorrent import QbittorrentModule
            
            qb_module = QbittorrentModule()
            server = qb_module.get_instance(downloader)
            
            if not server:
                logger.warning(f"【Enhanced115】获取下载器实例失败：{downloader}")
                return False
            
            # 删除标签
            server.remove_torrents_tag(ids=download_hash, tag=[self._cleanup_tag])
            logger.info(f"【Enhanced115】已删除'{self._cleanup_tag}'标签：{download_hash}")
            return True
            
        except Exception as e:
            logger.error(f"【Enhanced115】删除标签异常：{download_hash}，错误：{e}")
            return False
    
    def get_pending_count(self) -> int:
        """
        获取待检查队列大小
        
        :return: 队列大小
        """
        return len(self._pending_hashes)
    
    def _resolve_download_conflicts(self, subscribe_downloader_name: str, brush_downloader_name: str):
        """
        解决下载冲突：检查订阅下载器的tracker消息，如果有冲突则删除刷流下载器的种子
        
        :param subscribe_downloader_name: 订阅下载器名称
        :param brush_downloader_name: 刷流下载器名称
        """
        try:
            # 使用模块类获取种子信息（遵循MoviePilot规范）
            from app.modules.qbittorrent import QbittorrentModule
            
            qb_module = QbittorrentModule()
            
            # 获取订阅下载器实例
            subscribe_server = qb_module.get_instance(subscribe_downloader_name)
            if not subscribe_server:
                logger.debug(f"【Enhanced115】获取订阅下载器实例失败：{subscribe_downloader_name}")
                return
            
            # 获取刷流下载器实例
            brush_server = qb_module.get_instance(brush_downloader_name)
            if not brush_server:
                logger.debug(f"【Enhanced115】获取刷流下载器实例失败：{brush_downloader_name}")
                return
            
            # 获取订阅下载器中的所有种子
            subscribe_torrents, error = subscribe_server.get_torrents()
            if error or not subscribe_torrents:
                logger.debug(f"【Enhanced115】获取订阅下载器种子失败或为空：{subscribe_downloader_name}")
                return
            
            # 检查每个种子的tracker消息
            conflict_torrents = []
            for torrent in subscribe_torrents:
                tracker_msg = torrent.get('tracker_msg', '').lower()
                # 检查tracker消息是否包含冲突关键词
                if 'same torrent' in tracker_msg:
                    conflict_torrents.append(torrent)
            
            if not conflict_torrents:
                return
            
            logger.info(f"【Enhanced115】发现{len(conflict_torrents)}个订阅冲突种子，开始处理...")
            
            # 处理每个冲突种子
            for conflict_torrent in conflict_torrents:
                torrent_hash = conflict_torrent.get('hash')
                torrent_name = conflict_torrent.get('name', 'Unknown')
                
                # 检查刷流下载器是否存在相同hash的种子
                brush_torrents, _ = brush_server.get_torrents(ids=torrent_hash)
                if brush_torrents:
                    logger.info(f"【Enhanced115】发现刷流下载器存在冲突种子：{torrent_name} ({torrent_hash[:8]}...)，准备删除...")
                    
                    # 删除刷流下载器的种子和文件（使用ChainBase）
                    result = ChainBase().remove_torrents(
                        hashs=torrent_hash,
                        delete_file=True,
                        downloader=brush_downloader_name
                    )
                    
                    if result:
                        logger.info(f"【Enhanced115】已删除刷流下载器中的冲突种子和文件：{torrent_name}")
                    else:
                        logger.error(f"【Enhanced115】删除刷流下载器冲突种子失败：{torrent_name}")
                        
        except Exception as e:
            logger.error(f"【Enhanced115】解决下载冲突异常：{e}")

