"""
数据库操作模块
"""
from typing import Optional

from app.log import logger


class DatabaseHandler:
    """数据库操作处理类"""
    
    @staticmethod
    def update_transfer_record(src_path: str, download_hash: str, remote_path: str, file_info: dict) -> bool:
        """
        更新整理记录：从local改为u115
        ⚠️ 关键：只更新当前文件的记录，不是所有记录！
        
        :param src_path: 源文件路径（用于匹配具体哪条记录）
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
            
            # ⚠️ 关键修复：通过src路径找到具体的那条记录
            # 一个download_hash可能有多个文件（剧集E01, E02...）
            # 必须只更新当前文件对应的记录！
            record = transferhis.get_by_src(src_path, storage='local')
            
            if not record:
                logger.warning(f"【Enhanced115】未找到转移记录：{src_path}")
                return False
            
            with SessionFactory() as session:
                try:
                    # 只更新这一条记录
                    record.update(session, {
                        'dest_storage': 'u115',
                        'dest': remote_path,
                        'dest_fileitem': file_info
                    })
                    session.commit()
                    
                    logger.info(f"【Enhanced115】数据库已更新：{record.id}，文件：{file_info.get('name')}")
                    return True
                    
                except Exception as e:
                    logger.error(f"【Enhanced115】更新记录失败：{record.id}，错误：{e}")
                    session.rollback()
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

