"""
115上传处理模块
"""
from pathlib import Path
from typing import Optional, Tuple

from app.log import logger


class Upload115Handler:
    """115上传处理类"""
    
    def __init__(self, client):
        """
        初始化上传处理器
        :param client: p115client实例
        """
        self.client = client
    
    def upload_file(self, local_path: Path, remote_path: str, filename: str) -> Tuple[bool, Optional[dict]]:
        """
        上传文件到115
        
        :param local_path: 本地文件路径（硬链接文件）
        :param remote_path: 115远程路径
        :param filename: 文件名
        :return: (成功标志, 115文件信息)
        """
        try:
            from p115client.tool import P115MultipartUpload
            from p115client import check_response, P115OSError
            
            if not local_path.exists():
                logger.error(f"【Enhanced115】本地文件不存在：{local_path}")
                return False, None
            
            logger.info(f"【Enhanced115】开始上传：{filename}")
            
            # 获取或创建115目录
            remote_dir = str(Path(remote_path).parent)
            pid = self._get_or_create_dir(remote_dir)
            if not pid:
                logger.error(f"【Enhanced115】无法创建115目录：{remote_dir}")
                return False, None
            
            # 初始化上传
            logger.info(f"【Enhanced115】正在初始化上传：{filename}")
            uploader = P115MultipartUpload.from_path(
                path=str(local_path),
                pid=pid,
                filename=filename,
                user_id=self.client.user_id,
                user_key=self.client.user_key
            )
            
            # 检查秒传
            if isinstance(uploader, dict):
                logger.info(f"【Enhanced115】{filename} 秒传成功")
                # 从秒传响应中提取文件信息
                data = uploader.get('data', {})
                file_info = {
                    'storage': 'u115',
                    'fileid': str(data.get('id', '')),
                    'pickcode': data.get('pickcode', ''),
                    'path': remote_path,
                    'name': filename,
                    'size': local_path.stat().st_size,  # 添加size
                    'type': 'file'
                }
                logger.info(f"【Enhanced115】秒传file_info：{file_info}")
                return True, file_info
            
            # 分片上传
            logger.info(f"【Enhanced115】开始分片上传：{filename}")
            file_size = local_path.stat().st_size
            uploaded = 0
            
            for part_info in uploader.iter_upload():
                uploaded += part_info.get('Size', 0)
                progress = (uploaded / file_size * 100) if file_size > 0 else 0
                
                # 每10MB记录一次进度
                if uploaded % (10 * 1024 * 1024) < part_info.get('Size', 0):
                    logger.debug(f"【Enhanced115】上传进度：{filename} - {progress:.1f}%")
            
            # 完成上传
            result = uploader.complete()
            check_response(result)
            
            if result.get('state'):
                logger.info(f"【Enhanced115】{filename} 上传完成")
                # 从上传完成响应中提取文件信息
                data = result.get('data', {})
                
                # 提取pickcode（分片上传时在callback中）
                pickcode = data.get('pickcode', '')
                if not pickcode:
                    # 分片上传时，pickcode在callback的callback_var中
                    # 根据p115oss源码（451行）：callback_var["x:pick_code"]
                    try:
                        import json
                        callback_data = uploader.callback
                        if isinstance(callback_data, dict) and 'callback_var' in callback_data:
                            callback_var_str = callback_data['callback_var']
                            callback_var = json.loads(callback_var_str)
                            pickcode = callback_var.get('x:pick_code', '')
                            logger.debug(f"【Enhanced115】从callback提取pickcode：{pickcode}")
                    except Exception as pick_err:
                        logger.warning(f"【Enhanced115】提取pickcode失败：{pick_err}")
                
                file_info = {
                    'storage': 'u115',
                    'fileid': str(data.get('file_id', '')),
                    'pickcode': pickcode,
                    'path': remote_path,
                    'name': filename,
                    'size': local_path.stat().st_size,
                    'type': 'file'
                }
                logger.info(f"【Enhanced115】上传file_info：{file_info}")
                return True, file_info
            else:
                logger.error(f"【Enhanced115】{filename} 上传失败：{result.get('error')}")
                return False, None
                
        except Exception as e:
            logger.error(f"【Enhanced115】上传异常：{filename}，错误：{e}")
            return False, None
    
    def _get_or_create_dir(self, remote_dir: str) -> Optional[int]:
        """
        获取或创建115目录
        :return: 目录ID
        """
        try:
            from p115client import check_response
            
            result = self.client.fs_makedirs_app(remote_dir, pid=0)
            check_response(result)
            return int(result['cid'])
        except Exception as e:
            logger.error(f"【Enhanced115】创建目录失败：{remote_dir}，错误：{e}")
            return None
    
    def _get_file_info(self, remote_path: str) -> Optional[dict]:
        """
        获取115文件信息
        """
        try:
            filename = Path(remote_path).name
            parent_dir = str(Path(remote_path).parent)
            
            # 获取父目录信息
            result = self.client.fs_makedirs_app(parent_dir, pid=0)
            if not result or not result.get('cid'):
                return None
            
            parent_cid = result['cid']
            
            # 列出目录文件
            files_result = self.client.fs_files(cid=parent_cid)
            if not files_result or not files_result.get('data'):
                return None
            
            # 查找目标文件
            for file_data in files_result['data']:
                if file_data.get('n') == filename:
                    return {
                        'storage': 'u115',
                        'fileid': str(file_data.get('fid', '')),
                        'pickcode': file_data.get('pc', ''),
                        'path': remote_path,
                        'name': filename,
                        'size': file_data.get('s', 0),
                        'type': 'file'
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"【Enhanced115】获取115文件信息失败：{e}")
            return None

