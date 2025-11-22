"""
数据库操作模块
"""
from typing import Optional

from app.log import logger


class DatabaseHandler:
    """数据库操作处理类"""
    
    @staticmethod
    def update_transfer_record(download_hash: str, remote_path: str, file_info: dict) -> bool:
        """
        更新整理记录：从local改为u115
        
        :param download_hash: 下载hash
        :param remote_path: 115远程路径
        :param file_info: 115文件信息
        :return: 是否成功
        """
        if not download_hash:
            logger.warning("【Enhanced115】download_hash为空，无法更新数据库")
            return False
        
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            from app.db import SessionFactory
            
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            if not records:
                logger.warning(f"【Enhanced115】未找到转移记录：{download_hash}")
                return False
            
            # 更新所有相关记录（可能是多集）
            updated_count = 0
            with SessionFactory() as session:
                for record in records:
                    try:
                        # 使用ORM update方法
                        record.update(session, {
                            'dest_storage': 'u115',
                            'dest': remote_path,
                            'dest_fileitem': file_info
                        })
                        updated_count += 1
                    except Exception as e:
                        logger.error(f"【Enhanced115】更新记录失败：{record.id}，错误：{e}")
                
                # 提交事务
                session.commit()
            
            if updated_count > 0:
                logger.info(f"【Enhanced115】数据库已更新：{download_hash}，{updated_count}条记录")
                return True
            else:
                return False
            
        except Exception as e:
            logger.error(f"【Enhanced115】数据库更新失败：{e}")
            return False
    
    @staticmethod
    def get_files_by_hash(download_hash: str) -> list:
        """
        获取指定download_hash的所有文件
        
        :param download_hash: 下载hash
        :return: 文件列表
        """
        try:
            from app.db.transferhistory_oper import TransferHistoryOper
            
            transferhis = TransferHistoryOper()
            records = transferhis.list_by_hash(download_hash)
            
            files = []
            for record in records:
                if record.dest_storage == 'u115' and record.dest_fileitem:
                    fileid = record.dest_fileitem.get('fileid')
                    if fileid:
                        files.append({
                            'id': fileid,
                            'name': record.dest_fileitem.get('name', ''),
                            'size': record.dest_fileitem.get('size', 0)
                        })
            
            return files
            
        except Exception as e:
            logger.error(f"【Enhanced115】查询文件失败：{e}")
            return []

