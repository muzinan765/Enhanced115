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
from app.helper.downloader import DownloaderHelper


class CleanupManager:
    """清理和重试管理器"""
    
    def __init__(self, plugin_instance, cleanup_tag: str = "已整理", max_retry_count: int = 3):
        """
        初始化清理管理器
        
        :param plugin_instance: 插件实例，用于访问配置和保存数据
        :param cleanup_tag: 整理完成标签名称（默认：已整理）
        :param max_retry_count: 最大重试次数（默认：3）
        """
        self.plugin = plugin_instance
        self._cleanup_tag = cleanup_tag
        self._max_retry_count = max_retry_count
        self._pending_hashes: Set[str] = set()  # 待检查的download_hash集合
        self._last_check_time: Dict[str, float] = {}  # 记录每个hash的最后检查时间
        
        # 初始化下载器助手（遵循MoviePilot规范）
        self._downloader_helper = DownloaderHelper()
        
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
        
        # 获取任务的expected_count（关键修复：需要验证整理数量是否达标）
        task_info = None
        expected_count = 0
        if hasattr(self.plugin, '_task_manager') and self.plugin._task_manager:
            task_info = self.plugin._task_manager.get_task(download_hash)
            if task_info:
                expected_count = task_info.get('expected_count', 0)
        
        # 统计成功/失败情况
        total = len(records)
        success_count = sum(1 for r in records if r.status)
        failed_count = total - success_count
        
        # 获取下载器信息
        downloader = records[0].downloader if records else None
        
        if failed_count == 0:
            # 检查是否达到预期数量（防止过早删除种子）
            if expected_count > 0 and total < expected_count:
                # 还有文件没有整理，等待
                logger.debug(
                    f"【Enhanced115】任务整理中（{total}/{expected_count}），"
                    f"等待剩余{expected_count - total}个文件整理：{download_hash}"
                )
                return
            
            # 全部成功且数量达标 - 执行清理
            display_count = f"{total}/{expected_count}" if expected_count > 0 else f"{total}/{total}"
            logger.info(f"【Enhanced115】任务全部整理成功（{display_count}）：{download_hash}")
            self._cleanup_completed_task(download_hash, downloader)
            self._pending_hashes.discard(download_hash)
            
        else:
            # 有失败 - 需要重试
            logger.warning(f"【Enhanced115】任务有{failed_count}个文件整理失败（{success_count}/{total}）：{download_hash}")
            
            # 获取任务信息以检查重试次数
            if task_info:
                retry_count = task_info.get('retry_count', 0)
                
                if retry_count < self._max_retry_count:
                    # 未超过重试上限，触发重试
                    logger.info(f"【Enhanced115】触发重试（第{retry_count + 1}次）：{download_hash}")
                    self._trigger_retry(download_hash, downloader, records)
                    
                    # 增加重试计数
                    if hasattr(self.plugin, '_task_manager') and self.plugin._task_manager:
                        self.plugin._task_manager.increment_retry_count(download_hash)
                    
                    # 从队列移除，避免重复处理
                    self._pending_hashes.discard(download_hash)
                else:
                    # 超过重试上限
                    logger.warning(
                        f"【Enhanced115】任务已达到最大重试次数（{self._max_retry_count}次），"
                        f"放弃重试：{download_hash}"
                    )
                    # 从队列移除
                    self._pending_hashes.discard(download_hash)
            else:
                # 无法获取任务信息，依然触发重试（保守策略）
                logger.info(f"【Enhanced115】无法获取任务信息，触发重试：{download_hash}")
                self._trigger_retry(download_hash, downloader, records)
                self._pending_hashes.discard(download_hash)
    
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
    
    def _get_downloader_instance(self, downloader_name: str):
        """
        获取下载器实例（遵循MoviePilot规范）
        
        :param downloader_name: 下载器名称
        :return: 下载器实例，失败返回None
        """
        if not downloader_name:
            return None
        
        service_info = self._downloader_helper.get_service(downloader_name)
        if service_info and service_info.instance:
            return service_info.instance
        
        logger.debug(f"【Enhanced115】未找到下载器：{downloader_name}")
        return None
    
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
            # 使用DownloaderHelper获取下载器实例（遵循MoviePilot规范）
            server = self._get_downloader_instance(downloader)
            
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
            # 使用DownloaderHelper获取下载器实例（遵循MoviePilot规范）
            server = self._get_downloader_instance(downloader)
            
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
    
    def _reannounce_torrents(self, server, torrent_hashes: list, downloader_desc: str = "下载器"):
        """
        强制种子重新汇报tracker
        
        :param server: 下载器实例
        :param torrent_hashes: 种子hash列表
        :param downloader_desc: 下载器描述（用于日志）
        """
        if not server or not torrent_hashes:
            return
        
        try:
            # 检查是否为qBittorrent（只有qBittorrent支持重新汇报）
            if not hasattr(server, 'qbc') or not server.qbc:
                logger.debug(f"【Enhanced115】{downloader_desc}下载器不支持重新汇报（非qBittorrent）")
                return
            
            # 调用qBittorrent API强制重新汇报
            server.qbc.torrents_reannounce(torrent_hashes=torrent_hashes)
            
            logger.info(f"【Enhanced115】已触发{downloader_desc}下载器{len(torrent_hashes)}个种子重新汇报tracker")
            
        except Exception as e:
            logger.error(f"【Enhanced115】{downloader_desc}下载器重新汇报失败：{e}")
    
    def _resolve_download_conflicts(self, subscribe_downloader_name: str, brush_downloader_name: str):
        """
        解决下载冲突：检查订阅下载器的tracker消息，如果有冲突则删除刷流下载器的种子
        
        :param subscribe_downloader_name: 订阅下载器名称
        :param brush_downloader_name: 刷流下载器名称
        """
        try:
            # 使用DownloaderHelper获取下载器实例（遵循MoviePilot规范）
            
            # 获取订阅下载器实例
            subscribe_server = self._get_downloader_instance(subscribe_downloader_name)
            if not subscribe_server:
                logger.debug(f"【Enhanced115】获取订阅下载器实例失败：{subscribe_downloader_name}")
                return
            
            # 获取刷流下载器实例
            brush_server = self._get_downloader_instance(brush_downloader_name)
            if not brush_server:
                logger.debug(f"【Enhanced115】获取刷流下载器实例失败：{brush_downloader_name}")
                return
            
            # 获取订阅下载器中的所有种子
            subscribe_torrents, error = subscribe_server.get_torrents()
            if error or not subscribe_torrents:
                logger.debug(f"【Enhanced115】获取订阅下载器种子失败或为空：{subscribe_downloader_name}")
                return
            
            logger.debug(f"【Enhanced115】开始检查{len(subscribe_torrents)}个订阅种子的tracker状态...")
            
            # 检查每个种子的tracker消息
            conflict_torrents = []
            for torrent in subscribe_torrents:
                torrent_hash = torrent.get('hash')
                torrent_name = torrent.get('name', 'Unknown')
                
                if not torrent_hash:
                    continue
                
                # 获取tracker详细信息（qbittorrent需要单独调用API）
                try:
                    # 检查下载器是否有qbc属性（qbittorrent专用）
                    if not hasattr(subscribe_server, 'qbc') or not subscribe_server.qbc:
                        logger.debug(f"【Enhanced115】下载器不支持tracker消息检查（非qBittorrent）")
                        break
                    
                    # 获取该种子的所有tracker信息
                    trackers = subscribe_server.qbc.torrents_trackers(torrent_hash=torrent_hash)
                    
                    # 检查所有tracker的消息
                    has_conflict = False
                    for tracker in trackers:
                        tracker_msg = tracker.get('msg', '').lower()
                        # 检查tracker消息是否包含冲突关键词
                        if 'same torrent' in tracker_msg or 'torrent already' in tracker_msg or 'already exists' in tracker_msg:
                            has_conflict = True
                            logger.info(f"【Enhanced115】发现冲突种子：{torrent_name[:50]} - tracker消息：{tracker_msg}")
                            break
                    
                    if has_conflict:
                        conflict_torrents.append(torrent)
                        
                except Exception as e:
                    logger.debug(f"【Enhanced115】获取种子tracker信息失败：{torrent_name[:30]}，错误：{e}")
                    continue
            
            if not conflict_torrents:
                logger.debug(f"【Enhanced115】未发现下载冲突")
                return
            
            logger.info(f"【Enhanced115】发现{len(conflict_torrents)}个订阅冲突种子，开始处理...")
            
            # 处理每个冲突种子
            resolved_hashes = []  # 记录成功解决冲突的种子hash
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
                        resolved_hashes.append(torrent_hash)
                    else:
                        logger.error(f"【Enhanced115】删除刷流下载器冲突种子失败：{torrent_name}")
            
            # 如果成功解决了冲突，等待5秒后触发订阅下载器重新汇报
            if resolved_hashes:
                logger.info(f"【Enhanced115】等待5秒，让tracker服务器更新状态...")
                time.sleep(5)
                
                # 强制订阅下载器重新汇报种子
                self._reannounce_torrents(subscribe_server, resolved_hashes, "订阅")
                        
        except Exception as e:
            logger.error(f"【Enhanced115】解决下载冲突异常：{e}")

