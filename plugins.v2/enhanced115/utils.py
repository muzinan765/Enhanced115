"""
工具函数模块
"""
from pathlib import Path
from typing import Optional, List, Dict


def map_local_to_remote(local_path: str, path_mappings: List[Dict]) -> Optional[str]:
    """
    将本地路径映射为115远程路径
    
    :param local_path: 本地路径
    :param path_mappings: 路径映射配置 [{"local": "/media", "remote": "/Emby"}]
    :return: 115远程路径
    
    示例：
    local_path = "/media/电影/流浪地球2 (2023)/流浪地球2.mkv"
    mapping = {"local": "/media", "remote": "/Emby"}
    返回 = "/Emby/电影/流浪地球2 (2023)/流浪地球2.mkv"
    """
    if not path_mappings:
        return None
    
    local_path_obj = Path(local_path)
    
    # 尝试每个映射配置
    for mapping in path_mappings:
        local_prefix = mapping.get('local', '')
        remote_prefix = mapping.get('remote', '')
        
        if not local_prefix or not remote_prefix:
            continue
        
        try:
            local_prefix_obj = Path(local_prefix)
            
            # 检查local_path是否在这个前缀下
            if local_path_obj.is_relative_to(local_prefix_obj):
                # 计算相对路径
                relative = local_path_obj.relative_to(local_prefix_obj)
                # 拼接远程路径
                remote_path_obj = Path(remote_prefix) / relative
                return remote_path_obj.as_posix()
        except:
            continue
    
    return None


def parse_path_mappings(mappings_config: str) -> List[Dict]:
    """
    解析路径映射配置
    
    :param mappings_config: JSON字符串或列表
    :return: 路径映射列表
    """
    import json
    
    if not mappings_config:
        return []
    
    try:
        if isinstance(mappings_config, str):
            return json.loads(mappings_config)
        elif isinstance(mappings_config, list):
            return mappings_config
        else:
            return []
    except:
        return []

