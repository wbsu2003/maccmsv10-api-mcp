import json
import os
from pathlib import Path
from models import SourcesConfig

CONFIG_FILE = Path(__file__).parent / "config.json"

def load_config() -> dict:
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_FILE}")
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    return data

def load_sources() -> SourcesConfig:
    """加载、验证并返回 config.json 中的 sources 配置内容"""
    data = load_config()
    
    # 如果配置文件有 sources 字段，使用它
    if 'sources' in data:
        return SourcesConfig(data['sources'])
    
    # 否则，假设整个配置文件就是 sources（向后兼容）
    # 过滤掉非 source 字段
    sources_data = {k: v for k, v in data.items() if k != 'mcp_base_url' and isinstance(v, dict)}
    return SourcesConfig(sources_data)

def get_mcp_base_url() -> str:
    """获取 MCP 基础 URL，优先级：环境变量 > 配置文件 > 默认值"""
    # 1. 优先从环境变量获取
    app_url = os.getenv('MCP_BASE_URL')
    if app_url:
        return app_url.rstrip('/')
    
    # 2. 从配置文件获取
    try:
        config = load_config()
        mcp_base_url = config.get('mcp_base_url')
        if mcp_base_url:
            return mcp_base_url.rstrip('/')
    except Exception as e:
        print(f"警告: 读取配置文件失败: {e}")
    
    # 3. 默认值
    return "http://localhost:8000"

def get_dynamic_mcp_base_url(request=None) -> str:
    """
    动态获取 MCP 基础 URL，优先级：
    1. 环境变量
    2. 配置文件（如果不是默认值且有效）
    3. HTTP 请求中的信息
    4. 默认值
    
    Args:
        request: FastAPI Request 对象，用于从请求中获取 URL 信息
    
    Returns:
        str: MCP 基础 URL
    """
    from logger_config import get_logger
    logger = get_logger(__name__)
    
    # 1. 优先从环境变量获取
    app_url = os.getenv('MCP_BASE_URL')
    if app_url:
        logger.debug(f"使用环境变量中的 MCP_BASE_URL: {app_url}")
        return app_url.rstrip('/')
    
    # 2. 从配置文件获取
    try:
        config = load_config()
        base_mcp_url = config.get('mcp_base_url', "http://localhost:8000")
    except Exception as e:
        logger.warning(f"读取配置文件失败: {e}")
        base_mcp_url = "http://localhost:8000"
    
    logger.debug(f"从配置获取的 base_mcp_url = {base_mcp_url}")
    
    # 检查配置的 URL 是否有效（不是默认值且不包含 localhost）
    is_valid_config = (
        base_mcp_url != "http://localhost:8000" and 
        'localhost' not in base_mcp_url and 
        base_mcp_url.startswith('http')
    )
    
    if is_valid_config:
        logger.debug(f"使用有效的配置 URL: {base_mcp_url}")
        return base_mcp_url.rstrip('/')
    
    # 3. 如果配置无效且提供了请求对象，尝试从请求中获取
    if request:
        logger.debug("配置的 URL 无效或是默认值，尝试从请求中获取")
        request_base_url = str(request.base_url).rstrip('/')
        logger.debug(f"request.base_url = {request.base_url}")
        
        # 如果请求的 base_url 看起来正常，使用它
        if request_base_url.startswith('http') and 'apiserver' not in request_base_url:
            logger.debug(f"使用请求的 base_mcp_url = {request_base_url}")
            return request_base_url
        else:
            # 尝试从 headers 中获取真实的主机信息
            host = (request.headers.get('x-forwarded-host') or 
                   request.headers.get('x-original-host') or
                   request.headers.get('host'))
            
            if host and 'apiserver' not in host:
                scheme = 'https' if request.headers.get('x-forwarded-proto') == 'https' else 'http'
                dynamic_url = f"{scheme}://{host}"
                logger.debug(f"使用 headers 构建的 base_mcp_url = {dynamic_url}")
                return dynamic_url
            
            logger.debug(f"所有相关 headers = {dict(request.headers)}")
    
    # 4. 默认值
    logger.debug(f"使用默认的 base_mcp_url = {base_mcp_url}")
    return base_mcp_url.rstrip('/')
