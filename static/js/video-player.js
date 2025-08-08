class VideoPlayer {
    constructor() {
        this.videoId = null;
        this.source = null;
        this.movieTitle = null;
        this.episodes = [];
        this.currentIndex = 0;
        
        this.init();
    }
    
    async init() {
        try {
            // 从URL获取参数
            this.parseUrlParams();
            
            // 如果有分集数据则加载分集数据
            await this.loadEpisodesData();
        } catch (error) {
            console.error('VideoPlayer初始化失败:', error);
            this.showError(`初始化失败: ${error.message}`);
        }
    }
    
    parseUrlParams() {
        const urlParams = new URLSearchParams(window.location.search);
        this.videoId = urlParams.get('videoId');
        this.source = urlParams.get('source');
        this.movieTitle = urlParams.get('movieTitle') || '未知视频';
        this.currentIndex = parseInt(urlParams.get('index') || '0', 10);
        this.originalId = urlParams.get('originalId'); // 新增原始ID参数
        
        console.log('URL参数:', { 
            videoId: this.videoId, 
            source: this.source, 
            movieTitle: this.movieTitle,
            index: this.currentIndex,
            originalId: this.originalId
        });
        
        // 设置页面标题
        if (this.movieTitle && this.movieTitle !== '未知视频') {
            document.title = `${this.movieTitle} - LibreTV`;
        }
    }
    
    async loadEpisodesData() {
        if (!this.videoId || !this.source) {
            console.warn('缺少videoId或source参数，跳过分集数据加载');
            return;
        }
        
        try {
            // 先尝试从缓存获取
            const cachedData = this.getCachedData();
            if (cachedData) {
                console.log('VideoPlayer: 使用缓存数据');
                this.handleEpisodesData(cachedData);
                return;
            }
            
            // 发起API请求
            console.log(`VideoPlayer: 正在请求分集数据...`);
            
            // 构建API请求URL，包含originalId参数（如果有的话）
            let apiUrl = `/api/episodes/${this.videoId}?source=${encodeURIComponent(this.source)}&movie_title=${encodeURIComponent(this.movieTitle)}`;
            if (this.originalId) {
                apiUrl += `&originalId=${encodeURIComponent(this.originalId)}`;
            }
            
            const response = await fetch(apiUrl);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            if (!data.success) {
                throw new Error(data.error || '获取分集数据失败');
            }
            
            console.log(`VideoPlayer: 成功获取 ${data.episodes.length} 个分集`);
            
            // 缓存数据
            this.cacheData(data);
            
            // 处理分集数据
            this.handleEpisodesData(data);
            
        } catch (error) {
            console.error('VideoPlayer: 加载分集数据失败:', error);
            // 不显示错误，因为可能是单集视频
            console.warn('VideoPlayer: 将作为单集视频处理');
        }
    }
    
    handleEpisodesData(data) {
        this.episodes = data.episodes || [];
        
        if (this.episodes.length > 0) {
            console.log(`VideoPlayer: 处理 ${this.episodes.length} 个分集`);
            
            // 转换数据格式以兼容现有的播放器
            const convertedEpisodes = this.episodes.map((episode, index) => ({
                name: episode.title || `第${index + 1}集`,
                url: episode.url
            }));
            
            // 更新现有播放器的分集列表
            if (typeof window.updateEpisodesFromAPI === 'function') {
                window.updateEpisodesFromAPI(convertedEpisodes, this.currentIndex);
            }
            
            // 触发自定义事件，通知其他模块分集数据已加载
            const event = new CustomEvent('episodesLoaded', {
                detail: {
                    episodes: convertedEpisodes, // 使用转换后的格式保持一致性
                    currentIndex: this.currentIndex,
                    movieTitle: this.movieTitle,
                    source: this.source
                }
            });
            document.dispatchEvent(event);
        }
    }
    
    getCachedData() {
        try {
            const cacheKey = `episodes_${this.videoId}_${this.source}`;
            const cached = localStorage.getItem(cacheKey);
            if (cached) {
                const data = JSON.parse(cached);
                // 检查缓存是否过期（1小时）
                const now = Date.now();
                if (now - data.timestamp < 3600000) {
                    return data;
                }
            }
        } catch (error) {
            console.warn('VideoPlayer: 读取缓存失败:', error);
        }
        return null;
    }
    
    cacheData(data) {
        try {
            const cacheKey = `episodes_${this.videoId}_${this.source}`;
            data.timestamp = Date.now();
            localStorage.setItem(cacheKey, JSON.stringify(data));
            console.log('VideoPlayer: 数据已缓存');
        } catch (error) {
            console.warn('VideoPlayer: 缓存数据失败:', error);
        }
    }
    
    showError(message) {
        console.error('VideoPlayer: 显示错误:', message);
        // 不直接修改UI，让现有的错误处理机制处理
    }
    
    // 公共方法：获取当前分集信息
    getCurrentEpisode() {
        if (this.episodes.length > 0 && this.currentIndex < this.episodes.length) {
            return this.episodes[this.currentIndex];
        }
        return null;
    }
    
    // 公共方法：获取所有分集
    getAllEpisodes() {
        return this.episodes;
    }
    
    // 公共方法：更新当前播放索引
    setCurrentIndex(index) {
        if (index >= 0 && index < this.episodes.length) {
            this.currentIndex = index;
            
            // 更新URL参数
            const url = new URL(window.location);
            url.searchParams.set('index', index.toString());
            window.history.replaceState({}, '', url);
            
            return true;
        }
        return false;
    }
}

// 初始化新的VideoPlayer
function initializeNewVideoPlayer() {
    // 避免重复初始化
    if (window.newVideoPlayer) {
        return window.newVideoPlayer;
    }
    
    console.log('VideoPlayer: 初始化新的视频播放器');
    window.newVideoPlayer = new VideoPlayer();
    return window.newVideoPlayer;
}

// 兼容现有代码的函数
window.updateEpisodesFromAPI = function(episodes, currentIndex) {
    console.log('VideoPlayer: 更新现有播放器的分集列表', episodes.length, '个分集');
    
    // 更新全局变量（如果存在）
    if (typeof window.episodes !== 'undefined') {
        window.episodes = episodes;
    }
    
    // 更新当前播放索引
    if (typeof window.currentEpisodeIndex !== 'undefined') {
        window.currentEpisodeIndex = currentIndex || 0;
    }
    
    // 触发分集列表更新
    if (typeof refreshEpisodeList === 'function') {
        refreshEpisodeList();
    }
    
    // 更新分集信息显示
    if (typeof updateEpisodeInfo === 'function') {
        updateEpisodeInfo();
    }
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 延迟初始化，确保其他脚本已加载
    setTimeout(() => {
        initializeNewVideoPlayer();
    }, 100);
});

// 全局错误处理
window.addEventListener('error', (event) => {
    if (event.filename && event.filename.includes('video-player.js')) {
        console.error('VideoPlayer全局错误:', event.error);
    }
});

window.addEventListener('unhandledrejection', (event) => {
    if (event.reason && event.reason.toString().includes('VideoPlayer')) {
        console.error('VideoPlayer未处理的Promise拒绝:', event.reason);
    }
});