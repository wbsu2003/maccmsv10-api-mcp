/**
 * 剧集处理器 - 处理剧集数据的存储和URL重定向
 * 用于解决URL长度限制问题
 */

class EpisodeHandler {
    constructor() {
        this.STORAGE_KEY = 'currentEpisodes';
        this.MAX_URL_LENGTH = 2000; // 浏览器URL长度限制
    }

    /**
     * 检查URL是否过长
     * @param {string} url - 要检查的URL
     * @returns {boolean} - 是否超过长度限制
     */
    isUrlTooLong(url) {
        return url.length > this.MAX_URL_LENGTH;
    }

    /**
     * 将剧集数据存储到localStorage并重定向到简化URL
     * @param {Array} episodeUrls - 剧集URL数组
     * @param {string} baseUrl - 基础播放器URL（不包含episodes参数）
     */
    storeEpisodesAndRedirect(episodeUrls, baseUrl) {
        try {
            // 将剧集数据存储到localStorage
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(episodeUrls));
            
            console.log(`已将 ${episodeUrls.length} 个剧集URL存储到localStorage`);
            console.log('重定向到简化URL:', baseUrl);
            
            // 重定向到简化的URL
            window.location.href = baseUrl;
            
        } catch (error) {
            console.error('存储剧集数据失败:', error);
            // 如果存储失败，仍然尝试重定向（播放器会处理缺少剧集数据的情况）
            window.location.href = baseUrl;
        }
    }

    /**
     * 从localStorage获取剧集数据
     * @returns {Array|null} - 剧集URL数组或null
     */
    getStoredEpisodes() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            return stored ? JSON.parse(stored) : null;
        } catch (error) {
            console.error('读取存储的剧集数据失败:', error);
            return null;
        }
    }

    /**
     * 清除存储的剧集数据
     */
    clearStoredEpisodes() {
        try {
            localStorage.removeItem(this.STORAGE_KEY);
            console.log('已清除存储的剧集数据');
        } catch (error) {
            console.error('清除剧集数据失败:', error);
        }
    }

    /**
     * 处理MCP服务返回的播放信息
     * 如果包含episode_urls且URL可能过长，则使用localStorage方案
     * @param {Object} playbackInfo - MCP服务返回的播放信息
     */
    handlePlaybackInfo(playbackInfo) {
        const { web_player_url, episode_urls } = playbackInfo;
        
        // 如果没有剧集数据，直接跳转
        if (!episode_urls || episode_urls.length === 0) {
            window.location.href = web_player_url;
            return;
        }

        // 构建包含episodes参数的完整URL来检查长度
        const episodesJson = JSON.stringify(episode_urls);
        const encodedEpisodes = encodeURIComponent(episodesJson);
        const fullUrl = `${web_player_url}&episodes=${encodedEpisodes}`;

        // 如果URL过长，使用localStorage方案
        if (this.isUrlTooLong(fullUrl)) {
            console.log('URL过长，使用localStorage方案');
            this.storeEpisodesAndRedirect(episode_urls, web_player_url);
        } else {
            console.log('URL长度正常，直接跳转');
            window.location.href = fullUrl;
        }
    }

    /**
     * 创建一个中转页面，显示加载状态并处理重定向
     * @param {Object} playbackInfo - MCP服务返回的播放信息
     */
    createTransitionPage(playbackInfo) {
        // 清空当前页面内容
        document.body.innerHTML = `
            <div style="
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-align: center;
            ">
                <div style="
                    background: rgba(255, 255, 255, 0.1);
                    padding: 40px;
                    border-radius: 15px;
                    backdrop-filter: blur(10px);
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
                ">
                    <div style="
                        width: 50px;
                        height: 50px;
                        border: 4px solid rgba(255, 255, 255, 0.3);
                        border-top: 4px solid white;
                        border-radius: 50%;
                        animation: spin 1s linear infinite;
                        margin: 0 auto 20px;
                    "></div>
                    <h2 style="margin: 0 0 10px 0; font-size: 24px;">正在准备播放器...</h2>
                    <p style="margin: 0; opacity: 0.8; font-size: 16px;">请稍候，正在加载视频资源</p>
                </div>
            </div>
            <style>
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        `;

        // 短暂延迟后处理重定向，让用户看到加载状态
        setTimeout(() => {
            this.handlePlaybackInfo(playbackInfo);
        }, 1000);
    }
}

// 创建全局实例
window.episodeHandler = new EpisodeHandler();

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = EpisodeHandler;
}