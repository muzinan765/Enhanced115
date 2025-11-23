"""
STRM文件管理工具
用于115网盘文件的本地映射管理
"""
import re
from pathlib import Path
from typing import Optional, List, Tuple

from app.log import logger


class StrmHelper:
    """STRM文件管理类"""
    
    @staticmethod
    def generate_strm(strm_path: Path, fileid: str, pickcode: str) -> bool:
        """
        生成strm文件
        
        :param strm_path: strm文件路径
        :param fileid: 115文件ID
        :param pickcode: 115提取码
        :return: 是否成功
        """
        try:
            # 确保目录存在
            strm_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入strm内容
            content = f"fileid={fileid}\npickcode={pickcode}\n"
            strm_path.write_text(content, encoding='utf-8')
            
            logger.info(f"【Enhanced115】已生成strm文件：{strm_path.name}")
            return True
            
        except Exception as e:
            logger.error(f"【Enhanced115】生成strm文件失败：{strm_path}，错误：{e}")
            return False
    
    @staticmethod
    def read_strm(strm_path: Path) -> Optional[Tuple[str, str]]:
        """
        读取strm文件内容
        
        :param strm_path: strm文件路径
        :return: (fileid, pickcode) 或 None
        """
        try:
            if not strm_path.exists():
                return None
            
            content = strm_path.read_text(encoding='utf-8')
            lines = content.strip().split('\n')
            
            fileid = None
            pickcode = None
            
            for line in lines:
                if line.startswith('fileid='):
                    fileid = line.split('=', 1)[1].strip()
                elif line.startswith('pickcode='):
                    pickcode = line.split('=', 1)[1].strip()
            
            if fileid:
                return fileid, pickcode
            
            return None
            
        except Exception as e:
            logger.error(f"【Enhanced115】读取strm文件失败：{strm_path}，错误：{e}")
            return None
    
    @staticmethod
    def extract_episode_id(filename: str) -> Optional[str]:
        """
        从文件名提取集数标识（SXXEXX格式）
        
        :param filename: 文件名
        :return: 集数标识（如S01E06）或None
        """
        match = re.search(r'S\d{2}E\d{2}', filename, re.IGNORECASE)
        if match:
            return match.group().upper()
        return None
    
    @staticmethod
    def find_old_strms(strm_dir: Path, episode_id: Optional[str], is_movie: bool) -> List[Path]:
        """
        查找同目录下需要删除的旧strm文件
        
        :param strm_dir: strm文件所在目录
        :param episode_id: 集数标识（剧集）
        :param is_movie: 是否电影
        :return: 旧strm文件列表
        """
        if not strm_dir.exists():
            return []
        
        old_strms = []
        video_exts = {'.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.iso'}
        
        try:
            for strm_file in strm_dir.glob('*.strm'):
                # 剧集：匹配相同集数
                if not is_movie and episode_id:
                    if episode_id in strm_file.name.upper():
                        # 检查是否是视频strm（不是字幕strm）
                        # 通过去掉.strm后的扩展名判断
                        name_without_strm = strm_file.name[:-5]  # 去掉.strm
                        if Path(name_without_strm).suffix.lower() in video_exts:
                            old_strms.append(strm_file)
                
                # 电影：所有视频strm
                elif is_movie:
                    name_without_strm = strm_file.name[:-5]
                    if Path(name_without_strm).suffix.lower() in video_exts:
                        old_strms.append(strm_file)
            
            return old_strms
            
        except Exception as e:
            logger.error(f"【Enhanced115】查找旧strm失败：{strm_dir}，错误：{e}")
            return []
    
    @staticmethod
    def delete_old_files(client, old_strms: List[Path]) -> int:
        """
        删除115上的旧文件和本地旧strm
        
        :param client: p115client实例
        :param old_strms: 旧strm文件列表
        :return: 删除成功的数量
        """
        deleted_count = 0
        
        for old_strm in old_strms:
            try:
                # 读取旧文件ID
                result = StrmHelper.read_strm(old_strm)
                if not result:
                    logger.warning(f"【Enhanced115】无法读取strm内容，跳过：{old_strm.name}")
                    continue
                
                old_fileid, _ = result
                
                # 删除115文件
                try:
                    delete_result = client.fs_delete(old_fileid)
                    if delete_result and delete_result.get('state'):
                        logger.info(f"【Enhanced115】已删除115旧文件：{old_fileid}")
                        
                        # 删除本地strm
                        old_strm.unlink()
                        deleted_count += 1
                        logger.info(f"【Enhanced115】已删除旧strm：{old_strm.name}")
                    else:
                        logger.warning(f"【Enhanced115】删除115文件失败：{old_fileid}，{delete_result}")
                except Exception as del_err:
                    logger.error(f"【Enhanced115】删除115文件异常：{old_fileid}，{del_err}")
                    
            except Exception as e:
                logger.error(f"【Enhanced115】处理旧strm失败：{old_strm}，{e}")
        
        return deleted_count
    
    @staticmethod
    def generate_empty_subtitle(subtitle_path: Path) -> bool:
        """
        生成空字幕文件（占位）
        
        :param subtitle_path: 字幕文件路径
        :return: 是否成功
        """
        try:
            subtitle_path.parent.mkdir(parents=True, exist_ok=True)
            subtitle_path.touch()
            logger.debug(f"【Enhanced115】已生成空字幕文件：{subtitle_path.name}")
            return True
        except Exception as e:
            logger.error(f"【Enhanced115】生成空字幕失败：{subtitle_path}，{e}")
            return False

