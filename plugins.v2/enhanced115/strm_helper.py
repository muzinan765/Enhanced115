"""
STRM文件管理工具
用于115网盘文件的本地映射管理
"""
import re
from pathlib import Path
from typing import Optional, List, Tuple, Dict

from app.log import logger
from app.helper.mediaserver import MediaServerHelper
from app.schemas import RefreshMediaItem, MediaInfo, ServiceInfo
from app.core.metainfo import MetaInfoPath
from app.chain.media import MediaChain

VIDEO_EXTS = {'.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.iso'}
SUBTITLE_EXTS = {
    '.ass', '.srt', '.ssa', '.sub', '.vtt', '.idx', '.sup',
    '.dfxp', '.lrc', '.smi', '.sami'
}


class StrmHelper:
    """STRM文件管理类"""
    
    def __init__(self, mediaserver_refresh_enabled: bool = False, 
                 mediaservers: Optional[List[str]] = None):
        """
        初始化StrmHelper
        
        :param mediaserver_refresh_enabled: 是否启用媒体服务器刷新
        :param mediaservers: 要刷新的媒体服务器列表
        """
        self.mediaserver_refresh_enabled = mediaserver_refresh_enabled
        self.mediaservers = mediaservers or []
    
    def generate_strm(self, strm_path: Path, fileid: str, pickcode: str, 
                     trigger_refresh: bool = False) -> bool:
        """
        生成strm文件
        
        :param strm_path: strm文件路径
        :param fileid: 115文件ID
        :param pickcode: 115提取码
        :param trigger_refresh: 是否触发媒体服务器刷新
        :return: 是否成功
        """
        try:
            # 确保目录存在
            strm_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入strm内容
            content = f"fileid={fileid}\npickcode={pickcode}\n"
            strm_path.write_text(content, encoding='utf-8')
            
            logger.info(f"【Enhanced115】已生成strm文件：{strm_path.name}")
            
            # 触发媒体服务器刷新（参考p115strmhelper）
            if trigger_refresh and self.mediaserver_refresh_enabled:
                self.refresh_mediaserver(
                    file_path=str(strm_path),
                    file_name=strm_path.name
                )
            
            return True
            
        except Exception as e:
            logger.error(f"【Enhanced115】生成strm文件失败：{strm_path}，错误：{e}")
            return False
    
    def refresh_mediaserver(self, file_path: str, file_name: str, 
                           mediainfo: Optional[MediaInfo] = None):
        """
        刷新媒体服务器（完全参考p115strmhelper的实现）
        
        :param file_path: strm文件路径
        :param file_name: 文件名
        :param mediainfo: 媒体信息（可选）
        """
        if not self.mediaserver_refresh_enabled:
            return
        
        if not self.mediaservers:
            logger.debug("【Enhanced115】未配置媒体服务器，跳过刷新")
            return
        
        try:
            # 获取媒体服务器实例
            mediaserver_helper = MediaServerHelper()
            services = mediaserver_helper.get_services(name_filters=self.mediaservers)
            
            if not services:
                logger.warning("【Enhanced115】获取媒体服务器实例失败")
                return
            
            # 过滤未连接的服务器
            active_services: Dict[str, ServiceInfo] = {}
            for service_name, service_info in services.items():
                if service_info.instance.is_inactive():
                    logger.warning(f"【Enhanced115】媒体服务器 {service_name} 未连接")
                else:
                    active_services[service_name] = service_info
            
            if not active_services:
                logger.warning("【Enhanced115】没有已连接的媒体服务器")
                return
            
            logger.info(f"【Enhanced115】开始刷新媒体服务器：{file_name}")
            
            # 识别媒体信息
            if not mediainfo:
                media_chain = MediaChain()
                meta = MetaInfoPath(path=Path(file_path))
                mediainfo = media_chain.recognize_media(meta=meta)
                if not mediainfo:
                    logger.warning(f"【Enhanced115】{file_name} 无法识别媒体信息，尝试刷新根目录")
                    # 无法识别时刷新根目录
                    for name, service in active_services.items():
                        if hasattr(service.instance, "refresh_root_library"):
                            service.instance.refresh_root_library()
                            logger.info(f"【Enhanced115】已触发 {name} 刷新根目录")
                    return
            
            # 构建刷新项（参考p115strmhelper）
            items = [
                RefreshMediaItem(
                    title=mediainfo.title,
                    year=mediainfo.year,
                    type=mediainfo.type,
                    category=mediainfo.category,
                    target_path=Path(file_path),
                )
            ]
            
            # 触发刷新
            for name, service in active_services.items():
                if hasattr(service.instance, "refresh_library_by_items"):
                    service.instance.refresh_library_by_items(items)
                    logger.info(f"【Enhanced115】已触发 {name} 刷新媒体库")
                elif hasattr(service.instance, "refresh_root_library"):
                    service.instance.refresh_root_library()
                    logger.info(f"【Enhanced115】已触发 {name} 刷新根目录")
                else:
                    logger.warning(f"【Enhanced115】{name} 不支持刷新")
                    
        except Exception as e:
            logger.error(f"【Enhanced115】刷新媒体服务器失败：{e}")
    
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
                normalized = line.lstrip(';# ').strip()
                if normalized.startswith('fileid='):
                    fileid = normalized.split('=', 1)[1].strip()
                elif normalized.startswith('pickcode='):
                    pickcode = normalized.split('=', 1)[1].strip()
            
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
        
        old_files: List[Path] = []
        
        try:
            for item in strm_dir.iterdir():
                try:
                    suffix = item.suffix.lower()
                    name_upper = item.name.upper()
                    
                    if suffix == '.strm':
                        name_without_strm = item.name[:-5]
                        video_suffix = Path(name_without_strm).suffix.lower()
                        if video_suffix not in VIDEO_EXTS:
                            continue
                        
                        if is_movie:
                            old_files.append(item)
                        elif episode_id and episode_id in name_upper:
                            old_files.append(item)
                    
                    elif suffix in SUBTITLE_EXTS:
                        if is_movie:
                            old_files.append(item)
                        elif episode_id and episode_id in name_upper:
                            old_files.append(item)
                except Exception as inner_err:
                    logger.debug(f"【Enhanced115】扫描目录时跳过文件：{item}，原因：{inner_err}")
                    continue
            
            return old_files
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
    def generate_subtitle_placeholder(subtitle_path: Path, fileid: str, pickcode: str) -> bool:
        """
        生成空字幕文件（占位）
        
        :param subtitle_path: 字幕文件路径
        :param fileid: 115文件ID
        :param pickcode: 115提取码
        :return: 是否成功
        """
        try:
            subtitle_path.parent.mkdir(parents=True, exist_ok=True)
            content = (
                "[Script Info]\n"
                "Title=Enhanced115 Placeholder\n"
                "ScriptType=v4.00+\n"
                f"fileid={fileid}\n"
                f"pickcode={pickcode}\n"
                "\n[V4+ Styles]\n"
                "Format=Name,Fontname,Fontsize,PrimaryColour,"
                "SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
                "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,"
                "Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
                "Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&H00000000,"
                "&H64000000,-1,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n"
                "\n[Events]\n"
                "Format=Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
                "Dialogue: 0,0:00:00.00,0:00:00.01,Default,,0,0,0,,Enhanced115 Placeholder Subtitle\n"
            )
            subtitle_path.write_text(content, encoding='utf-8')
            logger.debug(f"【Enhanced115】已生成占位字幕文件：{subtitle_path.name}")
            return True
        except Exception as e:
            logger.error(f"【Enhanced115】生成空字幕失败：{subtitle_path}，{e}")
            return False

