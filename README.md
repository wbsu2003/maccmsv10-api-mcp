# maccmsv10-api-mcp 服务

maccmsv10-api-mcp 服务是一个 FastAPI 应用，旨在为视频点播（VOD）内容提供可靠的播放源。它通过检查多个视频源的健康状况并选择最佳可用源来实现此目的。

## 功能

*   **源健康检查**: 可检查所有视频源的可用性。
*   **动态源选择**: 为给定的 `vod_id` 从源列表中选择一个可用的播放源。
*   **代理或重定向**: 根据配置，可以将视频流代理到客户端或将客户端重定向到视频源。
*   **API 端点**: 提供用于获取播放链接和监控源状态的 API。

## 环境设置

1.  **克隆代码库**:
    ```bash
    # 下载代码
    git clone https://github.com/wbsu2003/maccmsv10-api-mcp.git
    
    # 进入目录  
    cd maccmsv10-api-mcp
    ```

2.  **创建并激活虚拟环境**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # 在 Windows 上使用 `venv\Scripts\activate`
    ```

3.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **配置环境变量**:
    创建一个 `.env` 文件，并填充以下变量:
    ```
    MCP_BASE_URL=http://127.0.0.1:8000
    ```

## 运行服务

使用 Uvicorn 运行 FastAPI 应用:
```bash
uvicorn main:app --reload
```
服务将在 `http://127.0.0.1:8000` 上可用。

## 配置

服务的行为可以通过 `config.json` 文件进行配置。

```json
{
  "sources": {
    "heimuer": {
      "api": "https://json.heimuer.xyz/api.php/provide/vod",
      "name": "黑木耳",
      "detail": "https://heimuer.tv",
    }
  }
}
```

## 使用Docker运行

### 构建镜像

在项目根目录下执行以下命令构建Docker镜像：

```bash
docker build -t maccmsv10-api-mcp .
```

### 运行容器

构建完成后，执行以下命令运行容器：

```bash
# 运行容器
docker run -d \
  --name maccmsv10-api-mcp \
  -p 8000:8000 \
  -e MCP_BASE_URL=http://127.0.0.1:8000 \
  -v $(pwd)/config.json:/app/config.json:ro \
  maccmsv10-api-mcp
```

### 访问服务

服务启动后，可以通过浏览器访问以下地址：

- Web界面: http://localhost:8000
- API文档: http://localhost:8000/docs

## API端点

- `GET /health` - 健康检查接口
- `POST /tools/search_movie` - 搜索影视资源接口
- `POST /tools/get_playback_info` - 获取播放 URL 接口
- `GET /proxy/` - 用于中继 M3U8 的代理服务器
- `GET /debug/source` - 测试并报告所有在配置文件中定义的视频源的健康状况


## 架构

### v1 架构 ❌
```
客户端 → mcp_service → 超长URL → 浏览器崩溃
```

### v2 架构 ✅
```
客户端 → mcp_service → 简短URL → 浏览器加载页面
                                ↓
                        JavaScript → API请求 → JSON数据 → 渲染界面
```

## ⚠️ 免责声明

本项目仅作为视频搜索工具，不存储、上传或分发任何视频内容。所有视频均来自第三方 API 接口提供的搜索结果。如有侵权内容，请联系相应的内容提供方。

本项目开发者不对使用本项目产生的任何后果负责。使用本项目时，您必须遵守当地的法律法规。

## 🥇 感谢支持

本项目播放器基于 `LibreTV` 播放器修改 
