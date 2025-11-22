"""
115分享处理模块
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
        self.share_mode = config.get('share_mode', 'folder')
        self.share_duration = config.get('share_duration', -1)
        self.share_password = config.get('share_password', '')
        self.movie_root_cid = config.get('movie_root_cid', '')
        self.tv_root_cid = config.get('tv_root_cid', '')
    
    def create_share(self, task: dict, file_info: dict) -> Optional[dict]:
        """
        创建115分享
        
        :param task: 上传任务信息
        :param file_info: 115文件信息
        :return: 分享结果 {share_url, share_code, receive_code}
        """
        try:
            if self.share_mode == 'folder':
                return self._share_folder(task, file_info)
            else:
                return self._share_files(task, file_info)
        except Exception as e:
            logger.error(f"【Enhanced115】创建分享失败：{e}")
            return None
    
    def _share_folder(self, task: dict, file_info: dict) -> Optional[dict]:
        """文件夹分享"""
        try:
            mediainfo = task['mediainfo']
            remote_path = task['remote_path']
            
            # 解析文件夹名
            folder_name = Path(remote_path).parent.name
            
            # 确定根目录CID
            if mediainfo.type.value == '电影':
                root_cid = self.movie_root_cid
            else:
                root_cid = self.tv_root_cid
            
            if not root_cid:
                logger.warning("【Enhanced115】未配置根目录CID，跳过分享")
                return None
            
            # 查找文件夹ID
            folder_id = self._find_folder_id(folder_name, root_cid)
            if not folder_id:
                logger.error(f"【Enhanced115】未找到115文件夹：{folder_name}")
                return None
            
            # 创建分享
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
            
            # 修改分享设置
            if share_code and (self.share_password or self.share_duration != -1):
                self._update_share(share_code)
            
            logger.info(f"【Enhanced115】分享已创建：{folder_name}")
            
            return {
                'share_url': share_url,
                'share_code': share_code,
                'receive_code': self.share_password
            }
            
        except Exception as e:
            logger.error(f"【Enhanced115】文件夹分享失败：{e}")
            return None
    
    def _share_files(self, task: dict, file_info: dict) -> Optional[dict]:
        """文件打包分享"""
        try:
            download_hash = task.get('download_hash')
            if not download_hash:
                return None
            
            # 查询所有文件ID
            from app.db.transferhistory_oper import TransferHistoryOper
            
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            file_ids = []
            for record in records:
                if record.dest_storage == 'u115' and record.dest_fileitem:
                    fileid = record.dest_fileitem.get('fileid')
                    if fileid:
                        file_ids.append(fileid)
            
            if not file_ids:
                logger.warning("【Enhanced115】未找到115文件ID，无法打包分享")
                return None
            
            # 创建打包分享
            share_result = self.client.share_send(file_ids)
            
            if not share_result or not share_result.get('state'):
                return None
            
            share_code = share_result.get('share_code')
            
            # 修改分享设置
            if share_code:
                self._update_share(share_code)
            
            logger.info("【Enhanced115】文件打包分享已创建")
            
            return {
                'share_url': share_result.get('share_url'),
                'share_code': share_code,
                'receive_code': self.share_password
            }
            
        except Exception as e:
            logger.error(f"【Enhanced115】文件打包分享失败：{e}")
            return None
    
    def _find_folder_id(self, folder_name: str, root_cid: str) -> Optional[str]:
        """在115根目录下查找文件夹ID"""
        try:
            from p115client.tool import iter_fs_files_serialized, normalize_attr
            
            login_app = self.client.login_app() or 'ios'
            
            for item_resp in iter_fs_files_serialized(self.client, root_cid, app=login_app):
                for item_raw in item_resp.get('data', []):
                    try:
                        item = normalize_attr(item_raw)
                        if item['is_dir'] and item['name'] == folder_name:
                            return str(item['id'])
                    except:
                        continue
            
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

