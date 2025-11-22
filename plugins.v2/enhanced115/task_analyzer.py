"""
任务分析模块 - 智能判断分享模式
完全复制my_115_app的判断逻辑
"""
import re
from typing import Tuple, Optional

from app.log import logger


class TaskAnalyzer:
    """任务分析器 - 智能判断分享模式"""
    
    @staticmethod
    def analyze_share_mode(download_history, message_text: str = "") -> Tuple[Optional[str], int]:
        """
        智能判断分享模式和预期文件数
        完全复制my_115_app的逻辑
        
        :param download_history: MoviePilot的下载记录对象
        :param message_text: 从message表查询的文本
        :return: (share_mode, expected_count)
        
        判断逻辑：
        - 电影：固定folder模式
        - 电视剧：根据三个条件智能判断
        """
        mtype = download_history.type
        
        # 电影：固定folder模式
        if mtype == '电影':
            return 'folder', 1
        
        # 电视剧：智能判断
        if mtype == '电视剧':
            return TaskAnalyzer._analyze_tv_show(download_history, message_text)
        
        return None, 0
    
    @staticmethod
    def _analyze_tv_show(download_history, message_text: str) -> Tuple[str, int]:
        """
        分析电视剧任务
        """
        # 1. 收集所有数据源
        desc_str = download_history.torrent_description or ''
        name_str = download_history.torrent_name or ''
        
        # 合并所有文本用于搜索
        combined_search_text = f"{desc_str} {name_str} {message_text}"
        
        # 2. 提取episodes字段（如"E01-E12"）
        ep_str = download_history.episodes or ''
        parts = re.findall(r'(\d+)', ep_str)
        
        # 3. 计算预期文件数
        expected_count = 0
        if len(parts) == 1:
            expected_count = 1  # 单集
        elif len(parts) > 1:
            try:
                # E01-E12 → 12-1+1=12
                expected_count = int(parts[-1]) - int(parts[0]) + 1
            except (ValueError, IndexError):
                expected_count = len(parts)
        
        if expected_count == 0:
            expected_count = 1
        
        # 4. 智能判断分享模式（三个条件）
        
        # 条件A：是否全季种子
        # 搜索："全X集"、"全集"、"完结"
        is_full_season_torrent = bool(
            re.search(r'全\d{1,3}集|全集|完结', combined_search_text, re.IGNORECASE)
        )
        
        # 条件B：是否多集下载
        is_multi_episode_download = len(parts) > 1
        
        # 条件C：是否从第1集开始
        starts_from_first_episode = False
        if parts:
            try:
                if int(parts[0]) == 1:
                    starts_from_first_episode = True
            except ValueError:
                pass
        
        # 5. 决策逻辑（核心）
        # 只有三个条件都满足才用folder模式
        if is_full_season_torrent and is_multi_episode_download and starts_from_first_episode:
            share_mode = 'folder'  # 整季文件夹分享
        else:
            share_mode = 'file'    # 文件打包分享
        
        logger.debug(
            f"【Enhanced115】判断结果：{share_mode}，"
            f"全季={is_full_season_torrent}，多集={is_multi_episode_download}，"
            f"从1开始={starts_from_first_episode}，预期={expected_count}集"
        )
        
        return share_mode, expected_count
    
    @staticmethod
    def query_message_text(download_history):
        """
        从message表查询相关消息文本
        用于判断"完结"等关键字
        """
        try:
            torrent_name = download_history.torrent_name
            if not torrent_name:
                return ""
            
            # 使用原始SQL查询（最可靠的方式）
            from app.db import SessionFactory
            
            with SessionFactory() as session:
                # 直接SQL查询
                sql = """
                    SELECT text FROM message 
                    WHERE mtype = '资源下载' 
                      AND text LIKE :pattern 
                    ORDER BY reg_time DESC 
                    LIMIT 1
                """
                result = session.execute(sql, {'pattern': f'%{torrent_name}%'})
                row = result.fetchone()
                
                if row:
                    return row[0] or ''
            
            return ""
            
        except Exception as e:
            logger.warning(f"【Enhanced115】查询message失败：{e}")
            return ""


# 判断示例说明
"""
示例1：整季下载
episodes = "E01-E12"
torrent_name = "[某组]权力的游戏.S08.全12集.完结.1080p"
→ parts = [1, 12]
→ expected_count = 12
→ A=True（包含"全12集""完结"）
→ B=True（多集）
→ C=True（从1开始）
→ share_mode = 'folder'  ✅ 分享整个S08文件夹

示例2：单集下载
episodes = "E05"
torrent_name = "[某组]权力的游戏.S08E05.1080p"
→ parts = [5]
→ expected_count = 1
→ A=False（没有"全集""完结"）
→ B=False（单集）
→ C=False（不从1开始）
→ share_mode = 'file'  ✅ 分享单个文件

示例3：补集下载
episodes = "E10-E12"
torrent_name = "[某组]权力的游戏.S08E10-E12.1080p"
→ parts = [10, 12]
→ expected_count = 3
→ A=False（没有"全集"）
→ B=True（多集）
→ C=False（不从1开始）
→ share_mode = 'file'  ✅ 打包分享3个文件

示例4：全集但从中间开始（罕见）
episodes = "E05-E12"
torrent_name = "[某组]权力的游戏.S08.全集.1080p"
→ parts = [5, 12]
→ expected_count = 8
→ A=True（有"全集"）
→ B=True（多集）
→ C=False（从5开始，不是1）
→ share_mode = 'file'  ✅ 打包分享8个文件（不是整季）
"""

