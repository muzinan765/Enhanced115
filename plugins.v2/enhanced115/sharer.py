"""
115分享处理模块
完全复制my_115_app的分享逻辑（包括所有高级配置）
"""
import random
from pathlib import Path
from typing import Optional, Dict, Any

from app.log import logger


class Share115Handler:
    """115分享处理类"""
    
    def __init__(self, client, config: dict):
        """
        初始化分享处理器
        :param client: p115client实例
        :param config: 完整分享配置
        """
        self.client = client
        # 完整配置
        self.share_modify_enabled = config.get('share_modify_enabled', True)
        self.file_duration = config.get('file_duration', 15)
        self.folder_duration = config.get('folder_duration', -1)
        self.password_strategy = config.get('password_strategy', 'keep_initial')
        self.password_value = config.get('password_value', '')
        self.receive_user_limit = config.get('receive_user_limit', 0)
        self.skip_login_enabled = config.get('skip_login_enabled', False)
        self.skip_login_limit = config.get('skip_login_limit', '')
        self.access_user_ids = config.get('access_user_ids', '')
        self.movie_root_cid = config.get('movie_root_cid', '')
        self.tv_root_cid = config.get('tv_root_cid', '')
    
    def create_share(self, task_info: dict, download_hash: str, mediainfo=None) -> Optional[dict]:
        """
        创建115分享（根据task_info中的share_mode自动选择）
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
        文件夹分享（完全复制my_115_app逻辑）
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            # 查询一个文件路径
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
            
            # 提取文件夹名
            folder_name = Path(dest_path).parent.name
            
            # 确定根目录CID
            is_movie = task_info.get('is_movie', False)
            root_cid = self.movie_root_cid if is_movie else self.tv_root_cid
            
            if not root_cid:
                logger.warning("【Enhanced115】未配置根目录CID")
                return None
            
            # 查找文件夹ID
            folder_id = self._find_folder_id(folder_name, root_cid)
            if not folder_id:
                logger.error(f"【Enhanced115】未找到文件夹：{folder_name}")
                return None
            
            # 创建分享
            share_result = self.client.share_send_app(
                str(folder_id),
                app='ios',
                async_=False
            )
            
            if not share_result or not share_result.get('state'):
                logger.error("【Enhanced115】创建分享失败")
                return None
            
            share_data = share_result.get('data', {})
            share_code = share_data.get('share_code')
            initial_code = share_data.get('receive_code')
            
            if not share_code:
                logger.error("【Enhanced115】未获取share_code")
                return None
            
            logger.info(f"【Enhanced115】分享已创建，share_code={share_code}")
            
            final_info = {
                'share_code': share_code,
                'share_url': share_data.get('share_url', f'https://115.com/s/{share_code}').split('?')[0],
                'password': initial_code,
                'media_title': task_info.get('media_title', '')
            }
            
            # 修改分享设置（完整逻辑）
            if self.share_modify_enabled:
                final_password = self._modify_share(share_code, 'folder', initial_code)
                if final_password is not None:
                    final_info['password'] = final_password
            
            logger.info(f"【Enhanced115】文件夹分享完成：{folder_name}")
            return final_info
            
        except Exception as e:
            logger.error(f"【Enhanced115】文件夹分享失败：{e}")
            return None
    
    def _share_files(self, download_hash: str, task_info: dict) -> Optional[dict]:
        """
        文件打包分享（完全复制my_115_app逻辑）
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            file_ids = []
            for record in records:
                if record.dest_storage == 'u115' and record.dest_fileitem:
                    fileid = record.dest_fileitem.get('fileid')
                    if fileid:
                        file_ids.append(str(fileid))
            
            if not file_ids:
                logger.error("【Enhanced115】未找到文件ID")
                return None
            
            # 创建打包分享
            share_result = self.client.share_send_app(
                ",".join(file_ids),
                app='ios',
                async_=False
            )
            
            if not share_result or not share_result.get('state'):
                logger.error("【Enhanced115】创建分享失败")
                return None
            
            share_data = share_result.get('data', {})
            share_code = share_data.get('share_code')
            initial_code = share_data.get('receive_code')
            
            if not share_code:
                logger.error("【Enhanced115】未获取share_code")
                return None
            
            logger.info(f"【Enhanced115】打包分享已创建，{len(file_ids)}个文件")
            
            final_info = {
                'share_code': share_code,
                'share_url': share_data.get('share_url', f'https://115.com/s/{share_code}').split('?')[0],
                'password': initial_code,
                'media_title': task_info.get('media_title', '')
            }
            
            # 修改分享设置
            if self.share_modify_enabled:
                final_password = self._modify_share(share_code, 'file', initial_code)
                if final_password is not None:
                    final_info['password'] = final_password
            
            logger.info("【Enhanced115】文件打包分享完成")
            return final_info
            
        except Exception as e:
            logger.error(f"【Enhanced115】文件打包分享失败：{e}")
            return None
    
    def _modify_share(self, share_code: str, share_mode: str, initial_code: str) -> Optional[str]:
        """
        修改分享设置（完整逻辑）
        完全复制my_115_app的share_update逻辑
        
        :return: 最终密码
        """
        try:
            from .password_strategy import PasswordStrategy
            
            update_payload = {'share_code': share_code}
            
            # 1. 密码策略
            password = PasswordStrategy.generate_password(
                self.password_strategy,
                self.password_value,
                initial_code
            )
            
            final_password = initial_code  # 默认
            
            if password is not None:
                if self.password_strategy != 'keep_initial':
                    update_payload['receive_code'] = password
                    final_password = password
            
            # 2. 有效期（根据模式）
            if share_mode == 'folder':
                update_payload['share_duration'] = self.folder_duration
            else:
                update_payload['share_duration'] = self.file_duration
            
            # 3. 高级限制
            if self.receive_user_limit > 0:
                update_payload['receive_user_limit'] = self.receive_user_limit
            
            if self.skip_login_enabled and self.skip_login_limit:
                update_payload['skip_login_down_flow_limit'] = self.skip_login_limit
            
            if self.access_user_ids:
                update_payload['access_user_ids'] = self.access_user_ids
            
            # 4. 执行更新
            logger.debug(f"【Enhanced115】更新分享设置：{update_payload}")
            update_resp = self.client.share_update_app(update_payload, app='ios', async_=False)
            
            if not update_resp or not update_resp.get('state'):
                logger.error(f"【Enhanced115】更新分享失败：{update_resp.get('error')}")
            else:
                logger.info("【Enhanced115】分享设置已更新")
            
            # 5. 单独控制免登录（如果禁用）
            if not self.skip_login_enabled:
                try:
                    self.client.share_skip_login_down({
                        'share_code': share_code,
                        'skip_login': 0
                    }, async_=False)
                    logger.debug("【Enhanced115】已关闭免登录下载")
                except Exception as e:
                    logger.warning(f"【Enhanced115】关闭免登录失败：{e}")
            
            return final_password
            
        except Exception as e:
            logger.error(f"【Enhanced115】修改分享设置失败：{e}")
            return initial_code
    
    def _find_folder_id(self, folder_name: str, root_cid: str) -> Optional[str]:
        """
        在115根目录下查找文件夹ID
        """
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
