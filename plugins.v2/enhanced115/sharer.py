"""
115分享处理模块
完全复制my_115_app的分享逻辑
"""
from pathlib import Path
from typing import Optional, Dict, Any

from app.log import logger


class Share115Handler:
    """115分享处理类"""
    
    def __init__(self, client, config: dict):
        """
        初始化分享处理器
        :param client: p115client实例
        :param config: 分享配置
        """
        self.client = client
        self.share_duration = config.get('share_duration', -1)
        self.share_password = config.get('share_password', '')
        self.movie_root_cid = config.get('movie_root_cid', '')
        self.tv_root_cid = config.get('tv_root_cid', '')
    
    def create_share(self, task_info: dict, download_hash: str, mediainfo=None) -> Optional[dict]:
        """
        创建115分享（根据task_info中的share_mode自动选择）
        
        :param task_info: 任务信息（包含share_mode）
        :param download_hash: 下载hash
        :param mediainfo: 媒体信息（可选）
        :return: 分享结果
        """
        try:
            share_mode = task_info.get('share_mode')
            
            if share_mode == 'folder':
                return self._share_folder(task_info, download_hash)
            elif share_mode == 'file':
                return self._share_files(download_hash, task_info)
            else:
                logger.error(f"【Enhanced115】未知分享模式：{share_mode}")
                return None
                
        except Exception as e:
            logger.error(f"【Enhanced115】创建分享失败：{e}")
            return None
    
    def _share_folder(self, task_info: dict, download_hash: str) -> Optional[dict]:
        """
        文件夹分享
        完全复制my_115_app的_handle_folder_share逻辑
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            # 1. 查询一个文件的路径（任意一个）
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            dest_path = None
            for record in records:
                if record.dest_storage == 'u115' and record.dest:
                    dest_path = record.dest
                    break
            
            if not dest_path:
                logger.error("【Enhanced115】未找到115文件路径")
                return None
            
            # 2. 从路径提取文件夹名
            # 例如：/Emby/电影/流浪地球2 (2023)/xxx.mkv → 流浪地球2 (2023)
            path_obj = Path(dest_path)
            folder_name = path_obj.parent.name
            
            # 3. 确定根目录CID
            is_movie = task_info.get('is_movie', False)
            root_cid = self.movie_root_cid if is_movie else self.tv_root_cid
            
            if not root_cid:
                logger.warning("【Enhanced115】未配置根目录CID")
                return None
            
            # 4. 在115中查找文件夹ID
            folder_id = self._find_folder_id(folder_name, root_cid)
            if not folder_id:
                logger.error(f"【Enhanced115】未找到115文件夹：{folder_name}")
                return None
            
            # 5. 创建分享
            share_result = self.client.share_send(
                file_id=folder_id,
                is_asc=1,
                order="user_ptime"
            )
            
            if not share_result or not share_result.get('state'):
                logger.error("【Enhanced115】创建分享失败")
                return None
            
            share_code = share_result.get('share_code')
            share_url = share_result.get('share_url')
            
            # 6. 修改分享设置
            if share_code:
                self._update_share(share_code)
            
            logger.info(f"【Enhanced115】文件夹分享已创建：{folder_name}")
            
            return {
                'share_url': share_url,
                'share_code': share_code,
                'receive_code': self.share_password,
                'media_title': task_info.get('media_title', '')
            }
            
        except Exception as e:
            logger.error(f"【Enhanced115】文件夹分享失败：{e}")
            return None
    
    def _share_files(self, download_hash: str, task_info: dict) -> Optional[dict]:
        """
        文件打包分享
        完全复制my_115_app的_handle_file_share逻辑
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            # 1. 查询所有文件的fileid
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            file_ids = []
            for record in records:
                if record.dest_storage == 'u115' and record.dest_fileitem:
                    fileid = record.dest_fileitem.get('fileid')
                    if fileid:
                        file_ids.append(fileid)
            
            if not file_ids:
                logger.error("【Enhanced115】未找到115文件ID")
                return None
            
            # 2. 创建打包分享
            share_result = self.client.share_send(file_ids)
            
            if not share_result or not share_result.get('state'):
                return None
            
            share_code = share_result.get('share_code')
            
            # 3. 修改分享设置
            if share_code:
                self._update_share(share_code)
            
            logger.info(f"【Enhanced115】文件打包分享已创建：{len(file_ids)}个文件")
            
            return {
                'share_url': share_result.get('share_url'),
                'share_code': share_code,
                'receive_code': self.share_password,
                'media_title': task_info.get('media_title', '')
            }
            
        except Exception as e:
            logger.error(f"【Enhanced115】文件打包分享失败：{e}")
            return None
    
    def _find_folder_id(self, folder_name: str, root_cid: str) -> Optional[str]:
        """
        在115根目录下查找文件夹ID
        完全复制my_115_app的_get_folder_id_from_path逻辑
        """
        try:
            from p115client.tool import iter_fs_files_serialized, normalize_attr
            
            login_app = self.client.login_app() or 'ios'
            
            logger.info(f"【Enhanced115】在根目录{root_cid}下查找：{folder_name}")
            
            for item_resp in iter_fs_files_serialized(self.client, root_cid, app=login_app):
                for item_raw in item_resp.get('data', []):
                    try:
                        item = normalize_attr(item_raw)
                        if item['is_dir'] and item['name'] == folder_name:
                            folder_id = str(item['id'])
                            logger.info(f"【Enhanced115】找到文件夹：{folder_name} (ID={folder_id})")
                            return folder_id
                    except Exception as e:
                        logger.debug(f"【Enhanced115】标准化item失败：{e}")
                        continue
            
            logger.warning(f"【Enhanced115】未找到文件夹：{folder_name}")
            return None
            
        except Exception as e:
            logger.error(f"【Enhanced115】查找文件夹失败：{e}")
            return None
    
    def _update_share(self, share_code: str):
        """修改分享设置"""
        try:
            self.client.share_update(
                share_code=share_code,
                receive_code=self.share_password if self.share_password else "",
                share_duration=self.share_duration if self.share_duration != -1 else 0,
                is_custom_code=1 if self.share_password else 0
            )
            logger.debug("【Enhanced115】分享设置已更新")
        except Exception as e:
            logger.warning(f"【Enhanced115】更新分享设置失败：{e}")
