from fastapi import FastAPI, Request, Response
from fastapi_mcp import FastApiMCP
from starlette.staticfiles import StaticFiles
from typing import AsyncGenerator, List, Optional

import os
import httpx
import base64
import urllib.parse
import re
import xml.etree.ElementTree as ET
import asyncio
import json
import uvicorn
import logging
import time
import hashlib

from models import ToolInputSearch, ToolInputPlayback, VideoResult, PlaybackInfo, EpisodeInfo
from config import load_sources, get_mcp_base_url, get_dynamic_mcp_base_url
from logger_config import setup_logging, get_logger

# 初始化日志系统
setup_logging()
logger = get_logger(__name__)
access_logger = get_logger('access')

# 创建FastAPI应用
app = FastAPI(
    version="1.0.1",
    name="影视搜索、播放 MCP 服务",
    description="通过 SSE 协议提供影视搜索、播放功能，支持标准的苹果 CMS V10 API 格式"
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有HTTP请求"""
    start_time = asyncio.get_event_loop().time()
    
    # 记录请求开始
    access_logger.info(f"请求开始: {request.method} {request.url}")
    
    try:
        response = await call_next(request)
        process_time = asyncio.get_event_loop().time() - start_time
        
        # 记录请求完成
        access_logger.info(
            f"请求完成: {request.method} {request.url} - "
            f"状态码: {response.status_code} - 耗时: {process_time:.3f}s"
        )
        
        return response
    except Exception as e:
        process_time = asyncio.get_event_loop().time() - start_time
        access_logger.error(
            f"请求异常: {request.method} {request.url} - "
            f"错误: {str(e)} - 耗时: {process_time:.3f}s"
        )
        raise

@app.get("/")
def read_root():
    logger.info("根路径被访问")
    return {"message": "maccms v10 api MCP Service is running."}

# 健康检查端点
@app.get("/health")
async def health_check():
    """
    健康检查端点
    """
    logger.info("健康检查被调用")
    return {"status": "ok", "message": "影视查询、播放MCP服务正常运行"}

@app.get("/test-proxy")
async def test_proxy_endpoint():
    """
    测试代理端点
    """
    return {
        "message": "代理端点已更新", 
        "version": "v2.0",
        "proxy_status": "正常",
        "features": [
            "M3U8代理",
            "URL长度优化",
            "多集支持",
            "跨域处理"
        ]
    }

def generate_video_id(movie_title: str, source_name: str) -> str:
    """
    生成唯一且稳定的视频ID（相同影片和源总是生成相同ID）
    """
    content = f"{movie_title}_{source_name}"
    return hashlib.md5(content.encode()).hexdigest()[:12]

async def fetch_episodes_data(movie_title: str, source: str, original_id: str = None) -> list:
    """
    获取分集数据的核心逻辑，复用现有的搜索和数据获取逻辑
    """
    logger.info(f"获取分集数据 - 影片: {movie_title}, 源: {source}, 原始ID: {original_id}")
    
    try:
        sources_config = load_sources()
        
        source_api_url: Optional[str] = None
        source_verify_ssl: bool = True
        video_id: Optional[str] = original_id  # 使用传入的原始ID
        
        # 查找源配置
        for key, source_config in sources_config.root.items():
            if source_config.name == source:
                source_api_url = str(source_config.api)
                source_verify_ssl = source_config.verify_ssl
                break
        
        if not source_api_url:
            raise ValueError(f"未找到名为 '{source}' 的数据源配置。")
        
        # 如果没有提供原始ID，则搜索影片获取ID
        if not video_id:
            search_url = f"{source_api_url}?ac=list&wd={movie_title}"
            async with httpx.AsyncClient(timeout=15.0, verify=source_verify_ssl) as client:
                search_response = await client.get(search_url, follow_redirects=True)
                search_response.raise_for_status()
                search_data = search_response.json()
                
                if not search_data or not search_data.get('list') or len(search_data['list']) == 0:
                    raise ValueError(f"未找到影片 '{movie_title}' 的搜索结果。")
                
                # 取第一个搜索结果的video_id
                video_id = str(search_data['list'][0].get('vod_id'))
                
                if not video_id:
                    raise ValueError(f"无法获取影片 '{movie_title}' 的ID。")
        
        # 获取详细信息，增加重试机制
        max_retries = 3
        episodes_info = []
        
        for attempt in range(max_retries):
            try:
                detail_url = f"{source_api_url}?ac=detail&ids={video_id}"
                logger.debug(f"获取分集详情 (第 {attempt + 1}/{max_retries} 次): {detail_url}")
                
                async with httpx.AsyncClient(timeout=15.0, verify=source_verify_ssl) as client:
                    detail_response = await client.get(detail_url, follow_redirects=True)
                    detail_response.raise_for_status()
                    detail_data = detail_response.json()
                    
                    if not detail_data or not detail_data.get('list') or len(detail_data['list']) == 0:
                        raise ValueError(f"未找到影片 '{video_id}' 的详细信息。")
                    
                    video_detail = detail_data['list'][0]
                    vod_play_url = video_detail.get('vod_play_url')
                    
                    if not vod_play_url:
                        logger.warning(f"未找到影片 '{video_id}' 的播放地址。")
                        return []
                    
                    # 解析播放链接，返回分集信息
                    episodes_info = []
                    
                    # 按 $$ 分割不同的播放组（如果存在）
                    play_groups = vod_play_url.split('$$')
                    
                    # 找到包含 .m3u8 的播放组
                    m3u8_group = None
                    for group in play_groups:
                        if '.m3u8' in group:
                            m3u8_group = group
                            break
                    
                    if not m3u8_group:
                        # 如果没有找到 $$ 分割，尝试整个字符串
                        m3u8_group = vod_play_url
                    
                    # 解析 M3U8 播放组中的所有集数
                    episodes = m3u8_group.split('#')
                    for episode in episodes:
                        episode = episode.strip()
                        if '$' in episode and '.m3u8' in episode:
                            parts = episode.split('$', 1)
                            if len(parts) == 2:
                                episode_name = parts[0].strip()
                                episode_url = parts[1].strip()
                                
                                if episode_url.endswith('.m3u8') and (episode_url.startswith('http://') or episode_url.startswith('https://')):
                                    episodes_info.append({
                                        'title': episode_name,
                                        'url': episode_url,
                                        'source': source
                                    })
                    
                    logger.info(f"成功解析出 {len(episodes_info)} 集数据")
                    return episodes_info
                    
            except httpx.ConnectTimeout as e:
                logger.warning(f"连接超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"获取分集数据的所有重试都失败了")
                    return []
                    
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP错误 {e.response.status_code} (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"获取分集数据的所有重试都失败了")
                    return []
                    
            except Exception as e:
                logger.warning(f"获取分集数据失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"获取分集数据的所有重试都失败了")
                    return []
        
        return episodes_info
            
    except Exception as e:
        logger.error(f"获取分集数据失败: {e}")
        logger.exception("详细异常信息:")
        return []

# 新增分集数据API端点
@app.get("/api/episodes/{video_id}")
async def get_episodes_data(video_id: str, source: str, movie_title: str, originalId: str = None):
    """
    返回指定视频的所有分集数据
    """
    
    try:
        logger.info(f"API请求 - 视频ID: {video_id}, 源: {source}, 影片: {movie_title}, 原始ID: {originalId}")
        
        # 根据参数获取分集数据，优先使用originalId
        episodes_data = await fetch_episodes_data(movie_title, source, originalId)
        
        return {
            "success": True,
            "video_id": video_id,
            "movie_title": movie_title,
            "source": source,
            "episodes": episodes_data,
            "total_count": len(episodes_data),
            "timestamp": int(time.time())
        }
        
    except Exception as e:
        logger.error(f"获取分集数据失败: {e}")
        logger.exception("详细异常信息:")
        return {
            "success": False,
            "error": str(e),
            "video_id": video_id
        }

# 新增调试端点
@app.get("/debug/sources")
async def test_all_sources():
    """测试所有配置的视频源是否可用"""
    logger.info("开始测试所有视频源")
    sources_config = load_sources()
    results = {}
    
    for key, source in sources_config.root.items():
        try:
            test_url = f"{source.api}?ac=list&wd=测试"
            logger.debug(f"测试源 {key} ({source.name}): {test_url}")
            
            async with httpx.AsyncClient(timeout=3.0, verify=source.verify_ssl) as client:
                start_time = asyncio.get_event_loop().time()
                response = await client.get(test_url)
                response_time = asyncio.get_event_loop().time() - start_time
                
                results[key] = {
                    "name": source.name,
                    "status": "正常" if response.status_code == 200 else f"HTTP {response.status_code}",
                    "response_time": f"{response_time:.3f}s",
                    "url": source.api
                }
                logger.info(f"源 {key} 测试结果: {results[key]['status']}")
                
        except asyncio.TimeoutError:
            results[key] = {
                "name": source.name,
                "status": "连接超时",
                "response_time": ">3.0s",
                "url": source.api
            }
            logger.error(f"源 {key} 测试失败: 连接超时")
            
        except Exception as e:
            results[key] = {
                "name": source.name,
                "status": f"错误: {str(e)[:50]}",
                "response_time": 'N/A',
                "url": source.api
            }
            logger.error(f"源 {key} 测试失败: {str(e)}")
    
    # 统计结果
    working_sources = len([r for r in results.values() if r['status'] == '正常'])
    total_sources = len(results)
    
    logger.info(f"视频源测试完成，共测试 {total_sources} 个源，{working_sources} 个正常工作")
    return {
        "total_sources": total_sources,
        "working_sources": working_sources, 
        "success_rate": f"{working_sources/total_sources*100:.1f}%",
        "results": results
    }

# 定义 search_movie 工具作为 FastAPI 端点
@app.post("/tools/search_movie", operation_id="search_movie")
async def search_movie_endpoint(tool_input: ToolInputSearch) -> List[VideoResult]:
    """
    接收一个影片标题，搜索指定的或所有已配置的 maccms10 API 源，返回一个格式化后的可用播放源列表。
    
    参数说明：
    - movie_title: 要搜索的影片标题
    - source_name: 可选，指定要搜索的视频源名称。如果不指定，则搜索所有源
    """
    try:
        movie_title = tool_input.movie_title
        specified_source_name = tool_input.source_name
        
        if specified_source_name:
            logger.info(f"开始搜索电影: '{movie_title}' (仅搜索源: '{specified_source_name}')")
        else:
            logger.info(f"开始搜索电影: '{movie_title}' (搜索所有源)")
        
        sources_config = load_sources()
        logger.info(f"加载了 {len(sources_config.root)} 个视频源配置")
        
        # 根据是否指定源名称来筛选要搜索的源
        sources_to_search = {}
        if specified_source_name:
            # 查找指定的源
            found_source = False
            for key, source in sources_config.root.items():
                if source.name == specified_source_name:
                    sources_to_search[key] = source
                    found_source = True
                    break
            
            if not found_source:
                available_sources = [source.name for source in sources_config.root.values()]
                error_msg = f"未找到名为 '{specified_source_name}' 的视频源。可用的源: {', '.join(available_sources)}"
                logger.error(error_msg)
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail=error_msg)
        else:
            # 搜索所有源
            sources_to_search = sources_config.root
        
        logger.info(f"将搜索 {len(sources_to_search)} 个视频源")
        
        async def fetch_single_source(key, source, movie_title):
            url = f"{source.api}?ac=list&wd={movie_title}"
            async with httpx.AsyncClient(timeout=10.0, verify=source.verify_ssl) as client:
                return await fetch_and_parse_search_result(client, key, source.name, url)

        tasks = [fetch_single_source(key, source, movie_title) for key, source in sources_to_search.items()]
        logger.debug(f"创建了 {len(tasks)} 个并发搜索任务")
            
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_videos = []
        failed_sources = []
        successful_sources = 0
        
        for i, res in enumerate(results):
            source_key = list(sources_to_search.keys())[i]
            source_name = list(sources_to_search.values())[i].name
            
            try:
                if isinstance(res, list):
                    all_videos.extend(res)
                    successful_sources += 1
                    logger.debug(f"源 '{source_name}' 成功返回 {len(res)} 个结果")
                elif isinstance(res, Exception):
                    failed_sources.append(f"{source_name}: {str(res)}")
                    logger.error(f"源 '{source_name}' 搜索失败: {res}")
            except Exception as e:
                failed_sources.append(f"{source_name}: 处理结果时出错 - {str(e)}")
                logger.error(f"处理源 '{source_name}' 的搜索结果时发生错误: {e}")
                logger.exception("详细异常信息:")
        
        search_scope = f"指定源 '{specified_source_name}'" if specified_source_name else "所有源"
        logger.info(
            f"搜索 '{movie_title}' 完成 ({search_scope}): "
            f"成功 {successful_sources} 个源，失败 {len(failed_sources)} 个源，"
            f"共找到 {len(all_videos)} 个结果"
        )
        
        if failed_sources:
            logger.warning(f"失败的源详情: {failed_sources}")
                
        return all_videos
        
    except Exception as e:
        logger.error(f"search_movie_endpoint 发生未处理的异常: {e}")
        logger.exception("详细异常信息:")
        raise

async def fetch_and_parse_search_result(client: httpx.AsyncClient, source_key: str, source_name: str, url: str) -> List[VideoResult]:
    """请求单个 API 源并解析其返回的搜索结果，同时获取影片详情信息。"""
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            logger.debug(f"请求源 '{source_name}' (尝试 {attempt + 1}/{max_retries}): {url}")
            
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            data = response.json()
            logger.debug(f"源 '{source_name}' 响应成功，状态码: {response.status_code}")

            videos = []
            if data and data.get('list') and isinstance(data['list'], list):
                logger.debug(f"源 '{source_name}' 返回 {len(data['list'])} 个搜索结果")
                
                # 收集所有视频ID，批量获取详情
                video_ids = [str(item.get('vod_id')) for item in data['list'] if item.get('vod_id')]
                
                # 获取详情信息
                detail_info = {}
                if video_ids:
                    detail_info = await fetch_video_details(client, url, video_ids)
                
                for item in data['list']:
                    video_id = str(item.get('vod_id'))
                    logger.debug(f"解析视频 - 源: {source_name}, ID: {video_id}, 标题: {item.get('vod_name')}")
                    
                    # 从详情信息中获取额外数据
                    detail = detail_info.get(video_id, {})
                    
                    video = VideoResult(
                        source_key=source_key,
                        source_name=source_name,
                        video_id=video_id,
                        title=item.get('vod_name'),
                        last_updated=item.get('vod_time'),
                        category=item.get('type_name'),
                        poster_url=detail.get('vod_pic'),
                        area=detail.get('vod_area'),
                        language=detail.get('vod_lang'),
                        year=detail.get('vod_year'),
                        actor=detail.get('vod_actor'),
                        director=detail.get('vod_director'),
                        content=detail.get('vod_content'),
                        remarks=detail.get('vod_remarks') or item.get('vod_remarks')
                    )
                    videos.append(video)
            else:
                logger.warning(f"源 '{source_name}' 返回的数据格式异常或为空")
                
            logger.info(f"源 '{source_name}' 成功解析出 {len(videos)} 个视频")
            return videos
            
        except httpx.HTTPStatusError as e:
            error_msg = f"源 '{source_name}' HTTP 错误 {e.response.status_code}: {e.response.reason_phrase}"
            logger.error(f"{error_msg}, URL: {url}")
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"将在 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"源 '{source_name}' 已达最大重试次数，放弃请求")
                # 记录详细的响应信息用于调试
                try:
                    if hasattr(e.response, 'text'):
                        response_text = e.response.text[:500]
                        logger.debug(f"HTTP错误响应内容前500字符: {response_text}")
                except Exception as log_error:
                    logger.debug(f"无法获取响应内容: {log_error}")
                return []
                
        except httpx.ConnectError as e:
            error_msg = f"源 '{source_name}' 连接失败: {str(e)}"
            logger.error(f"{error_msg}, URL: {url}")
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"连接失败，将在 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"源 '{source_name}' 连接失败，已达最大重试次数")
                return []
                
        except httpx.RequestError as e:
            error_msg = f"源 '{source_name}' 请求失败: {str(e)}"
            logger.error(f"{error_msg}, URL: {url}")
            return []
            
        except json.JSONDecodeError as e:
            error_msg = f"源 '{source_name}' JSON 解析失败: {str(e)}"
            logger.error(f"{error_msg}, URL: {url}")
            
            # 记录响应内容用于调试
            try:
                if 'response' in locals():
                    response_preview = response.text[:1000] if len(response.text) > 1000 else response.text
                    logger.debug(f"无效的 JSON 响应内容: {response_preview}")
            except Exception as log_error:
                logger.debug(f"无法获取响应内容用于调试: {log_error}")
            return []
            
        except Exception as e:
            error_msg = f"源 '{source_name}' 发生未知错误: {str(e)}"
            logger.error(f"{error_msg}, URL: {url}")
            logger.exception("详细异常信息:")
            return []
    
    # 如果所有重试都失败了
    logger.error(f"源 '{source_name}' 所有重试均失败")
    return []

async def fetch_video_details(client: httpx.AsyncClient, search_url: str, video_ids: List[str]) -> dict:
    """
    批量获取影片详情信息
    
    Args:
        client: HTTP客户端
        search_url: 搜索URL，用于构建详情API URL
        video_ids: 视频ID列表
    
    Returns:
        dict: 以video_id为key的详情信息字典
    """
    if not video_ids:
        return {}
    
    try:
        # 从搜索URL构建详情API URL
        base_url = search_url.split('?')[0]  # 获取基础URL
        ids_param = ','.join(video_ids[:20])  # 限制一次最多查询20个，避免URL过长
        detail_url = f"{base_url}?ac=detail&ids={ids_param}"
        
        logger.debug(f"获取详情信息 - URL: {detail_url}")
        
        response = await client.get(detail_url, follow_redirects=True)
        response.raise_for_status()
        
        detail_data = response.json()
        
        # 构建以video_id为key的详情字典
        details_dict = {}
        if detail_data and detail_data.get('list') and isinstance(detail_data['list'], list):
            for detail_item in detail_data['list']:
                video_id = str(detail_item.get('vod_id'))
                if video_id:
                    details_dict[video_id] = detail_item
                    logger.debug(f"获取到详情 - ID: {video_id}, 海报: {detail_item.get('vod_pic', 'N/A')}")
        
        logger.debug(f"成功获取 {len(details_dict)} 个视频的详情信息")
        return details_dict
        
    except Exception as e:
        logger.error(f"获取详情信息时发生错误: {e}")
        logger.exception("详细异常信息:")
        return {}

# 定义 get_playback_info 工具作为 FastAPI 端点（新版本 - 返回简短URL）
@app.post("/tools/get_playback_info", operation_id="get_playback_info")
async def get_playback_info_endpoint(tool_input: ToolInputPlayback, request: Request) -> PlaybackInfo:
    """
    返回播放器页面URL，而不是包含所有数据的超长URL
    
    参数说明：
    - source_name: 数据源的中文名称（如 "电影天堂资源"）
    - video_id: 影片的数字ID（从 search_movie 结果中获取，如 "12345"）
    
    注意：video_id 必须是从 search_movie 返回结果中的 video_id 字段获取的实际数字ID。
    """
    try:
        source_name = tool_input.source_name
        movie_id = tool_input.video_id
        
        logger.info(f"获取播放信息 - 源: {source_name}, 视频ID: {movie_id}")

        sources_config = load_sources()
        
        # 查找源配置
        source_api_url: Optional[str] = None
        source_verify_ssl: bool = True
        for key, source in sources_config.root.items():
            if source.name == source_name:
                source_api_url = str(source.api)
                source_verify_ssl = source.verify_ssl
                break
        
        if not source_api_url:
            raise ValueError(f"未找到名为 '{source_name}' 的数据源配置。")

        # 获取影片详细信息，增加重试和更好的错误处理
        detail_url = f"{source_api_url}?ac=detail&ids={movie_id}"
        movie_title = "未知视频"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.debug(f"尝试获取影片详情 (第 {attempt + 1}/{max_retries} 次): {detail_url}")
                
                async with httpx.AsyncClient(timeout=15.0, verify=source_verify_ssl) as client:
                    response = await client.get(detail_url, follow_redirects=True)
                    response.raise_for_status()
                    data = response.json()

                if data and data.get('list') and isinstance(data['list'], list) and len(data['list']) > 0:
                    video_detail = data['list'][0]
                    movie_title = video_detail.get('vod_name', '未知视频')
                    logger.info(f"成功获取影片信息: {movie_title}")
                    break
                else:
                    logger.warning(f"未找到影片 '{movie_id}' 的详细信息，尝试使用默认标题")
                    
            except httpx.ConnectTimeout as e:
                logger.warning(f"连接超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                else:
                    logger.error(f"所有重试都失败了，使用默认影片标题")
                    
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP错误 {e.response.status_code} (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"所有重试都失败了，使用默认影片标题")
                    
            except Exception as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"所有重试都失败了，使用默认影片标题")

        # 即使无法获取影片详情，我们仍然可以生成播放器URL
        # 生成唯一的视频ID
        video_id = generate_video_id(movie_title, source_name)
        
        # 获取基础URL
        base_url = get_dynamic_mcp_base_url(request)
        
        # 返回简洁的播放器URL，包含原始的movie_id用于后续API调用
        player_url = f"{base_url}/static/player.html?videoId={video_id}&source={urllib.parse.quote(source_name)}&movieTitle={urllib.parse.quote(movie_title)}&index=0&originalId={movie_id}"
        
        logger.info(f"生成简洁播放器URL: {player_url}")
        
        # 为了保持兼容性，我们仍然返回PlaybackInfo格式，但episodes为空
        return PlaybackInfo(
            web_player_url=player_url,
            original_m3u8_url=None,  # 这些数据将通过API异步获取
            episodes=None  # 这些数据将通过API异步获取
        )
        
    except Exception as e:
        logger.error(f"get_playback_info_endpoint 发生异常: {e}")
        logger.exception("详细异常信息:")
        
        # 即使发生异常，我们也尝试返回一个基本的播放器URL
        try:
            source_name = tool_input.source_name
            movie_id = tool_input.video_id
            video_id = generate_video_id(f"视频_{movie_id}", source_name)
            base_url = get_dynamic_mcp_base_url(request)
            
            fallback_url = f"{base_url}/static/player.html?videoId={video_id}&source={urllib.parse.quote(source_name)}&movieTitle={urllib.parse.quote('未知视频')}&index=0&originalId={movie_id}"
            
            logger.info(f"使用fallback播放器URL: {fallback_url}")
            
            return PlaybackInfo(
                web_player_url=fallback_url,
                original_m3u8_url=None,
                episodes=None
            )
        except Exception as fallback_error:
            logger.error(f"Fallback也失败了: {fallback_error}")
            raise e


# Web 播放代理（支持URL编码）
@app.get("/proxy/")
async def proxy_m3u8_url_encoded(request: Request):
    """代理m3u8文件，支持URL编码的参数"""
    # 从查询参数获取URL
    target_url = None
    query_string = str(request.url.query)
    
    # 解析查询参数，查找编码的URL
    if query_string:
        # 简单解析，获取第一个参数作为目标URL
        # 格式: /proxy/?https%3A%2F%2Fexample.com%2Ffile.m3u8
        try:
            # 如果查询字符串不包含=，则整个字符串就是编码的URL
            if '=' not in query_string:
                target_url = urllib.parse.unquote(query_string)
            else:
                # 如果包含=，可能是其他参数，暂时不处理
                pass
        except Exception as e:
            print(f"调试: URL解码失败: {e}")
            return Response(status_code=400, content="Invalid URL encoding")
    
    # 如果没有从查询参数获取到URL，尝试从路径获取
    if not target_url:
        path = request.url.path
        if path.startswith('/proxy/'):
            path_part = path[7:]  # 移除 '/proxy/' 前缀
            if path_part:
                try:
                    target_url = urllib.parse.unquote(path_part)
                except Exception as e:
                    print(f"调试: 路径URL解码失败: {e}")
                    return Response(status_code=400, content="Invalid URL encoding")
    
    if not target_url:
        return Response(status_code=400, content="Missing target URL")
        
    print(f"调试: URL编码代理请求，target_url = {target_url}")
    
    if not (target_url.startswith("http://") or target_url.startswith("https://")):
        print(f"调试: 无效的 URL 格式")
        return Response(status_code=400, content="Invalid URL format")

    # 使用相同的代理逻辑
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        }
        
        # 设置 Referer
        try:
            parsed_url = urllib.parse.urlparse(target_url)
            headers['Referer'] = f"{parsed_url.scheme}://{parsed_url.netloc}"
        except:
            pass

        print(f"调试: 代理请求 {target_url}")
        
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            proxy_response = await client.get(target_url, headers=headers, timeout=30.0)
            proxy_response.raise_for_status()
            
            print(f"调试: 请求成功，状态码: {proxy_response.status_code}")
            
            content = proxy_response.content
            content_type = proxy_response.headers.get('content-type', 'application/octet-stream')
            
            # 如果是m3u8文件，处理相对路径
            if 'm3u8' in content_type.lower() or target_url.endswith('.m3u8'):
                try:
                    decoded_content = content.decode('utf-8')
                    print(f"调试: M3U8 内容长度: {len(decoded_content)}")
                    
                    # 获取配置的基础URL
                    configured_base_url = get_dynamic_mcp_base_url()
                    print(f"调试: 使用基础URL: {configured_base_url}")
                    
                    def replace_relative_paths(match):
                        relative_path = match.group(0).strip()
                        if relative_path.startswith("#") or relative_path.startswith("http"):
                            return relative_path
                        
                        absolute_url = urllib.parse.urljoin(target_url, relative_path)
                        encoded_absolute_url = urllib.parse.quote(absolute_url, safe='')
                        return f"{configured_base_url}/proxy/{encoded_absolute_url}"

                    processed_content = re.sub(r"^(?!https?://).*$", replace_relative_paths, decoded_content, flags=re.MULTILINE)
                    content = processed_content.encode('utf-8')
                    
                    content_type = "application/vnd.apple.mpegurl"
                    print(f"调试: 处理后的 M3U8 内容长度: {len(content)}")
                except UnicodeDecodeError:
                    print("调试: M3U8 解码失败，直接返回二进制内容")

            # 构建响应头
            response_headers = {}
            for key, value in proxy_response.headers.items():
                key_lower = key.lower()
                if key_lower not in ['content-encoding', 'content-length', 'transfer-encoding']:
                    response_headers[key] = value
            
            response_headers['Access-Control-Allow-Origin'] = '*'
            response_headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response_headers['Access-Control-Allow-Headers'] = '*'
            if content_type:
                response_headers['Content-Type'] = content_type
            
            return Response(
                content=content,
                status_code=proxy_response.status_code,
                headers=response_headers
            )
            
    except Exception as e:
        print(f"调试: 代理请求异常: {e}")
        return Response(status_code=500, content=f"Proxy error: {str(e)}")


# Web 播放代理（原有的base64编码版本，修改支持URL编码）
@app.get("/proxy/{encoded_url:path}")
async def proxy_m3u8(encoded_url: str, request: Request):
    print(f"调试: 代理请求开始，encoded_url = {encoded_url}")
    try:
        # 解码目标 URL - 先尝试URL解码，如果失败再尝试base64解码
        original_url = None
        
        # 首先尝试URL解码
        try:
            original_url = urllib.parse.unquote(encoded_url)
            print(f"调试: URL解码成功，original_url = {original_url}")
        except Exception as e:
            print(f"调试: URL 解码失败: {e}")
        
        # 如果URL解码失败或结果不像有效URL，尝试base64解码
        if not original_url or not (original_url.startswith("http://") or original_url.startswith("https://")):
            try:
                original_url = base64.urlsafe_b64decode(encoded_url).decode()
                print(f"调试: Base64解码成功，original_url = {original_url}")
            except Exception as e:
                print(f"调试: Base64 解码也失败: {e}")
                return Response(status_code=400, content="Invalid encoded URL")
            
        print(f"调试: 解码后的 URL = {original_url}")
        
        if not (original_url.startswith("http://") or original_url.startswith("https://")):
            print(f"调试: 无效的 URL 格式")
            return Response(status_code=400, content="Invalid URL format")

        # 使用简化的请求头，避免 gzip 压缩问题
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            # 不设置 Accept-Encoding，让 httpx 自动处理
        }
        
        # 设置 Referer
        try:
            parsed_url = urllib.parse.urlparse(original_url)
            headers['Referer'] = f"{parsed_url.scheme}://{parsed_url.netloc}"
        except:
            pass

        print(f"调试: 代理请求 {original_url}")
        
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            proxy_response = await client.get(original_url, headers=headers, timeout=30.0)
            proxy_response.raise_for_status()
            
            print(f"调试: 请求成功，状态码: {proxy_response.status_code}")
            
            content_type = proxy_response.headers.get("Content-Type", "application/octet-stream")
            print(f"调试: Content-Type: {content_type}")
            
            # 检查是否是 M3U8 内容
            is_m3u8 = (
                "application/x-mpegURL" in content_type or 
                "audio/mpegurl" in content_type or
                "application/vnd.apple.mpegurl" in content_type or
                original_url.endswith('.m3u8')
            )
            
            if is_m3u8:
                print("调试: 检测到 M3U8 内容，进行处理")
                # 对于 M3U8 内容，使用 .text 获取文本内容
                decoded_content = proxy_response.text
                base_url = original_url.rsplit('/', 1)[0] + '/'
                print(f"调试: Base URL: {base_url}")

                def replace_relative_paths(match):
                    path = match.group(0).strip()
                    if path.startswith('#'):
                        return path
                    
                    absolute_path = urllib.parse.urljoin(base_url, path)
                    encoded_absolute_path = base64.urlsafe_b64encode(absolute_path.encode()).decode()
                    
                    # 使用配置的 MCP 基础 URL 而不是请求的 base_url
                    configured_base_url = get_dynamic_mcp_base_url()
                    return f"{configured_base_url}/proxy/{encoded_absolute_path}"

                processed_content = re.sub(r"^(?!https?://).*$", replace_relative_paths, decoded_content, flags=re.MULTILINE)
                content = processed_content.encode('utf-8')
                
                # 设置正确的 M3U8 Content-Type
                content_type = "application/vnd.apple.mpegurl"
                
                print(f"调试: 处理后的 M3U8 内容长度: {len(content)}")
            else:
                print("调试: 非 M3U8 内容，直接返回")
                # 对于非 M3U8 内容，使用 .content 获取二进制内容
                content = proxy_response.content

            # 构建响应头，移除可能有问题的头
            response_headers = {}
            for key, value in proxy_response.headers.items():
                key_lower = key.lower()
                # 跳过可能导致问题的头
                if key_lower not in ['content-encoding', 'content-length', 'transfer-encoding']:
                    response_headers[key] = value
            
            # 设置缓存头
            response_headers['Cache-Control'] = 'public, max-age=3600'
            
            print(f"调试: 最终内容长度: {len(content)}")
            print(f"调试: 最终 Content-Type: {content_type}")
            
            return Response(
                content=content, 
                media_type=content_type, 
                headers=response_headers
            )

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP 错误 {e.response.status_code}: {e.response.reason_phrase}"
        print(f"调试: {error_msg}")
        
        if e.response.status_code == 403:
            error_msg = "视频服务器拒绝访问 (403 Forbidden)。这可能是由于地理位置限制或防盗链保护。"
            
        return Response(
            status_code=e.response.status_code, 
            content=error_msg,
            headers={"Content-Type": "text/plain; charset=utf-8"}
        )
    except httpx.RequestError as e:
        error_msg = f"网络请求失败: {str(e)}"
        print(f"调试: {error_msg}")
        return Response(status_code=500, content=error_msg)
    except Exception as e:
        error_msg = f"代理发生未知错误: {str(e)}"
        print(f"调试: {error_msg}")
        import traceback
        traceback.print_exc()
        return Response(status_code=500, content=error_msg)

# 初始化MCP服务（无base_url参数）
mcp = FastApiMCP(app)

# 挂载MCP路由
mcp.mount()

# 必须在所有路由定义后调用
mcp.setup_server()

if __name__ == "__main__":
    # 使用导入字符串格式解决reload问题
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="debug"
    )