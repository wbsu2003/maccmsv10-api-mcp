from pydantic import BaseModel, HttpUrl, RootModel
from typing import Dict, Optional, List

class Source(BaseModel):
    """定义单个 maccms10 API 源的数据结构"""
    name: str
    api: HttpUrl
    detail: Optional[HttpUrl] = None
    verify_ssl: bool = True

class ConfigData(BaseModel):
    """定义整个 config.json 的配置结构"""
    mcp_base_url: Optional[str] = None
    sources: Dict[str, Source] = {}

class SourcesConfig(RootModel[Dict[str, Source]]):
    """定义 sources 部分的配置结构，保持向后兼容"""
    pass # RootModel 不需要 __root__ 字段

class VideoResult(BaseModel):
    """定义搜索结果中单个视频条目的数据结构"""
    source_key: str
    source_name: str
    video_id: str
    title: str
    last_updated: str
    category: str
    # 新增的详情字段
    poster_url: Optional[str] = None  # 海报图片URL
    area: Optional[str] = None  # 地区
    language: Optional[str] = None  # 语言
    year: Optional[str] = None  # 年份
    actor: Optional[str] = None  # 演员
    director: Optional[str] = None  # 导演
    content: Optional[str] = None  # 剧情简介
    remarks: Optional[str] = None  # 备注信息

class EpisodeInfo(BaseModel):
    """定义单集播放信息"""
    episode_name: str
    web_player_url: str  # 改为 str 类型，避免 URL 长度限制
    original_m3u8_url: HttpUrl

class PlaybackInfo(BaseModel):
    """定义最终返回给用户的播放信息"""
    web_player_url: str  # 改为 str 类型，避免 URL 长度限制
    original_m3u8_url: Optional[HttpUrl] = None  # 改为可选字段，支持URL优化架构
    episodes: Optional[List[EpisodeInfo]] = None  # 多集信息（可选）

class ToolInputSearch(BaseModel):
    """定义 search_movie 工具的输入模型"""
    movie_title: str
    source_name: Optional[str] = None  # 可选参数，指定要搜索的视频源名称

class ToolInputPlayback(BaseModel):
    """定义 get_playback_info 工具的输入模型"""
    source_name: str
    video_id: str
