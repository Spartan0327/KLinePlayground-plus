// 全局变量
let currentUser = null;
let chart = null;
let volumeChart = null;
let indicatorChart = null;
let candlestickSeries = null;
let volumeSeries = null;
let maSeries = {}; // 存储移动平均线系列
let indicatorSeries = null;
let tradeMarkerSeries = null;
let tradeMarkersPlugin = null;
let cooldownMarkersData = [];
let signalMarkersData = [];
let positionGuideLines = { cost: null, stop: null, take: null };
let isPlaying = false;
let playbackInterval = null;
let currentTraining = null;
let currentIndicatorType = 'MACD';
let currentIndicatorSeries = [];
let bollSeries = {}; // 用于存储BOLL指标线
let autoSyncInterval = null;
let lastKnownBarId = null;
let lastKnownTradeCount = null;
let maPeriods = [5, 10, 20]; // 默认MA周期
let isShiftClicked = false;
let isShiftKeyPressed = false;
let currentTheme = localStorage.getItem('uiTheme') || 'light';
let currentPeriod = 'daily';
let availableDataSources = [];
let latestRenderedKlineData = [];
let trainingSetupReturnScreen = 'main';
let currentReportData = null;
let isViewOnlyMode = false;

const THEME_PALETTES = {
    light: {
        chartBg: '#fdfefe',
        text: '#172033',
        grid: 'rgba(23, 32, 51, 0.08)',
        border: 'rgba(23, 32, 51, 0.12)',
        overlay: 'rgba(255, 255, 255, 0.84)',
        positive: '#e25555',
        negative: '#0f8a52',
        neutral: '#5d6b82',
        chip: 'linear-gradient(90deg, transparent, rgba(15, 111, 255, 0.28))',
    },
    dark: {
        chartBg: '#121d31',
        text: '#ecf2ff',
        grid: 'rgba(255, 255, 255, 0.08)',
        border: 'rgba(255, 255, 255, 0.12)',
        overlay: 'rgba(9, 17, 31, 0.84)',
        positive: '#ff7a74',
        negative: '#4fd096',
        neutral: '#9daccc',
        chip: 'linear-gradient(90deg, transparent, rgba(103, 165, 255, 0.28))',
    }
};

function getThemePalette() {
    return THEME_PALETTES[currentTheme] || THEME_PALETTES.light;
}

function updateThemeButton() {
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
        themeBtn.textContent = currentTheme === 'dark' ? '浅色主题' : '深色主题';
    }
    const themeSelect = document.getElementById('theme-select');
    if (themeSelect) {
        themeSelect.value = currentTheme;
    }
}

function updatePeriodBadge(period) {
    currentPeriod = period || 'daily';
    const badge = document.getElementById('current-period');
    if (badge) {
        badge.textContent = currentPeriod === 'weekly' ? '周K' : '日K';
    }
    document.querySelectorAll('.view-period-btn').forEach((button) => {
        button.classList.toggle('active', button.dataset.period === currentPeriod);
    });
}

async function persistUserSettings(partialSettings) {
    if (!currentUser) return;
    try {
        await fetch(`${API_BASE}/users/${currentUser}/settings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(partialSettings)
        });
    } catch (error) {
        console.error('保存用户设置失败:', error);
    }
}

function applyTheme(theme, persist = true, syncUser = false) {
    currentTheme = theme === 'dark' ? 'dark' : 'light';
    document.body.dataset.theme = currentTheme;
    if (persist) {
        localStorage.setItem('uiTheme', currentTheme);
    }
    if (syncUser) {
        persistUserSettings({ theme: currentTheme });
    }
    updateThemeButton();
    updatePriceMode();
    applyChartTheme();
}

function getViewPeriodQuery() {
    return `view_period=${currentPeriod}`;
}

function showLoading(title = '正在加载', detail = '') {
    const overlay = document.getElementById('loading-overlay');
    if (!overlay) return;
    const titleEl = document.getElementById('loading-title');
    const detailEl = document.getElementById('loading-detail');
    if (titleEl) titleEl.textContent = title;
    if (detailEl) detailEl.textContent = detail || '请稍候...';
    overlay.classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loading-overlay')?.classList.add('hidden');
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function applyChartTheme() {
    const palette = getThemePalette();
    const infoDisplay = document.getElementById('chart-info-display');
    if (infoDisplay) {
        infoDisplay.style.background = palette.overlay;
        infoDisplay.style.color = palette.text;
        infoDisplay.style.borderColor = palette.border;
    }
    const indicatorInfoDisplay = document.getElementById('indicator-info-display');
    if (indicatorInfoDisplay) {
        indicatorInfoDisplay.style.background = palette.overlay;
        indicatorInfoDisplay.style.color = palette.text;
        indicatorInfoDisplay.style.borderColor = palette.border;
    }

    document.querySelectorAll('.chip-bar').forEach((bar) => {
        bar.style.background = palette.chip;
    });

    if (!chart) return;

    chart.applyOptions({
        layout: {
            background: { type: 'solid', color: palette.chartBg },
            textColor: palette.text,
        },
        grid: {
            vertLines: { color: palette.grid },
            horzLines: { color: palette.grid },
        },
        rightPriceScale: { borderColor: palette.border },
        timeScale: { borderColor: palette.border },
    });

    if (volumeChart) {
        volumeChart.applyOptions({
            layout: {
                background: { type: 'solid', color: palette.chartBg },
                textColor: palette.text,
            },
            grid: {
                vertLines: { color: palette.grid },
                horzLines: { color: palette.grid },
            },
            rightPriceScale: { borderColor: palette.border },
            timeScale: { borderColor: palette.border },
        });
    }

    if (indicatorChart) {
        indicatorChart.applyOptions({
            layout: {
                background: { type: 'solid', color: palette.chartBg },
                textColor: palette.text,
            },
            grid: {
                vertLines: { color: palette.grid },
                horzLines: { color: palette.grid },
            },
            rightPriceScale: { borderColor: palette.border },
            timeScale: { borderColor: palette.border },
        });
    }

    if (candlestickSeries) {
        candlestickSeries.applyOptions({
            downColor: palette.negative,
            borderUpColor: palette.positive,
            borderDownColor: palette.negative,
            wickUpColor: palette.positive,
            wickDownColor: palette.negative,
        });
    }
}

function updatePriceMode() {
    const isModeOpen = isShiftClicked || isShiftKeyPressed;
    const shiftBtn = document.getElementById('shift-toggle-btn');
    const buyBtn = document.getElementById('buy-btn');
    const sellBtn = document.getElementById('sell-btn');
    const palette = getThemePalette();
    
    if (!shiftBtn || !buyBtn || !sellBtn) return;
    
    if (isModeOpen) {
        shiftBtn.style.backgroundColor = palette.positive;
        shiftBtn.style.color = 'white';
        shiftBtn.style.borderColor = 'transparent';
        shiftBtn.textContent = '⇧ 开盘价';
    } else {
        shiftBtn.style.backgroundColor = '';
        shiftBtn.style.color = '';
        shiftBtn.style.borderColor = '';
        shiftBtn.textContent = '⇧ 收盘价';
    }
}
const maColors = ['#1d2140', '#2816cf', '#ff8103', '#e02424', '#8b5cf6', '#059669']; // 6个预设颜色

// --- 筹码分布开始 ---
let chipDistributionData = null;

function scheduleChipDistributionRender() {
    if (typeof window === 'undefined') {
        renderChipDistribution();
        return;
    }

    window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
            renderChipDistribution();
        });
    });
}

function getChipPriceCoordinate(price, containerHeight) {
    if (!Number.isFinite(price) || !containerHeight) {
        return null;
    }

    const directCoordinate = candlestickSeries?.priceToCoordinate?.(price);
    if (Number.isFinite(directCoordinate)) {
        return directCoordinate;
    }

    if (!Array.isArray(latestRenderedKlineData) || latestRenderedKlineData.length === 0) {
        return null;
    }

    let minPrice = Number.POSITIVE_INFINITY;
    let maxPrice = Number.NEGATIVE_INFINITY;
    latestRenderedKlineData.forEach((bar) => {
        if (Number.isFinite(bar?.low)) minPrice = Math.min(minPrice, bar.low);
        if (Number.isFinite(bar?.high)) maxPrice = Math.max(maxPrice, bar.high);
    });

    if (!Number.isFinite(minPrice) || !Number.isFinite(maxPrice)) {
        return null;
    }

    if (maxPrice === minPrice) {
        return containerHeight / 2;
    }

    const clampedPrice = Math.min(maxPrice, Math.max(minPrice, price));
    return ((maxPrice - clampedPrice) / (maxPrice - minPrice)) * containerHeight;
}

async function updateChipDistribution() {
    const toggleCb = document.getElementById('toggle-chip-distribution');
    const profitRatioContainer = document.getElementById('profit-ratio-container');
    
    if (!toggleCb || !toggleCb.checked) {
        const container = getOrCreateVolumeProfileContainer();
        if (container) container.style.display = 'none';
        if (profitRatioContainer) {
            profitRatioContainer.classList.add('hidden');
            profitRatioContainer.style.display = 'none';
        }
        return;
    }

    if (profitRatioContainer) {
        profitRatioContainer.classList.remove('hidden');
        profitRatioContainer.style.display = 'flex';
    }

    if (!currentTraining || !currentTraining.id) return;

    try {
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/chip_distribution?bins=80&${getViewPeriodQuery()}`);
        if (response.ok) {
            chipDistributionData = await response.json();
            scheduleChipDistributionRender();
        } else {
            chipDistributionData = null;
            const container = getOrCreateVolumeProfileContainer();
            if (container) container.innerHTML = '';
        }
    } catch (e) {
        console.error("Failed to load chip distribution", e);
    }
}

function renderChipDistribution() {
    try {
        const toggleCb = document.getElementById('toggle-chip-distribution');
        if (!toggleCb || !toggleCb.checked) {
            return;
        }
        const container = getOrCreateVolumeProfileContainer();
        container.style.display = 'block';
        
        if (!chipDistributionData || !chipDistributionData.data || !candlestickSeries || !chart) {
            container.innerHTML = '';
            return;
        }

        const data = chipDistributionData.data;
        if (data.length === 0) {
            container.innerHTML = '';
            return;
        }

        const currentData = latestRenderedKlineData;
        let currentPrice = null;
        if (currentData.length > 0) {
            currentPrice = currentData[currentData.length - 1].close;
            let profitVolume = 0;
            let totalVolume = 0;
            data.forEach(bin => {
                totalVolume += bin.volume;
                if (bin.price <= currentPrice) profitVolume += bin.volume;
            });
            const profitRatioEl = document.getElementById('profit-ratio');
            if (profitRatioEl) {
                const palette = getThemePalette();
                const profitRatio = totalVolume > 0 ? ((profitVolume / totalVolume) * 100).toFixed(2) : 0;
                profitRatioEl.textContent = `${profitRatio}%`;
                profitRatioEl.style.color = profitRatio > 50 ? palette.positive : palette.negative;
            }
        }

        const maxVolume = Math.max(...data.map(d => d.volume), 0);
        if (!maxVolume) {
            container.innerHTML = '';
            return;
        }

        const containerHeight = container.clientHeight || document.getElementById('chart')?.clientHeight || 0;
        const fragment = document.createDocumentFragment();
        let renderedCount = 0;

        if (Number.isFinite(currentPrice)) {
            const currentLineY = getChipPriceCoordinate(currentPrice, containerHeight);
            if (currentLineY !== null) {
                const currentLine = document.createElement('div');
                currentLine.className = 'chip-current-line';
                currentLine.style.top = `${currentLineY}px`;
                fragment.appendChild(currentLine);
            }
        }
        
        data.forEach((bin, i) => {
            const y = getChipPriceCoordinate(bin.price, containerHeight);
            if (y === null || y < -50 || y > containerHeight + 50) {
                return; 
            }
            
            let nextY = null;
            if (i < data.length - 1) {
                nextY = getChipPriceCoordinate(data[i + 1].price, containerHeight);
            } else if (i > 0) {
                const prevY = getChipPriceCoordinate(data[i - 1].price, containerHeight);
                if (y !== null && prevY !== null) {
                    nextY = y - (prevY - y);
                }
            }
            
            let barHeight = 2;
            if (y !== null && nextY !== null) {
                barHeight = Math.abs(y - nextY);
            }
            if (barHeight < 1) barHeight = 1;
            
            const widthPercent = (bin.volume / maxVolume) * 100;
            
            const barDiv = document.createElement('div');
            const isProfitChip = Number.isFinite(currentPrice) ? bin.price <= currentPrice : true;
            barDiv.className = `chip-bar ${isProfitChip ? 'chip-profit' : 'chip-loss'}`;
            barDiv.style.top = `${y - barHeight/2}px`;
            barDiv.style.width = `${Math.max(widthPercent, 2)}%`;
            barDiv.style.height = `${barHeight * 0.9}px`;
            
            fragment.appendChild(barDiv);
            renderedCount += 1;
        });
        
        container.innerHTML = '';
        container.appendChild(fragment);
        container.dataset.renderedCount = String(renderedCount);
    } catch (error) {
        console.error('渲染筹码分布失败:', error);
    }
}

function getOrCreateVolumeProfileContainer() {
    let container = document.getElementById('volume-profile-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'volume-profile-container';
        const chartDiv = document.getElementById('chart');
        if (chartDiv) {
             if (window.getComputedStyle(chartDiv).position === 'static') {
                 chartDiv.style.position = 'relative';
             }
             chartDiv.appendChild(container);
        }
    }
    return container;
}

function ensureBackToReportButton() {
    let backBtn = document.getElementById('back-to-report-btn');
    if (backBtn) {
        return backBtn;
    }

    const controlsSection = document.querySelector('.training-controls');
    if (!controlsSection) {
        return null;
    }

    backBtn = document.createElement('button');
    backBtn.id = 'back-to-report-btn';
    backBtn.className = 'btn btn-primary hidden';
    backBtn.style.width = '100%';
    backBtn.style.marginTop = '10px';
    backBtn.textContent = '返回复盘报告';
    backBtn.onclick = () => {
        setTrainingViewOnlyMode(false, { showBackToReport: false });
        document.getElementById('training-interface').classList.add('hidden');
        document.getElementById('report-interface').classList.remove('hidden');
        document.getElementById('main-app').classList.remove('training-mode');
        toggleToolbarForTraining(false);
    };
    controlsSection.appendChild(backBtn);
    return backBtn;
}

function setTrainingViewOnlyMode(viewOnly, options = {}) {
    const { showBackToReport = false } = options;
    const disabled = !!viewOnly;
    const opacity = disabled ? '0.5' : '1';
    const cursor = disabled ? 'not-allowed' : 'pointer';

    document.querySelectorAll('.trade-controls button').forEach((btn) => {
        btn.disabled = disabled;
        btn.style.opacity = opacity;
        btn.style.cursor = cursor;
    });

    ['buy-percent', 'sell-percent'].forEach((id) => {
        const slider = document.getElementById(id);
        if (slider) slider.disabled = disabled;
    });

    const playbackSpeedSelect = document.getElementById('playback-speed');
    if (playbackSpeedSelect) {
        playbackSpeedSelect.disabled = disabled;
        playbackSpeedSelect.style.opacity = opacity;
    }

    ['end-training-btn', 'reset-training-btn', 'next-bar-btn', 'play-pause-btn'].forEach((id) => {
        const element = document.getElementById(id);
        if (!element) return;
        element.disabled = disabled;
        element.style.opacity = opacity;
        element.style.cursor = cursor;
    });

    const backBtn = ensureBackToReportButton();
    if (backBtn) {
        backBtn.classList.toggle('hidden', !showBackToReport);
    }

    isViewOnlyMode = disabled;
}
// --- 筹码分布结束 ---

// API 基础URL - 改为相对路径适配动态端口
const API_BASE = '/api';

// 初始化应用
document.addEventListener('DOMContentLoaded', function () {
    initializeApp();
    setupEventListeners();
    setupKeyboardShortcuts();
});

// 初始化应用
async function initializeApp() {
    try {
        applyTheme(currentTheme, false, false);
        updatePeriodBadge('daily');
        await loadDataSources();
        // 检查是否有保存的用户：先取真实用户列表，避免本地残留指向已删除用户
        let knownUsers = [];
        let usersLoaded = false;
        try {
            const res = await fetch(`${API_BASE}/users`);
            const list = await res.json();
            if (Array.isArray(list)) {
                knownUsers = list;
                usersLoaded = true;
            }
        } catch (error) {
            console.error('加载用户列表失败:', error);
        }
        let savedUser = localStorage.getItem('currentUser');
        if (savedUser && usersLoaded && !knownUsers.includes(savedUser)) {
            localStorage.removeItem('currentUser');
            savedUser = null;
        }
        if (savedUser) {
            currentUser = savedUser;
            document.getElementById('current-username').textContent = savedUser;
            showMainApp();
            await loadUserStatistics();
            await loadTrainingHistory();
        } else {
            showUserSelection();
        }

        // 加载用户列表
        await loadUsers();

        // 如果有保存的用户，初始化 AI API 状态
        if (currentUser) {
            fetch(`${API_BASE}/users/${currentUser}/settings`)
                .then(res => res.json())
                .then(settings => {
                    updateAIApiStatus(!!settings.enable_ai_api, currentUser);
                    if (settings.theme) {
                        applyTheme(settings.theme, true, false);
                    }
                }).catch(e => console.error(e));
        }
    } catch (error) {
        console.error('初始化失败:', error);
        showUserSelection();
    }
}

async function updateAIApiStatus(enabled, username) {
    try {
        await fetch(`${API_BASE}/system/api_info`, {
            method: enabled ? 'POST' : 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user: username })
        });
    } catch (e) {
        console.error('Failed to update AI API status:', e);
    }
}

async function loadDataSources() {
    try {
        const response = await fetch(`${API_BASE}/data/sources`);
        if (!response.ok) return;
        const payload = await response.json();
        availableDataSources = payload.sources || [];
        hydrateDataSourceSelect('data-source', true);
        hydrateDataSourceSelect('sync-source', false);
    } catch (error) {
        console.error('加载数据源列表失败:', error);
    }
}

function hydrateDataSourceSelect(selectId, includeOffline = false) {
    const select = document.getElementById(selectId);
    if (!select) return;

    const currentValue = select.value;
    const options = availableDataSources.filter((item) => includeOffline || item.value !== 'offline');
    if (options.length === 0) return;

    select.innerHTML = '';
    options.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.value;
        const disabledText = item.available ? '' : '（未安装）';
        option.textContent = `${item.label}${disabledText}`;
        option.disabled = !item.available;
        select.appendChild(option);
    });

    const hasCurrent = options.some((item) => item.value === currentValue && item.available);
    select.value = hasCurrent ? currentValue : options.find((item) => item.available)?.value || options[0].value;
}

function renderChartLegend() {
    const container = document.getElementById('chart-legend');
    if (!container) return;
    const items = [];
    maPeriods.forEach(p => {
        if (maSeries[p]) {
            items.push({ label: `MA${p}`, color: maSeries[p].options().color });
        }
    });
    if (bollSeries && bollSeries.upper && bollSeries.middle && bollSeries.lower) {
        items.push({ label: 'UP', color: bollSeries.upper.options().color });
        items.push({ label: 'MID', color: bollSeries.middle.options().color });
        items.push({ label: 'LOW', color: bollSeries.lower.options().color });
    }
    container.innerHTML = '';
    items.forEach(it => {
        const el = document.createElement('span');
        el.className = 'legend-chip';
        el.style.backgroundColor = it.color || '#999';
        el.textContent = it.label;
        container.appendChild(el);
    });
}

function renderIndicatorLegend() {
    const container = document.getElementById('indicator-legend');
    if (!container) return;
    container.innerHTML = '';
    const items = [];
    switch (currentIndicatorType) {
        case 'MACD':
            if (currentIndicatorSeries[0]) items.push({ label: 'DIF', color: currentIndicatorSeries[0].options().color });
            if (currentIndicatorSeries[1]) items.push({ label: 'DEA', color: currentIndicatorSeries[1].options().color });
            items.push({ label: 'MACD', color: '#999' });
            break;
        case 'KDJ':
            if (currentIndicatorSeries[0]) items.push({ label: 'K', color: currentIndicatorSeries[0].options().color });
            if (currentIndicatorSeries[1]) items.push({ label: 'D', color: currentIndicatorSeries[1].options().color });
            if (currentIndicatorSeries[2]) items.push({ label: 'J', color: currentIndicatorSeries[2].options().color });
            break;
        case 'RSI':
            currentIndicatorSeries.forEach(series => {
                items.push({ label: series.rsiTitle || series.options().title || 'RSI', color: series.options().color });
            });
            break;
        case 'BOLL':
            items.push({ label: 'UP', color: '#ff6b6b' });
            items.push({ label: 'MID', color: '#4ecdc4' });
            items.push({ label: 'LOW', color: '#45b7d1' });
            break;
    }
    items.forEach(it => {
        const el = document.createElement('span');
        el.className = 'legend-chip';
        el.style.backgroundColor = it.color || '#999';
        el.textContent = it.label;
        container.appendChild(el);
    });
}
// 设置事件监听器
function setupEventListeners() {
    // 用户选择相关
    document.getElementById('create-user-btn').addEventListener('click', createUser);
    document.getElementById('switch-user-btn').addEventListener('click', showUserSelection);

    // 训练设置相关
    document.getElementById('new-training-btn').addEventListener('click', showTrainingSetup);
    document.getElementById('cancel-setup-btn').addEventListener('click', hideTrainingSetup);
    document.getElementById('start-training-btn').addEventListener('click', startTraining);

    // 设置按钮
    document.getElementById('settings-btn')?.addEventListener('click', showSettings);
    document.getElementById('save-settings-btn')?.addEventListener('click', saveSettings);
    document.getElementById('reset-ai-prompt-btn')?.addEventListener('click', () => {
        const box = document.getElementById('ai-review-prompt');
        if (box) {
            box.value = '';
            box.placeholder = '留空使用内置模板；已清空，点「保存」生效';
        }
    });
    document.getElementById('fill-default-ai-prompt-btn')?.addEventListener('click', () => {
        const box = document.getElementById('ai-review-prompt');
        if (box) box.value = defaultAiReviewPrompt || '';
    });
    document.getElementById('ai-config-test-btn')?.addEventListener('click', testAIConfig);
    document.getElementById('ai-config-clear-btn')?.addEventListener('click', clearAIConfig);
    document.getElementById('cancel-settings-btn')?.addEventListener('click', hideSettings);
    document.getElementById('theme-toggle-btn')?.addEventListener('click', () => {
        applyTheme(currentTheme === 'dark' ? 'light' : 'dark', true, true);
    });
    document.getElementById('data-sync-btn')?.addEventListener('click', showDataSyncModal);
    document.getElementById('confirm-sync-btn')?.addEventListener('click', syncOfflineData);
    document.getElementById('cancel-sync-btn')?.addEventListener('click', hideDataSyncModal);
    document.getElementById('sync-scope')?.addEventListener('change', updateSyncScopeUI);
    document.querySelectorAll('.view-period-btn').forEach((button) => {
        button.addEventListener('click', () => {
            switchViewPeriod(button.dataset.period || 'daily');
        });
    });

    // 标签页切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            switchTab(this.dataset.tab);
        });
    });

    // 回放控制
    document.getElementById('play-pause-btn').addEventListener('click', togglePlayback);
    document.getElementById('next-bar-btn').addEventListener('click', nextBar);
    document.getElementById('playback-speed').addEventListener('change', updatePlaybackSpeed);

    // 复权设置
    document.querySelectorAll('input[name="adjustment"]').forEach(radio => {
        radio.addEventListener('change', updateAdjustment);
    });

    // 交易操作
    document.getElementById('shift-toggle-btn')?.addEventListener('click', () => {
        isShiftClicked = !isShiftClicked;
        updatePriceMode();
    });

    document.getElementById('buy-btn')?.addEventListener('click', () => {
        executeBuy((isShiftClicked || isShiftKeyPressed) ? 'open' : 'close');
    });

    document.getElementById('sell-btn')?.addEventListener('click', () => {
        executeSell((isShiftClicked || isShiftKeyPressed) ? 'open' : 'close');
    });

    // 买卖滑块与百分比显示联动
    ['buy', 'sell'].forEach((side) => {
        const slider = document.getElementById(`${side}-percent`);
        if (!slider) return;
        slider.addEventListener('input', () => {
            limitTradePercent();
            updateTradePercentHint(side);
        });
        updateTradePercentHint(side);
    });

    // 训练控制
    document.getElementById('end-training-btn').addEventListener('click', endTraining);
    document.getElementById('reset-training-btn').addEventListener('click', resetTraining);

    // 技术指标选择
    document.getElementById('indicator-select')?.addEventListener('change', changeIndicator);

    // 筹码分布切换
    document.getElementById('toggle-chip-distribution')?.addEventListener('change', updateChipDistribution);

    // 复盘报告
    document.getElementById('view-full-chart-btn').addEventListener('click', viewFullChart);
    document.getElementById('export-report-md-btn').addEventListener('click', exportReportMarkdown);
    // AI 实时陪练
    document.getElementById('ai-coach-btn')?.addEventListener('click', () => toggleCoachPanel());
    document.getElementById('ai-coach-close-btn')?.addEventListener('click', () => toggleCoachPanel(false));
    document.getElementById('ai-coach-clear-btn')?.addEventListener('click', () => resetCoachChat(false));
    document.getElementById('ai-coach-send-btn')?.addEventListener('click', () => sendCoachQuestion(document.getElementById('ai-coach-input')?.value));
    document.getElementById('ai-coach-input')?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendCoachQuestion(event.target.value);
        }
    });
    document.querySelectorAll('.ai-coach-chip').forEach((chip) => {
        chip.addEventListener('click', () => sendCoachQuestion(chip.dataset.q));
    });
    const coachMessagesEl = document.getElementById('ai-coach-messages');
    coachMessagesEl?.addEventListener('mouseover', (event) => {
        const ref = event.target.closest('.coach-bar-ref');
        if (ref) highlightChartBar(Number(ref.dataset.bar));
    });
    coachMessagesEl?.addEventListener('mouseout', (event) => {
        const ref = event.target.closest('.coach-bar-ref');
        if (ref) clearBarHighlight();
    });
    coachMessagesEl?.addEventListener('click', (event) => {
        const ref = event.target.closest('.coach-bar-ref');
        if (!ref) return;
        event.preventDefault();
        highlightChartBar(Number(ref.dataset.bar), true);
    });
    document.getElementById('equity-scale-linear')?.addEventListener('click', () => applyEquityScaleMode(false));
    document.getElementById('equity-scale-log')?.addEventListener('click', () => applyEquityScaleMode(true));
    document.getElementById('ai-analyze-btn').addEventListener('click', requestAIAnalysis);
    // document.getElementById('new-training-from-report-btn').addEventListener('click', showTrainingSetup);
    document.getElementById('new-training-from-report-btn').addEventListener('click', () => {
        showTrainingSetup('report');
    });
    document.getElementById('return-main-menu-btn')?.addEventListener('click', resetToMainAppState);

    // 历史训练记录
    document.getElementById('history-refresh-btn')?.addEventListener('click', loadTrainingHistory);

    // 历史问题档案
    document.getElementById('review-history-btn')?.addEventListener('click', openReviewHistory);
    document.getElementById('rh-close-btn')?.addEventListener('click', () => {
        document.getElementById('review-history-modal')?.classList.add('hidden');
    });
    document.getElementById('rh-refresh-btn')?.addEventListener('click', loadReviewHistory);
    document.getElementById('rh-export-btn')?.addEventListener('click', exportReviewHistory);
    document.getElementById('rh-backup-btn')?.addEventListener('click', backupReviewHistory);
    document.getElementById('rh-restore-btn')?.addEventListener('click', restoreReviewHistory);
    document.getElementById('rh-save-btn')?.addEventListener('click', saveIssueDetail);
    document.getElementById('rh-detail-close')?.addEventListener('click', () => {
        document.getElementById('rh-detail')?.classList.add('hidden');
        rhState.currentId = null;
    });
    ['rh-search', 'rh-filter-category', 'rh-filter-ai', 'rh-filter-user', 'rh-filter-severity'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener(id === 'rh-search' ? 'input' : 'change', () => loadReviewHistory());
    });


    // 监听窗口大小变化
    window.addEventListener('resize', resizeCharts);

    // V2.2 曲线点评：卡片与全局关闭事件
    frBindCardEvents();
    frBindGlobalEvents();
}

// 设置键盘快捷键
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Shift') {
            isShiftKeyPressed = true;
            updatePriceMode();
        }
        // 只在训练界面激活快捷键
        if (document.getElementById('training-interface').classList.contains('hidden') || isViewOnlyMode) {
            return;
        }

        // 如果是由于按住按键导致的重复触发，则忽略大多数操作
        // 但允许数字键的重复输入（如果焦点在输入框内）
        if (event.repeat) {
            // 检查当前焦点是否在滑块，如果不在，则阻止所有重复事件
            const isTradeSliderFocused = ['buy-percent', 'sell-percent'].includes(document.activeElement?.id);
            if (!isTradeSliderFocused) {
                return;
            }
            // 如果焦点在滑块，且按下的不是方向键，也阻止
            if (!/^(Arrow)?(Left|Right|Up|Down)$/.test(event.key)) {
                return;
            }
        }

        const isTradeSliderFocused = ['buy-percent', 'sell-percent'].includes(document.activeElement?.id);

        switch (event.key.toLowerCase()) {
            case 'b':
            case '+':
            case '=':
                event.preventDefault(); // 阻止默认行为（如输入'b'或'+'）
                executeBuy((isShiftClicked || isShiftKeyPressed || event.shiftKey) ? 'open' : 'close');
                break;

            case 's':
            case '-':
            case '_':
                event.preventDefault(); // 阻止默认行为
                executeSell((isShiftClicked || isShiftKeyPressed || event.shiftKey) ? 'open' : 'close');
                break;

            case ' ':
            case 'enter':
                event.preventDefault();
                nextBar();
                break;

            case '0': case '1': case '2': case '3': case '4':
            case '5': case '6': case '7': case '8': case '9':
                // 数字键快速设定买入仓位：1→10% … 9→90%，0→100%
                if (!isTradeSliderFocused) {
                    event.preventDefault();
                    const buySlider = document.getElementById('buy-percent');
                    buySlider.value = event.key === '0' ? 100 : Number(event.key) * 10;
                    updateTradePercentHint('buy');
                }
                break;
        }

    });
    
    document.addEventListener('keyup', function (event) {
        if (event.key === 'Shift') {
            isShiftKeyPressed = false;
            updatePriceMode();
        }
    });
}

// 处理窗口大小变化
function resizeCharts() {
    if (chart && !document.getElementById('training-interface').classList.contains('hidden')) {
        const chartContainer = document.getElementById('chart');
        const volumeContainer = document.getElementById('volume-chart');
        const indicatorContainer = document.getElementById('indicator-canvas');

        chart.resize(chartContainer.clientWidth, chartContainer.clientHeight);
        volumeChart.resize(volumeContainer.clientWidth, volumeContainer.clientHeight);
        indicatorChart.resize(indicatorContainer.clientWidth, indicatorContainer.clientHeight);
        
        scheduleChipDistributionRender();
    }

    if (!document.getElementById('report-interface').classList.contains('hidden')) {
        const priceEl = document.getElementById('report-price-chart');
        const equityEl = document.getElementById('report-equity-chart');
        if (reportPriceChart && priceEl) {
            reportPriceChart.resize(priceEl.clientWidth, 280);
        }
        if (reportEquityChart && equityEl) {
            reportEquityChart.resize(equityEl.clientWidth, 180);
        }
        if (typeof frScheduleRender === 'function') frScheduleRender();
    }
}

// 用户管理
async function loadUsers() {
    try {
        const response = await fetch(`${API_BASE}/users`);
        const users = await response.json();

        const container = document.getElementById('existing-users');
        container.innerHTML = '';

        users.forEach(user => {
            const userItem = document.createElement('div');
            userItem.className = 'user-item';
            userItem.textContent = user;

            let pressTimer;

            // 鼠标长按事件
            userItem.addEventListener('mousedown', () => {
                pressTimer = window.setTimeout(() => {
                    // 长按触发删除确认
                    if (confirm(`确定要永久删除用户 "${user}" 吗？此操作不可恢复！`)) {
                        deleteUser(user);
                    }
                }, 1000); // 1秒后触发
            });

            userItem.addEventListener('mouseup', () => {
                clearTimeout(pressTimer);
            });

            userItem.addEventListener('mouseleave', () => {
                clearTimeout(pressTimer);
            });

            // 触摸长按事件 (移动端支持)
            userItem.addEventListener('touchstart', () => {
                pressTimer = window.setTimeout(() => {
                    if (confirm(`确定要永久删除用户 "${user}" 吗？此操作不可恢复！`)) {
                        deleteUser(user);
                    }
                }, 1000);
            });

            userItem.addEventListener('touchend', () => {
                clearTimeout(pressTimer);
            });

            userItem.addEventListener('touchmove', () => {
                clearTimeout(pressTimer);
            });

            // 单击事件
            userItem.addEventListener('click', (e) => {
                // 防止长按后还触发单击
                if (e.detail) { // e.detail > 0 for real clicks
                    selectUser(user);
                }
            });

            container.appendChild(userItem);
        });
    } catch (error) {
        console.error('加载用户列表失败:', error);
    }
}

async function createUser() {
    const username = document.getElementById('new-username').value.trim();
    if (!username) {
        alert('请输入用户名');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/users`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username })
        });

        if (response.ok) {
            await loadUsers();
            document.getElementById('new-username').value = '';
            selectUser(username);
        } else {
            const error = await response.json();
            alert(error.message || '创建用户失败');
        }
    } catch (error) {
        console.error('创建用户失败:', error);
        alert('创建用户失败');
    }
}

async function deleteUser(username) {
    try {
        const response = await fetch(`${API_BASE}/users/${username}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            alert(`用户 "${username}" 已成功删除。`);
            await loadUsers(); // 重新加载用户列表
        } else {
            const error = await response.json();
            alert(error.message || '删除用户失败');
        }
    } catch (error) {
        console.error('删除用户失败:', error);
        alert('删除用户时发生网络错误。');
    }
}

function selectUser(username) {
    currentUser = username;
    localStorage.setItem('currentUser', username);
    document.getElementById('current-username').textContent = username;
    showMainApp();
    loadUserStatistics();
    loadTrainingHistory();

    // 初始化 AI API 状态
    fetch(`${API_BASE}/users/${username}/settings`)
        .then(res => res.json())
        .then(settings => {
            updateAIApiStatus(!!settings.enable_ai_api, username);
            if (settings.theme) {
                applyTheme(settings.theme, true, false);
            }
        }).catch(e => console.error(e));
}

async function loadUserStatistics() {
    if (!currentUser) return;

    try {
        const response = await fetch(`${API_BASE}/users/${currentUser}/statistics`);
        const stats = await response.json();

        // 显示用户统计信息
        const statsElement = document.getElementById('user-stats');
        if (statsElement) {
            statsElement.innerHTML = `
                <div class="stat-item">
                    <span>历史总收益:</span>
                    <span class="${stats.avg_return >= 0 ? 'positive' : 'negative'}">${stats.avg_return.toFixed(2)}%</span>
                </div>
                <div class="stat-item">
                    <span>局胜率:</span>
                    <span class="${stats.avg_session_win_rate >= 50 ? 'positive' : 'negative'}">${stats.avg_session_win_rate.toFixed(2)}%</span>
                </div>
                <div class="stat-item">
                    <span>总训练次数:</span>
                    <span>${stats.total_sessions}</span>
                </div>
            `;
        }
    } catch (error) {
        console.error('加载用户统计失败:', error);
    }
}

/**
 * 历史训练记录列表
 */
let historyViewMode = false;

async function loadTrainingHistory() {
    const listEl = document.getElementById('history-list');
    const emptyEl = document.getElementById('history-empty');
    if (!listEl || !currentUser) return;

    try {
        const response = await fetch(`${API_BASE}/users/${currentUser}/history?limit=100`);
        if (!response.ok) {
            throw new Error('获取历史记录失败');
        }
        const data = await response.json();
        const items = (data && data.history) || [];

        listEl.innerHTML = '';
        if (!items.length) {
            if (emptyEl) emptyEl.classList.remove('hidden');
            return;
        }
        if (emptyEl) emptyEl.classList.add('hidden');
        items.forEach(item => listEl.appendChild(buildHistoryItem(item)));
    } catch (error) {
        console.error('加载历史训练失败:', error);
    }
}

function buildHistoryItem(item) {
    const wrap = document.createElement('div');
    wrap.className = 'history-item';

    const returnPct = item.total_return === null || item.total_return === undefined ? null : Number(item.total_return);
    const returnClass = returnPct === null ? '' : (returnPct >= 0 ? 'positive' : 'negative');
    const trades = item.total_trades || 0;
    const returnText = trades === 0 ? '未交易' : (returnPct === null ? '—' : `${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(2)}%`);
    const drawdownText = item.max_drawdown ? `${Number(item.max_drawdown).toFixed(2)}%` : '—';
    const winRateText = item.session_win_rate === null || item.session_win_rate === undefined ? '—' : `${Number(item.session_win_rate).toFixed(0)}%`;
    const statusText = (item.status === 'completed' || item.status === 'ended')
        ? '已结束'
        : (item.has_report ? '进行中' : '未完成');
    const dateText = (item.start_date || '') + (item.end_date ? ` → ${item.end_date}` : '');
    const nameText = item.stock_name || '';
    const aiBadge = item.has_ai_analysis ? '<span class="history-badge ai">已存 AI 点评</span>' : '';

    wrap.innerHTML = `
        <div class="history-item-main">
            <div class="history-item-title">
                <span>${nameText || item.stock_code || '未知标的'}</span>
                <span class="history-item-code">${item.stock_code || ''}</span>
                <span class="history-badge">${statusText}</span>
                ${aiBadge}
            </div>
            <div class="history-item-metrics">
                <span>收益 <b class="history-return ${returnClass}">${returnText}</b></span>
                <span>最大回撤 <b>${drawdownText}</b></span>
                <span>局胜率 <b>${winRateText}</b></span>
                <span>成交 <b>${trades}</b> 笔</span>
                <span>${dateText}</span>
                <span>${item.mode === 'weekly' ? '周线' : '日线'}</span>
            </div>
        </div>
        <div class="history-item-actions"></div>
    `;

    const actions = wrap.querySelector('.history-item-actions');

    const reportBtn = document.createElement('button');
    reportBtn.className = 'btn btn-secondary';
    reportBtn.textContent = '查看报告';
    reportBtn.addEventListener('click', () => openHistorySession(item.session_id, false));
    actions.appendChild(reportBtn);

    const aiBtn = document.createElement('button');
    aiBtn.className = 'btn btn-info';
    aiBtn.textContent = item.has_ai_analysis ? '查看 AI 点评' : '生成 AI 点评';
    aiBtn.addEventListener('click', () => openHistorySession(item.session_id, true));
    actions.appendChild(aiBtn);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-danger';
    delBtn.textContent = '删除';
    delBtn.addEventListener('click', () => deleteHistorySession(item, wrap));
    actions.appendChild(delBtn);

    return wrap;
}

/**
 * 删除一条历史训练记录（含保存的报告与 AI 点评），删除后无法恢复
 */
async function deleteHistorySession(item, wrapEl) {
    if (!currentUser || !item || !item.session_id) return;

    const label = `${item.stock_name || ''} ${item.stock_code || ''}`.trim() || item.session_id;
    const isRunning = !(item.status === 'completed' || item.status === 'ended');
    const tip = isRunning
        ? `这条「${label}」还标记为「进行中」，删除后无法继续训练。\n确定删除这次训练记录吗？（删除后不可恢复）`
        : `确定删除「${label}」这次训练记录吗？保存的报告和 AI 点评会一并删除，且不可恢复。`;
    if (!confirm(tip)) return;

    try {
        const response = await fetch(`${API_BASE}/users/${currentUser}/history/${item.session_id}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            let message = '删除失败';
            try {
                const err = await response.json();
                message = err.error || message;
            } catch (e) { }
            alert(message);
            return;
        }

        if (wrapEl && wrapEl.parentNode) {
            wrapEl.parentNode.removeChild(wrapEl);
        }
        const listEl = document.getElementById('history-list');
        if (listEl && listEl.children.length === 0) {
            const emptyEl = document.getElementById('history-empty');
            if (emptyEl) emptyEl.classList.remove('hidden');
        }
        loadUserStatistics();
    } catch (error) {
        console.error('删除历史训练失败:', error);
        alert('删除失败，请确认后端服务正常。');
    }
}

/**
 * 打开一次历史训练：恢复当时的复盘报告，并尽量带出已保存的 AI 点评
 */
async function openHistorySession(sessionId, wantAi) {
    if (!currentUser || !sessionId) return;

    try {
        const response = await fetch(`${API_BASE}/users/${currentUser}/history/${sessionId}`);
        if (!response.ok) {
            throw new Error('读取历史记录失败');
        }
        const data = await response.json();

        if (!data.report) {
            alert('这次训练没有保存报告：可能是中途关闭了窗口、旧版本训练，或者这条记录已经失效。\n可以直接点这条记录右侧的「删除」把它清掉。');
            return;
        }

        if (data.report && !data.report.session_id) {
            data.report.session_id = sessionId; // 曲线点评要按 session_id 取结构化数据
        }
        showReport(data.report);
        historyViewMode = true;

        // 历史会话已结束，无法再拉完整走势
        const fullChartBtn = document.getElementById('view-full-chart-btn');
        if (fullChartBtn) fullChartBtn.classList.add('hidden');
        const returnBtn = document.getElementById('return-main-menu-btn');
        if (returnBtn) returnBtn.textContent = '返回主菜单';

        if (data.ai_analysis) {
            renderAICommentarySection(data.ai_analysis, true);
        } else if (wantAi) {
            await requestAIAnalysis();
        }
    } catch (error) {
        console.error('打开历史训练失败:', error);
        alert('打开历史训练失败，请确认后端服务正常。');
    }
}

/**
 * 把 AI 点评文本渲染到报告页
 */
function renderAICommentarySection(commentary, cached = false) {
    if (!commentary) return;

    const reportContent = document.getElementById('report-content');
    if (!reportContent) return;

    let aiSection = document.querySelector('.ai-commentary-section');
    if (!aiSection) {
        aiSection = document.createElement('div');
        aiSection.className = 'ai-commentary-section';
        const detailsSection = document.querySelector('.trade-details-section');
        if (detailsSection) {
            reportContent.insertBefore(aiSection, detailsSection);
        } else {
            reportContent.appendChild(aiSection);
        }
    }

    const parts = splitCommentaryForFold(commentary);
    let formattedContent = '';
    if (typeof marked !== 'undefined') {
        formattedContent = marked.parse(parts.main);
    } else {
        formattedContent = parts.main.replace(/\n/g, '<br>');
    }
    const scores = extractReviewScores(commentary);
    const scoreHtml = scores.length ? `
        <div class="ai-score-row">
            ${scores.map(s => `<div class="ai-score-card"><span class="ai-score-label">${s.label}</span><span class="ai-score-value">${s.value}</span></div>`).join('')}
            <span class="ai-score-hint">两个分数独立，不合并成一个总分</span>
        </div>` : '';
    let appendixHtml = '';
    if (parts.appendix) {
        const rendered = typeof marked !== 'undefined' ? marked.parse(parts.appendix) : parts.appendix.replace(/\n/g, '<br>');
        appendixHtml = `
            <details class="ai-fold">
                <summary>展开附录：全部成交逐笔点评 / 重点交易深度点评 / 历史问题证据</summary>
                <div class="ai-content">${rendered}</div>
            </details>`;
    }

    aiSection.innerHTML = `
        <h3>🤖 AI 复盘点评</h3>
        ${scoreHtml}
        <div class="ai-content">${formattedContent}</div>
        ${appendixHtml}
        <div class="ai-commentary-actions">
            <button type="button" id="regenerate-ai-btn" class="btn btn-secondary">用当前提示词重新生成</button>
            <span class="ai-cached-hint">${cached ? '以上内容来自历史记录，未调用模型' : '已保存到历史记录，下次查看不会重复调用模型'}</span>
        </div>
    `;
    document.getElementById('regenerate-ai-btn')?.addEventListener('click', () => requestAIAnalysis(true));
    aiSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/**
 * 报告首页与附录分离：附录（逐笔点评/重点交易/历史证据）默认折叠
 */
function splitCommentaryForFold(commentary) {
    const lines = String(commentary || '').split('\n');
    const idx = lines.findIndex(line => /^[#*\s]*附录\s*A/.test(line.trim()));
    if (idx < 0) return { main: commentary, appendix: '' };
    return {
        main: lines.slice(0, idx).join('\n').trim(),
        appendix: lines.slice(idx).join('\n').trim()
    };
}

/**
 * 抓取双维度评分（模板固定输出「交易执行质量：XX/100」「收益表现：XX/100」）
 */
function extractReviewScores(commentary) {
    const text = String(commentary || '');
    const out = [];
    const patterns = [
        ['交易执行质量', /交易执行质量[^\d]{0,6}(\d{1,3}(?:\.\d)?)\s*\/\s*100/],
        ['收益表现', /收益表现[^\d]{0,6}(\d{1,3}(?:\.\d)?)\s*\/\s*100/]
    ];
    patterns.forEach(([label, re]) => {
        const m = text.match(re);
        if (m) out.push({ label, value: m[1] });
    });
    return out;
}

/**
 * 控制顶部工具栏在训练期间的元素可见性
 * @param {boolean} isTraining - 是否正在进行训练
 */
function toggleToolbarForTraining(isTraining) {
    const elementsToToggle = [
        document.getElementById('switch-user-btn'),
        document.getElementById('theme-toggle-btn'),
        document.getElementById('data-sync-btn'),
        document.getElementById('settings-btn'),
        document.getElementById('new-training-btn'),
        document.getElementById('main-title') // 新增的标题元素
    ];

    elementsToToggle.forEach(el => {
        if (el) { // 确保元素存在
            el.classList.toggle('hidden', isTraining);
        }
    });
}

/**
 * 重置整个训练环境，回到主应用界面
 * 用于从复盘报告或训练界面返回时，清理所有状态
 */
function resetToMainAppState() {
    const cleanupTrainingId = currentTraining?.id;
    // 1. 暂停任何正在进行的回放
    if (isPlaying) {
        pausePlayback();
    }
    stopAutoSync();

    // 2. 清理图表对象和数据
    if (chart) {
        chart.remove();
        chart = null;
    }
    if (volumeChart) {
        volumeChart.remove();
        volumeChart = null;
    }
    if (indicatorChart) {
        indicatorChart.remove();
        indicatorChart = null;
    }
    disposeReportCharts();
    document.getElementById('report-price-chart').innerHTML = '';
    document.getElementById('report-equity-chart').innerHTML = '';
    const frOverlay = document.getElementById('fill-review-overlay');
    if (frOverlay) frOverlay.innerHTML = '';
    if (typeof frState !== 'undefined') {
        frState.token += 1;
        frState.available = false;
        frState.clusters = [];
    }
    if (typeof frCloseCard === 'function') frCloseCard();
    document.getElementById('fill-review-panel')?.classList.add('hidden');
    // 清空图表容器，确保 Lightweight Charts 的 DOM 被彻底移除
    document.getElementById('chart').innerHTML = '';
    document.getElementById('volume-chart').innerHTML = '';
    const indicatorCanvas = document.getElementById('indicator-canvas');
    if (indicatorCanvas) {
        indicatorCanvas.innerHTML = '';
    }

    // 3. 重置所有图表系列变量
    candlestickSeries = null;
    volumeSeries = null;
    maSeries = {};
    indicatorSeries = null;
    tradeMarkerSeries = null;
    tradeMarkersPlugin = null;
    cooldownMarkersData = [];
    signalMarkersData = [];
    positionGuideLines = { cost: null, stop: null, take: null };
    positionGuidePrices = { cost: null, stop: null, take: null };
    currentIndicatorSeries = [];
    bollSeries = {};
    latestRenderedKlineData = [];

    // 4. 清理界面上的动态数据
    // 清理交易记录
    document.getElementById('trade-history').innerHTML = '<div class="no-trades">暂无交易记录</div>';
    // 清理持仓信息
    document.getElementById('current-positions').innerHTML = '<div class="no-positions">暂无持仓</div>';
    // 清理账户信息
    document.getElementById('total-assets').textContent = '¥-';
    document.getElementById('available-cash').textContent = '¥-';
    document.getElementById('position-value').textContent = '¥-';
    document.getElementById('floating-pnl').textContent = '¥-';
    document.getElementById('floating-pnl').style.color = '#000000';
    
    // reset shift toggle
    isShiftClicked = false;
    isShiftKeyPressed = false;
    if(typeof updatePriceMode === 'function') updatePriceMode();
    document.getElementById('max-buy-quantity').textContent = '0';
    document.getElementById('max-sell-quantity').textContent = '0';
    document.getElementById('buy-percent').value = '100';
    document.getElementById('sell-percent').value = '100'; // 重置交易比例
    updateTradePercentHint('buy');
    updateTradePercentHint('sell');
    maxBuyLots = 0;
    maxSellLots = 0;
    // 清理K线信息
    document.getElementById('stock-name').textContent = '未知股票';
    document.getElementById('current-date').textContent = 'YYYY/MM/DD';
    document.getElementById('current-price').textContent = '¥-.--';
    document.getElementById('current-bar-id').textContent = 'Bar ID: N/A';
    document.getElementById('training-progress').textContent = '进度: -';


    // 5. 重置全局状态变量
    currentTraining = null;
    updatePeriodBadge('daily');
    isPlaying = false;
    trainingSetupReturnScreen = 'main';

    // 6. 隐藏所有主要界面，然后显示主应用界面
    document.getElementById('training-interface').classList.add('hidden');
    document.getElementById('report-interface').classList.add('hidden');
    document.getElementById('user-selection').classList.add('hidden');
    document.getElementById('main-app').classList.remove('hidden');
    document.getElementById('main-app').classList.remove('training-mode');

    setTrainingViewOnlyMode(false, { showBackToReport: false });

    // 清理后端的训练会话
    if (cleanupTrainingId) {
        fetch(`${API_BASE}/training/${cleanupTrainingId}/cleanup`, { method: 'POST' })
            .catch(e => console.error('Cleanup failed:', e));
    }
    
    // Clear current report data and training data
    currentReportData = null;
    currentTraining = null;
    historyViewMode = false;

    // 恢复历史模式里隐藏的报告页按钮
    const fullChartBtn = document.getElementById('view-full-chart-btn');
    if (fullChartBtn) fullChartBtn.classList.remove('hidden');
    const returnMainBtn = document.getElementById('return-main-menu-btn');
    if (returnMainBtn) returnMainBtn.textContent = '返回主菜单';

    // 7. 确保主界面的工具栏是可见的
    toggleToolbarForTraining(false);

    // 8. 刷新历史训练记录列表
    loadTrainingHistory();
}

// 界面切换
function showUserSelection() {
    document.getElementById('user-selection').classList.remove('hidden');
    document.getElementById('main-app').classList.add('hidden');
    document.getElementById('training-interface').classList.add('hidden');
    document.getElementById('report-interface').classList.add('hidden');
    currentUser = null;
    localStorage.removeItem('currentUser');
}

function showMainApp() {
    document.getElementById('user-selection').classList.add('hidden');
    document.getElementById('main-app').classList.remove('hidden');
    document.getElementById('main-app').classList.remove('training-mode');
    document.getElementById('training-interface').classList.add('hidden');
    document.getElementById('report-interface').classList.add('hidden');
    updatePeriodBadge('daily');
    setTrainingViewOnlyMode(false, { showBackToReport: false });

    // 确保按钮和标题是可见的
    toggleToolbarForTraining(false);
}

async function showTrainingSetup(returnScreen = null) {
    trainingSetupReturnScreen = returnScreen || (document.getElementById('report-interface').classList.contains('hidden') ? 'main' : 'report');
    if (currentUser) {
        try {
            const response = await fetch(`${API_BASE}/users/${currentUser}/settings`);
            const settings = await response.json();
            // 应用默认初始资金，如果不存在则使用100000
            document.getElementById('initial-capital').value = settings.default_initial_capital || 100000;
        } catch (error) {
            console.error('加载用户默认资金失败:', error);
            // 加载失败时使用硬编码的默认值
            document.getElementById('initial-capital').value = 100000;
        }
    }
    document.getElementById('training-setup').classList.remove('hidden');
    // 设置默认日期为一年前
    const oneYearAgo = new Date();
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
    document.getElementById('start-date').value = oneYearAgo.toISOString().split('T')[0];
}

function hideTrainingSetup() {
    document.getElementById('training-setup').classList.add('hidden');
    trainingSetupReturnScreen = 'main';
}

function showDataSyncModal() {
    const modal = document.getElementById('data-sync-modal');
    if (!modal) return;

    const currentStock = currentTraining?.stock_code || document.getElementById('stock-code')?.value || '';
    const stockInput = document.getElementById('sync-stock-code');
    const startInput = document.getElementById('sync-start-date');
    const endInput = document.getElementById('sync-end-date');
    const sourceSelect = document.getElementById('sync-source');
    const scopeSelect = document.getElementById('sync-scope');
    const forceFull = document.getElementById('sync-force-full');
    const resultBox = document.getElementById('sync-result');
    const progressWrap = document.getElementById('sync-progress-wrap');
    const progressFill = document.getElementById('sync-progress-fill');
    const progressText = document.getElementById('sync-progress-text');

    if (stockInput && currentStock) stockInput.value = currentStock;
    if (startInput && !startInput.value) {
        startInput.value = '2010-01-01';
    }
    if (endInput && !endInput.value) {
        endInput.value = new Date().toISOString().split('T')[0];
    }
    if (sourceSelect && !sourceSelect.value) {
        sourceSelect.value = 'akshare';
    }
    if (forceFull) forceFull.checked = false;
    if (scopeSelect && !scopeSelect.value) {
        scopeSelect.value = 'single';
    }
    if (resultBox) {
        resultBox.classList.add('hidden');
        resultBox.textContent = '';
    }
    if (progressWrap) {
        progressWrap.classList.add('hidden');
    }
    if (progressFill) {
        progressFill.style.width = '0%';
    }
    if (progressText) {
        progressText.textContent = '准备中...';
    }

    updateSyncScopeUI();
    modal.classList.remove('hidden');
}

function hideDataSyncModal() {
    document.getElementById('data-sync-modal')?.classList.add('hidden');
}

function updateSyncScopeUI() {
    const scope = document.getElementById('sync-scope')?.value || 'single';
    const stockInput = document.getElementById('sync-stock-code');
    const stockGroup = stockInput?.closest('.form-group');
    if (stockGroup) {
        stockGroup.classList.toggle('hidden', scope !== 'single');
    }
}

function updateSyncProgress(completed, total, label = '') {
    const progressWrap = document.getElementById('sync-progress-wrap');
    const progressFill = document.getElementById('sync-progress-fill');
    const progressText = document.getElementById('sync-progress-text');
    if (!progressWrap || !progressFill || !progressText) return;

    progressWrap.classList.remove('hidden');
    const percent = total > 0 ? Math.min(100, (completed / total) * 100) : 0;
    progressFill.style.width = `${percent}%`;
    progressText.textContent = label || `${completed}/${total}`;
}

function getSyncThrottleMs(source) {
    if (source === 'xtdata') return 40;
    if (source === 'mootdx') return 240;
    return 260;
}

function getSyncScopeLabel(scope) {
    if (scope === 'sh') return '全沪市';
    if (scope === 'sz') return '全深市';
    if (scope === 'all') return '全市场';
    return '单只股票';
}

function describeSyncRange(startDate, endDate) {
    if (startDate && endDate) {
        return `${startDate} ~ ${endDate}`;
    }
    if (startDate) {
        return `${startDate} 起`;
    }
    if (endDate) {
        return `截至 ${endDate}`;
    }
    return '默认区间';
}

async function syncSingleStock(stockCode, source, startDate, endDate, forceFull) {
    const response = await fetch(`${API_BASE}/data/sync`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            stock_code: stockCode,
            source,
            start_date: startDate || null,
            end_date: endDate || null,
            force_full: forceFull,
        }),
    });
    const result = await response.json();
    if (!response.ok) {
        throw new Error(result.error || '补数失败');
    }
    return result;
}

async function syncOfflineData() {
    const scope = document.getElementById('sync-scope')?.value || 'single';
    const stockCode = document.getElementById('sync-stock-code')?.value.trim();
    const source = document.getElementById('sync-source')?.value || 'akshare';
    const startDate = document.getElementById('sync-start-date')?.value || '';
    const endDate = document.getElementById('sync-end-date')?.value || '';
    const forceFull = !!document.getElementById('sync-force-full')?.checked;
    const resultBox = document.getElementById('sync-result');
    const btn = document.getElementById('confirm-sync-btn');

    if (scope === 'single' && !stockCode) {
        alert('请输入股票代码');
        return;
    }
    if (startDate && endDate && startDate > endDate) {
        alert('结束日期不能早于开始日期');
        return;
    }

    if (btn) btn.disabled = true;
    if (resultBox) {
        resultBox.classList.remove('hidden');
        resultBox.textContent = scope === 'single'
            ? `正在按区间 ${describeSyncRange(startDate, endDate)} 同步离线数据，请稍候...`
            : `正在准备批量补数列表（区间 ${describeSyncRange(startDate, endDate)}）...`;
    }

    try {
        if (scope === 'single') {
            updateSyncProgress(0, 1, '正在同步 1/1');
            const result = await syncSingleStock(stockCode, source, startDate, endDate, forceFull);
            updateSyncProgress(1, 1, '已完成 1/1');
            if (resultBox) {
                resultBox.classList.remove('hidden');
                const beforeRange = result.range_before ? `${result.range_before.start} ~ ${result.range_before.end}` : '无本地数据';
                const afterRange = result.range_after ? `${result.range_after.start} ~ ${result.range_after.end}` : '无数据';
                const plannedRangeText = Array.isArray(result.planned_ranges) && result.planned_ranges.length > 0
                    ? ` 计划补齐 ${result.planned_ranges.map(item => `${item.start} ~ ${item.end}`).join('；')}。`
                    : '';
                const fetchedRangeText = Array.isArray(result.fetched_ranges) && result.fetched_ranges.length > 0
                    ? ` 实际抓取 ${result.fetched_ranges.map(item => `${item.start} ~ ${item.end}`).join('；')}。`
                    : '';
                const missingRangeText = Array.isArray(result.missing_ranges) && result.missing_ranges.length > 0
                    ? ` 在线源未返回 ${result.missing_ranges.map(item => `${item.start} ~ ${item.end}`).join('；')}。`
                    : '';
                const fileStateText = result.local_file_changed === false ? ' 本地文件未改动。' : '';
                resultBox.textContent = `完成: ${result.message} 请求区间 ${describeSyncRange(startDate, endDate)}，本地范围 ${beforeRange} -> ${afterRange}，新增 ${result.added_rows || 0} 条，抓取 ${result.fetched_rows || 0} 条。${plannedRangeText}${fetchedRangeText}${missingRangeText}${fileStateText}`;
            }
        } else {
            const universeResponse = await fetch(`${API_BASE}/data/stock_universe?market=${scope}`);
            const universePayload = await universeResponse.json();
            if (!universeResponse.ok) {
                throw new Error(universePayload.error || '获取股票列表失败');
            }

            const stockCodes = universePayload.stock_codes || [];
            if (stockCodes.length === 0) {
                if (universePayload.stock_list_pending) {
                    throw new Error('股票列表还在后台下载，稍等片刻再试');
                }
                throw new Error('当前市场没有可补数的股票列表');
            }

            let successCount = 0;
            let failureCount = 0;
            let addedRows = 0;
            let latestSuccessCode = '';
            const throttleMs = getSyncThrottleMs(source);

            for (let index = 0; index < stockCodes.length; index += 1) {
                const code = stockCodes[index];
                updateSyncProgress(index, stockCodes.length, `正在补数 ${index + 1}/${stockCodes.length}：${code}`);
                try {
                    const result = await syncSingleStock(code, source, startDate, endDate, forceFull);
                    successCount += 1;
                    addedRows += result.added_rows || 0;
                    latestSuccessCode = code;
                } catch (error) {
                    failureCount += 1;
                    console.error(`批量补数失败 ${code}:`, error);
                }

                if (index < stockCodes.length - 1) {
                    await sleep(throttleMs);
                }
            }

            updateSyncProgress(stockCodes.length, stockCodes.length, `批量补数完成 ${stockCodes.length}/${stockCodes.length}`);
            if (resultBox) {
                resultBox.classList.remove('hidden');
                resultBox.textContent = `完成: ${getSyncScopeLabel(scope)}区间 ${describeSyncRange(startDate, endDate)}，共 ${stockCodes.length} 只，成功 ${successCount}，失败 ${failureCount}，累计新增 ${addedRows} 条。${latestSuccessCode ? ` 最近成功股票 ${latestSuccessCode}。` : ''}`;
            }
        }
    } catch (error) {
        console.error('离线数据补充失败:', error);
        if (resultBox) {
            resultBox.classList.remove('hidden');
            resultBox.textContent = `失败: ${error.message || '未知错误'}`;
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

function showSettings() {
    document.getElementById('settings-modal').classList.remove('hidden');
    loadUserSettings();
}

function renderMaPeriodsEditor() {
    const container = document.getElementById('ma-periods-editor');
    if (!container) return;
    container.innerHTML = '';

    maPeriods.forEach((p, index) => {
        const tag = document.createElement('div');
        tag.className = 'ma-period-tag';
        const value = document.createElement('span');
        value.className = 'ma-period-value';
        value.textContent = `MA${p}`;

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'ma-period-remove delete-ma';
        removeBtn.dataset.index = String(index);
        removeBtn.setAttribute('aria-label', `删除 MA${p}`);
        removeBtn.textContent = 'x';

        tag.appendChild(value);
        tag.appendChild(removeBtn);
        container.appendChild(tag);
    });

    if (maPeriods.length < 6) {
        const addBtn = document.createElement('button');
        addBtn.className = 'btn-add-ma';
        addBtn.type = 'button';
        addBtn.textContent = '+';
        addBtn.onclick = () => {
            const val = prompt('输入新的均线周期 (如: 60):');
            if (val && !isNaN(val)) {
                const p = parseInt(val);
                if (p > 0 && !maPeriods.includes(p)) {
                    maPeriods.push(p);
                    maPeriods.sort((a, b) => a - b);
                    renderMaPeriodsEditor();
                }
            }
        };
        container.appendChild(addBtn);
    }

    // 删除事件
    container.querySelectorAll('.delete-ma').forEach(btn => {
        btn.onclick = (e) => {
            const idx = parseInt(e.target.dataset.index);
            maPeriods.splice(idx, 1);
            renderMaPeriodsEditor();
        };
    });
}

function hideSettings() {
    document.getElementById('settings-modal').classList.add('hidden');
}

let defaultAiReviewPrompt = '';

/**
 * 拉取当前用户的 AI 复盘提示词（自定义内容 + 内置默认模板）
 */
async function loadAiReviewPromptEditor() {
    if (!currentUser) return;
    try {
        const response = await fetch(`${API_BASE}/users/${currentUser}/ai-review-prompt`);
        const data = await response.json();
        defaultAiReviewPrompt = data.default_prompt || '';
        const box = document.getElementById('ai-review-prompt');
        if (box) {
            box.value = data.prompt || '';
            box.placeholder = data.is_custom ? '' : '当前使用内置模板，可点「载入默认模板」后修改';
        }
    } catch (error) {
        console.error('加载 AI 复盘提示词失败:', error);
    }
}

/* AI 接口配置（写在 data/.ai_tester_config.enc，与命令行工具共用同一份） */
async function loadAIConfigEditor() {
    try {
        const resp = await fetch(`${API_BASE}/system/ai-config`);
        const data = await resp.json();
        const baseEl = document.getElementById('ai-base-url');
        const modelEl = document.getElementById('ai-model');
        const keyEl = document.getElementById('ai-api-key');
        const status = document.getElementById('ai-config-status');
        if (baseEl) baseEl.value = data.base_url || '';
        if (modelEl) modelEl.value = data.model || '';
        if (keyEl) {
            keyEl.value = '';
            keyEl.placeholder = data.has_key
                ? `已保存 ${data.api_key_masked}（留空 = 不修改）`
                : '留空 = 沿用已保存的 Key';
        }
        if (status) {
            status.textContent = data.configured
                ? `当前已配置：${data.base_url || '(无地址)'} / ${data.model || '(无模型)'} · Key ${data.api_key_masked || '(无)'}`
                : '当前还没有 AI 配置：填好地址、模型与 Key 后点「保存」就能直接做 AI 复盘。';
        }
    } catch (error) {
        console.error('加载 AI 接口配置失败:', error);
    }
}

async function saveAIConfigFromSettings() {
    const baseEl = document.getElementById('ai-base-url');
    const modelEl = document.getElementById('ai-model');
    const keyEl = document.getElementById('ai-api-key');
    const status = document.getElementById('ai-config-status');
    const baseUrl = (baseEl?.value || '').trim();
    const model = (modelEl?.value || '').trim();
    const apiKey = (keyEl?.value || '').trim();
    if (!baseUrl && !model && !apiKey) return true;
    try {
        const resp = await fetch(`${API_BASE}/system/ai-config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ base_url: baseUrl, model: model, api_key: apiKey }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            if (status) status.textContent = 'AI 配置保存失败：' + (data.error || resp.status);
            return false;
        }
        if (keyEl) keyEl.value = '';
        if (status) status.textContent = `已保存：${data.base_url} / ${data.model} · Key ${data.api_key_masked}`;
        return true;
    } catch (error) {
        if (status) status.textContent = 'AI 配置保存失败：' + error.message;
        return false;
    }
}

async function testAIConfig() {
    const status = document.getElementById('ai-config-status');
    const payload = {
        base_url: (document.getElementById('ai-base-url')?.value || '').trim(),
        model: (document.getElementById('ai-model')?.value || '').trim(),
        api_key: (document.getElementById('ai-api-key')?.value || '').trim(),
    };
    if (status) status.textContent = '正在测试连接…';
    try {
        const resp = await fetch(`${API_BASE}/system/ai-config/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (status) status.textContent = data.message || '测试失败';
    } catch (error) {
        if (status) status.textContent = '测试失败：' + error.message;
    }
}

async function clearAIConfig() {
    const status = document.getElementById('ai-config-status');
    try {
        const resp = await fetch(`${API_BASE}/system/ai-config`, { method: 'DELETE' });
        const data = await resp.json();
        const baseEl = document.getElementById('ai-base-url');
        const modelEl = document.getElementById('ai-model');
        const keyEl = document.getElementById('ai-api-key');
        if (baseEl) baseEl.value = '';
        if (modelEl) modelEl.value = '';
        if (keyEl) {
            keyEl.value = '';
            keyEl.placeholder = '留空 = 沿用已保存的 Key';
        }
        if (status) status.textContent = data.message || '已清除';
    } catch (error) {
        if (status) status.textContent = '清除失败：' + error.message;
    }
}

async function loadUserSettings() {
    if (!currentUser) return;

    try {
        const response = await fetch(`${API_BASE}/users/${currentUser}/settings`);
        const settings = await response.json();

        document.getElementById('default-initial-capital').value = settings.default_initial_capital || 100000;
        document.getElementById('commission-rate').value = (settings.commission_rate * 10000).toFixed(1);
        document.getElementById('min-commission').value = settings.min_commission;
        document.getElementById('stamp-tax-rate').value = (settings.stamp_tax_rate * 1000).toFixed(1);
        document.getElementById('theme-select').value = settings.theme || currentTheme;
        document.getElementById('adjustment-mode').value = 'forward';
        const adjustmentRadio = document.querySelector('input[name="adjustment"][value="forward"]');
        if (adjustmentRadio) {
            adjustmentRadio.checked = true;
        }

        // 加载 AI API 设置
        if (settings.enable_ai_api !== undefined) {
            document.getElementById('enable-ai-api').checked = settings.enable_ai_api;
        } else {
            document.getElementById('enable-ai-api').checked = false;
        }

        // 加载清仓后禁买期
        document.getElementById('cooldown-bars-after-flat').value =
            settings.cooldown_bars_after_flat !== undefined ? settings.cooldown_bars_after_flat : 3;

        // 加载成本线辅助（止损 / 止盈）
        document.getElementById('stop-loss-percent').value =
            settings.stop_loss_percent !== undefined ? settings.stop_loss_percent : 10;
        document.getElementById('take-profit-percent').value =
            settings.take_profit_percent !== undefined ? settings.take_profit_percent : 20;

        // 加载 AI 复盘提示词
        await loadAiReviewPromptEditor();
        // 加载 AI 接口配置（base_url / model / Key 掩码）
        await loadAIConfigEditor();

        // 加载MA周期
        if (settings.ma_periods && Array.isArray(settings.ma_periods)) {
            maPeriods = [...settings.ma_periods];
        } else {
            maPeriods = [5, 10, 20];
        }
        renderMaPeriodsEditor();

        // 加载指标配置
        if (settings.indicators) {
            const ind = settings.indicators;
            if (ind.macd) {
                document.getElementById('macd-fast').value = ind.macd.fast || 12;
                document.getElementById('macd-slow').value = ind.macd.slow || 26;
                document.getElementById('macd-signal').value = ind.macd.signal || 9;
            }
            if (ind.kdj) {
                document.getElementById('kdj-n').value = ind.kdj.n || 9;
                document.getElementById('kdj-m1').value = ind.kdj.m1 || 3;
                document.getElementById('kdj-m2').value = ind.kdj.m2 || 3;
            }
            if (ind.rsi && ind.rsi.periods) {
                document.getElementById('rsi-periods').value = ind.rsi.periods.join(',');
            }
            if (ind.boll) {
                document.getElementById('boll-period').value = ind.boll.period || 20;
                document.getElementById('boll-std-dev').value = ind.boll.std_dev || 2;
            }
        }
    } catch (error) {
        console.error('加载用户设置失败:', error);
    }
}

async function saveSettings() {
    if (!currentUser) return;

    try {
        // 收集指标参数
        const indicators = {
            macd: {
                fast: parseInt(document.getElementById('macd-fast').value) || 12,
                slow: parseInt(document.getElementById('macd-slow').value) || 26,
                signal: parseInt(document.getElementById('macd-signal').value) || 9
            },
            kdj: {
                n: parseInt(document.getElementById('kdj-n').value) || 9,
                m1: parseInt(document.getElementById('kdj-m1').value) || 3,
                m2: parseInt(document.getElementById('kdj-m2').value) || 3
            },
            rsi: {
                periods: document.getElementById('rsi-periods').value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))
            },
            boll: {
                period: parseInt(document.getElementById('boll-period').value) || 20,
                std_dev: parseFloat(document.getElementById('boll-std-dev').value) || 2
            }
        };
        if (indicators.rsi.periods.length === 0) indicators.rsi.periods = [6, 12, 24];

        const settings = {
            default_initial_capital: parseInt(document.getElementById('default-initial-capital').value, 10),
            commission_rate: parseFloat(document.getElementById('commission-rate').value) / 10000,
            min_commission: parseFloat(document.getElementById('min-commission').value),
            stamp_tax_rate: parseFloat(document.getElementById('stamp-tax-rate').value) / 1000,
            adjustment_mode: 'forward',
            theme: document.getElementById('theme-select').value,
            enable_ai_api: document.getElementById('enable-ai-api').checked,
            cooldown_bars_after_flat: Math.max(0, parseInt(document.getElementById('cooldown-bars-after-flat').value, 10) || 0),
            ai_review_prompt: (document.getElementById('ai-review-prompt')?.value || '').trim(),
            stop_loss_percent: getGuidePercent('stop-loss-percent', 10),
            take_profit_percent: getGuidePercent('take-profit-percent', 20),
            ma_periods: maPeriods,
            indicators: indicators
        };

        const response = await fetch(`${API_BASE}/users/${currentUser}/settings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });

        if (response.ok) {
            const adjustmentRadio = document.querySelector('input[name="adjustment"][value="forward"]');
            if (adjustmentRadio) {
                adjustmentRadio.checked = true;
            }

            // 顺手保存设置窗口里的 AI 接口配置（没填就跳过）
            await saveAIConfigFromSettings();

            // 更新 AI 接口信息
            updateAIApiStatus(settings.enable_ai_api, currentUser);
            applyTheme(settings.theme, true, false);

            // 止损/止盈比例变了，持仓中的辅助线立刻重算
            if (currentTraining && currentTraining.id && candlestickSeries) {
                updateAccountInfo();
            }

            hideSettings();
            alert('设置保存成功');
        } else {
            alert('设置保存失败');
        }
    } catch (error) {
        console.error('保存设置失败:', error);
        alert('保存设置失败');
    }
}

function switchTab(tabName) {
    // 更新标签按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // 更新标签内容显示
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `${tabName}-tab`);
    });
}

function replaceRenderedKlineData(klineData) {
    latestRenderedKlineData = Array.isArray(klineData) ? klineData.map(item => ({ ...item })) : [];
}

function upsertRenderedBar(bar) {
    if (!bar) return;
    if (latestRenderedKlineData.length === 0) {
        latestRenderedKlineData = [{ ...bar }];
        return;
    }

    const lastBar = latestRenderedKlineData[latestRenderedKlineData.length - 1];
    if (lastBar.time === bar.time) {
        latestRenderedKlineData[latestRenderedKlineData.length - 1] = { ...bar };
        return;
    }

    latestRenderedKlineData.push({ ...bar });
}

function shiftLogicalRange(range, delta = 1) {
    if (!range) return null;
    return {
        from: range.from + delta,
        to: range.to + delta
    };
}

function setVisibleRangeAll(range) {
    if (!range) return;
    chart?.timeScale().setVisibleLogicalRange(range);
    volumeChart?.timeScale().setVisibleLogicalRange(range);
    indicatorChart?.timeScale().setVisibleLogicalRange(range);
}

function applyTrainingSnapshot(data, options = {}) {
    const { fitContent = false } = options;
    if (!data.kline_data || data.kline_data.length === 0) {
        throw new Error('训练数据为空');
    }

    if (currentTraining) {
        currentTraining.latestProgress = data.progress || null;
        currentTraining.tradeMarkers = data.trade_markers || [];
        cooldownMarkersData = data.cooldown_markers || [];
        signalMarkersData = data.signal_markers || [];
    }

    candlestickSeries.setData(data.kline_data);
    volumeSeries.setData(data.volume_data || []);
    replaceRenderedKlineData(data.kline_data);

    if (data.ma_data) {
        maPeriods.forEach(p => {
            if (maSeries[p]) {
                maSeries[p].setData(data.ma_data[p] || []);
            }
        });
    }

    const currentBar = data.kline_data[data.kline_data.length - 1];
    updateCurrentInfo(currentBar, data.progress);
    // 标记绘制失败不能阻断后续图表/指标刷新
    try {
        updateTradeMarkers(data.trade_markers || [], cooldownMarkersData, signalMarkersData);
    } catch (markerError) {
        console.warn('刷新交易标记失败:', markerError);
    }

    if (fitContent) {
        chart.timeScale().fitContent();
    }
}

async function refreshTrainingView(options = {}) {
    if (!currentTraining || !currentTraining.id) return;
    const { preserveRange = true, fitContent = false } = options;
    const visibleRange = preserveRange && chart ? chart.timeScale().getVisibleLogicalRange() : null;
    const maQuery = maPeriods.join(',');
    const dataEndpoint = isViewOnlyMode ? 'full_data' : 'data';
    const response = await fetch(`${API_BASE}/training/${currentTraining.id}/${dataEndpoint}?ma_periods=${maQuery}&${getViewPeriodQuery()}`);
    if (!response.ok) {
        throw new Error(`刷新训练视图失败: ${response.status}`);
    }

    const data = await response.json();
    if (data.stock_name) {
        document.getElementById('stock-name').textContent = data.stock_name;
    }
    applyTrainingSnapshot(data, { fitContent });
    await loadTechnicalIndicator(currentIndicatorType);
    await ensureIndicatorSeries();
    if (visibleRange !== null) {
        setVisibleRangeAll(visibleRange);
    }
    await updateChipDistribution();
}

async function switchViewPeriod(period) {
    const nextPeriod = period === 'weekly' ? 'weekly' : 'daily';
    if (currentPeriod === nextPeriod) {
        updatePeriodBadge(nextPeriod);
        return;
    }

    updatePeriodBadge(nextPeriod);
    if (!currentTraining || !currentTraining.id || !chart) {
        return;
    }

    showLoading(nextPeriod === 'weekly' ? '正在切换周K视图' : '正在切换日K视图');
    try {
        await refreshTrainingView({ preserveRange: false, fitContent: true });
    } catch (error) {
        console.error('切换K线视图失败:', error);
        alert('切换K线视图失败');
    } finally {
        hideLoading();
    }
}

// 训练管理
async function startTraining() {
    const isRandomMode = document.querySelector('.tab-btn.active').dataset.tab === 'random';
    const initialCapital = parseFloat(document.getElementById('initial-capital').value);
    const dataSource = document.getElementById('data-source').value || 'akshare';
    const period = document.getElementById('kline-period')?.value || 'daily';

    let trainingConfig = {
        user: currentUser,
        initial_capital: initialCapital,
        mode: isRandomMode ? 'random' : 'specified',
        data_source: dataSource,
        period: period
    };

    if (isRandomMode) {
        trainingConfig.sector = document.getElementById('sector-filter').value;
        trainingConfig.date_start = document.getElementById('random-start-date').value.trim();
        trainingConfig.date_end = document.getElementById('random-end-date').value.trim();
    } else {
        const stockCode = document.getElementById('stock-code').value.trim();
        const startDate = document.getElementById('start-date').value;

        if (!stockCode || !startDate) {
            alert('请填写完整的股票代码和起始日期');
            return;
        }

        trainingConfig.stock_code = stockCode;
        trainingConfig.start_date = startDate;
    }

    try {
        updatePeriodBadge(period);
        showLoading(
            dataSource === 'offline' ? '正在筛选本地离线数据' : '正在创建训练',
            dataSource === 'offline' ? '首次校验离线股票可用范围时会稍慢一些。' : '正在准备图表和训练数据...'
        );
        const response = await fetch(`${API_BASE}/training/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(trainingConfig)
        });

        if (response.ok) {
            currentTraining = await response.json();
            currentTraining.period = period;
            currentReportData = null;
            resetCoachChat(true);
            hideTrainingSetup();
            document.getElementById('report-interface').classList.add('hidden');
            showTrainingInterface();
            initializeChart();
            await loadInitialData();
            await updateChipDistribution(); // 加入此行，初始化筹码分布

            // 在所有内容加载完毕后，自动触发一次 nextBar
            // 我们加一个小的延时，确保图表渲染完成，视觉效果更平滑
            setTimeout(() => {
                nextBar();
            }, 100); // 100毫秒的延时

            startAutoSync();
        } else {
            const error = await response.json();
            alert(error.error || error.message || '开始训练失败');
        }
    } catch (error) {
        console.error('开始训练失败:', error);
        alert('开始训练失败');
    } finally {
        hideLoading();
    }
}

function showTrainingInterface() {
    // 注意：#training-interface 是 #main-app 的子节点，不能隐藏 #main-app，
    // 否则训练界面会跟着一起消失（表现为整窗白屏）。改用 training-mode 只隐藏主菜单外壳。
    const mainApp = document.getElementById('main-app');
    mainApp.classList.remove('hidden');
    mainApp.classList.add('training-mode');
    document.getElementById('training-interface').classList.remove('hidden');
    setTrainingViewOnlyMode(false, { showBackToReport: false });
    updateAccountInfo();
    // 隐藏按钮和标题
    toggleToolbarForTraining(true);
}

// 图表管理
function initializeChart() {
    const palette = getThemePalette();
    // 初始化主图表
    const chartContainer = document.getElementById('chart');
    chartContainer.innerHTML = '';

    // 在图表容器内动态创建信息显示框
    const infoDisplay = document.createElement('div');
    infoDisplay.id = 'chart-info-display';
    infoDisplay.className = 'chart-info-display';
    chartContainer.appendChild(infoDisplay);

    const chartLegend = document.createElement('div');
    chartLegend.id = 'chart-legend';
    chartLegend.className = 'chart-legend';
    chartContainer.appendChild(chartLegend);

    chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth,
        height: chartContainer.clientHeight,
        layout: {
            background: { type: 'solid', color: palette.chartBg },
            textColor: palette.text,
        },
        grid: {
            vertLines: {
                color: palette.grid,
            },
            horzLines: {
                color: palette.grid,
            },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: palette.border,
            minimumWidth: 80,
        },
        // 使用 localization 选项来格式化十字标线的时间
        localization: {
            // timeFormatter 用于格式化十字标线悬浮窗中的时间
            timeFormatter: (businessDay) => {
                // businessDay 是一个 Date 对象，包含了年、月、日
                // 注意：这里的 businessDay 是一个 UTC 日期对象，所以使用 getUTCFullYear 等方法可以避免时区问题
                const date = new Date(businessDay * 1000);

                const year = date.getUTCFullYear();
                const month = ('0' + (date.getUTCMonth() + 1)).slice(-2); // 月份从0开始
                const day = ('0' + date.getUTCDate()).slice(-2);

                return `${year}年${month}月${day}日`;
            },
            locale: 'zh-CN',
        },
        timeScale: {
            borderColor: palette.border,
            timeVisible: true,
            secondsVisible: false,
            tickMarkFormatter: (time) => {
                const date = new Date(time * 1000);
                return `${date.getFullYear()}/${(date.getMonth() + 1).toString().padStart(2, '0')}/${date.getDate().toString().padStart(2, '0')}`;
            }
        },
    });

    // 添加K线系列
    candlestickSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
        upColor: 'rgba(255, 77, 79, 0)',
        downColor: palette.negative,
        borderUpColor: palette.positive,
        borderDownColor: palette.negative,
        wickUpColor: palette.positive,
        wickDownColor: palette.negative,
        borderVisible: true,
    });
    candlestickSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });

    // 添加移动平均线
    maPeriods.forEach((p, index) => {
        maSeries[p] = chart.addSeries(LightweightCharts.LineSeries, {
            color: maColors[index % maColors.length],
            lineWidth: 1,
            crosshairMarkerVisible: false,
            priceLineVisible: false,
            lastValueVisible: false,
        });
        maSeries[p].applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    });

    renderChartLegend();

    // 添加交易标记系列
    tradeMarkerSeries = chart.addSeries(LightweightCharts.LineSeries, {
        color: 'transparent',
        lineWidth: 0,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false
    });
    tradeMarkerSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });

    // 初始化成交量图表
    const volumeContainer = document.getElementById('volume-chart');
    volumeContainer.innerHTML = '';

    volumeChart = LightweightCharts.createChart(volumeContainer, {
        width: volumeContainer.clientWidth,
        height: volumeContainer.clientHeight,
        layout: {
            background: { type: 'solid', color: palette.chartBg },
            textColor: palette.text,
        },
        grid: {
            vertLines: {
                color: palette.grid,
            },
            horzLines: {
                color: palette.grid,
            },
        },
        rightPriceScale: {
            borderColor: palette.border,
            minimumWidth: 80,
        },
        timeScale: {
            borderColor: palette.border,
            visible: false,
            tickMarkFormatter: (time) => {
                const date = new Date(time * 1000);
                return `${date.getFullYear()}/${(date.getMonth() + 1).toString().padStart(2, '0')}/${date.getDate().toString().padStart(2, '0')}`;
            }
        },
    });

    // 添加成交量系列
    volumeSeries = volumeChart.addSeries(LightweightCharts.HistogramSeries, {
        color: '#26a69a',
        priceFormat: {
            type: 'volume',
        },
        priceLineVisible: false,
        lastValueVisible: false
    });

    // 初始化技术指标图表
    const indicatorContainer = document.getElementById('indicator-canvas');
    indicatorContainer.innerHTML = '';

    // 在图表容器内动态创建信息显示框
    const infoDisplay_2 = document.createElement('div');
    infoDisplay_2.id = 'indicator-info-display';
    infoDisplay_2.className = 'chart-info-display';
    indicatorContainer.appendChild(infoDisplay_2);

    const indicatorLegend = document.createElement('div');
    indicatorLegend.id = 'indicator-legend';
    indicatorLegend.className = 'chart-legend';
    indicatorContainer.appendChild(indicatorLegend);

    indicatorChart = LightweightCharts.createChart(indicatorContainer, {
        width: indicatorContainer.clientWidth,
        height: indicatorContainer.clientHeight,
        layout: {
            background: { type: 'solid', color: palette.chartBg },
            textColor: palette.text,
        },
        grid: {
            vertLines: {
                color: palette.grid,
            },
            horzLines: {
                color: palette.grid,
            },
        },
        rightPriceScale: {
            borderColor: palette.border,
            minimumWidth: 80,
        },
        timeScale: {
            borderColor: palette.border,
            visible: false,
            tickMarkFormatter: (time) => {
                const date = new Date(time * 1000);
                return `${date.getFullYear()}/${(date.getMonth() + 1).toString().padStart(2, '0')}/${date.getDate().toString().padStart(2, '0')}`;
            }
        },
    });

    // 监听主图表（K线图）的时间轴变化
    chart.timeScale().subscribeVisibleLogicalRangeChange(timeRange => {
        if (timeRange) { // 增加一个 null 检查
            volumeChart.timeScale().setVisibleLogicalRange(timeRange);
            indicatorChart.timeScale().setVisibleLogicalRange(timeRange);
        }
        scheduleChipDistributionRender();
    });
    
    chart.timeScale().subscribeVisibleTimeRangeChange(() => {
        scheduleChipDistributionRender();
    });

    // 监听成交量图表的时间轴变化
    volumeChart.timeScale().subscribeVisibleLogicalRangeChange(timeRange => {
        if (timeRange) {
            chart.timeScale().setVisibleLogicalRange(timeRange);
            indicatorChart.timeScale().setVisibleLogicalRange(timeRange);
        }
    });

    // 监听技术指标图表的时间轴变化
    indicatorChart.timeScale().subscribeVisibleLogicalRangeChange(timeRange => {
        if (timeRange) {
            chart.timeScale().setVisibleLogicalRange(timeRange);
            volumeChart.timeScale().setVisibleLogicalRange(timeRange);
        }
    });

    function getCrosshairDataPoint(series, param) {
        if (!param.time) {
            return null;
        }
        const dataPoint = param.seriesData.get(series);
        return dataPoint || null;
    }

    function syncCrosshair(chart, series, dataPoint) {
        if (dataPoint) {
            chart.setCrosshairPosition(dataPoint.value, dataPoint.time, series);
            return;
        }
        chart.clearCrosshairPosition();
    }


    chart.subscribeCrosshairMove(param => {
        const infoEl = document.getElementById('chart-info-display');
        if (!param.time || param.point.x < 0 || param.point.y < 0) {
            infoEl.style.display = 'none';
            // 同步其他图表的十字准星
            syncCrosshair(volumeChart, volumeSeries, null);
            if (currentIndicatorSeries.length > 0) {
                syncCrosshair(indicatorChart, currentIndicatorSeries[0], null);
            }
            return;
        }

        infoEl.style.display = 'block';

        // 创建数据Map以便快速查找
        const seriesData = latestRenderedKlineData;
        const dataMap = new Map();
        seriesData.forEach((dataPoint, index) => {
            // 确保数据点有时间属性
            if (dataPoint.time) {
                dataMap.set(dataPoint.time, { ...dataPoint, index });
            }
        });

        // 从Map中快速获取当前数据点及其索引
        const currentDataPoint = dataMap.get(param.time);

        if (!currentDataPoint) {
            return;
        }

        let previousDataPoint = null;
        // 检查是否存在前一个数据点
        if (currentDataPoint.index > 0) {
            // 直接通过索引从原始数据数组中获取
            previousDataPoint = seriesData[currentDataPoint.index - 1];
        }

        // 获取K线数据
        const ohlcData = param.seriesData.get(candlestickSeries);
        let ohlcHtml = '数据加载中...';
        if (ohlcData) {
            if (previousDataPoint) {
                ohlcHtml = `
                    <div style="margin-bottom: 4px;">
                        <strong>开:</strong> <span style="color: ${ohlcData.open > previousDataPoint.close ? '#ff4d4f' : ohlcData.open < previousDataPoint.close ? '#008000' : '#000000'};">${ohlcData.open.toFixed(2)}</span>
                        <strong>高:</strong> <span style="color: ${ohlcData.high > previousDataPoint.close ? '#ff4d4f' : ohlcData.high < previousDataPoint.close ? '#008000' : '#000000'};">${ohlcData.high.toFixed(2)}</span>
                        <strong>低:</strong> <span style="color: ${ohlcData.low > previousDataPoint.close ? '#ff4d4f' : ohlcData.low < previousDataPoint.close ? '#008000' : '#000000'};">${ohlcData.low.toFixed(2)}</span>
                        <strong>收: <span style="color: ${ohlcData.close > ohlcData.open ? '#ff4d4f' : ohlcData.close > ohlcData.open ? '#008000' : '#000000'};">${ohlcData.close.toFixed(2)}</span></strong>
                    </div>
                `;
            } else {
                ohlcHtml = `
                    <div style="margin-bottom: 4px;">
                        <strong>开:</strong> <span>${ohlcData.open.toFixed(2)}</span>
                        <strong>高:</strong> <span>${ohlcData.high.toFixed(2)}</span>
                        <strong>低:</strong> <span>${ohlcData.low.toFixed(2)}</span>
                        <strong>收: <span style="color: ${ohlcData.close > ohlcData.open ? '#ff4d4f' : ohlcData.close < ohlcData.open ? '#008000' : '#000000'};">${ohlcData.close.toFixed(2)}</span></strong>
                    </div>
                `;
            }
        }

        // 获取MA数据
        let maHtml = '<div>';
        maPeriods.forEach(p => {
            const mData = param.seriesData.get(maSeries[p]);
            if (mData) {
                maHtml += `<span style="color: ${maSeries[p].options().color};">MA${p}:${mData.value.toFixed(2)} </span>`;
            }
        });
        maHtml += '</div>';

        // 获取并显示BOLL指标数据
        let bollHtml = '';
        // 检查BOLL指标是否处于激活状态 (通过检查bollSeries对象)
        if (currentIndicatorType === 'BOLL' && bollSeries.upper && bollSeries.middle && bollSeries.lower) {
            const upperData = param.seriesData.get(bollSeries.upper);
            const middleData = param.seriesData.get(bollSeries.middle);
            const lowerData = param.seriesData.get(bollSeries.lower);

            if (upperData && middleData && lowerData) {
                bollHtml = `
                    <div id="boll-info-content" style="margin-top: 4px;">
                        <span style="color: ${bollSeries.upper.options().color};">UP:${upperData.value.toFixed(2)} </span>
                        <span style="color: ${bollSeries.middle.options().color};">MID:${middleData.value.toFixed(2)} </span>
                        <span style="color: ${bollSeries.lower.options().color};">LOW:${lowerData.value.toFixed(2)} </span>
                    </div>
                `;
            }
        }

        // 组合所有信息并更新到DOM
        infoEl.innerHTML = ohlcHtml + maHtml + bollHtml;

        // 同步其他图表的十字准星
        const dataPoint = getCrosshairDataPoint(candlestickSeries, param);
        syncCrosshair(volumeChart, volumeSeries, dataPoint);
        if (currentIndicatorSeries.length > 0) {
            syncCrosshair(indicatorChart, currentIndicatorSeries[0], dataPoint);
        }
    });

    volumeChart.subscribeCrosshairMove(param => {
        const dataPoint = getCrosshairDataPoint(volumeSeries, param);
        syncCrosshair(chart, candlestickSeries, dataPoint);
        if (currentIndicatorSeries.length > 0) {
            syncCrosshair(indicatorChart, currentIndicatorSeries[0], dataPoint);
        }
    });

    indicatorChart.subscribeCrosshairMove(param => {
        const infoEl = document.getElementById('indicator-info-display');
        if (!infoEl) return;

        // 如果十字准星移出图表或没有数据，则隐藏信息框
        if (!param.time || param.point.x < 0 || param.point.y < 0 || currentIndicatorSeries.length === 0) {
            infoEl.style.display = 'none';
            return;
        }

        infoEl.style.display = 'block';
        let indicatorHtml = '';

        // 根据当前指标类型，获取并格式化数据
        switch (currentIndicatorType) {
            case 'MACD':
                const difData = param.seriesData.get(currentIndicatorSeries[0]);
                const deaData = param.seriesData.get(currentIndicatorSeries[1]);
                const histData = param.seriesData.get(currentIndicatorSeries[2]);
                if (difData && deaData && histData) {
                    indicatorHtml = `
                        <div><strong>MACD</strong></div>
                        <div style="color: ${currentIndicatorSeries[0].options().color};">DIF: ${difData.value.toFixed(2)}</div>
                        <div style="color: ${currentIndicatorSeries[1].options().color};">DEA: ${deaData.value.toFixed(2)}</div>
                        <div style="color: ${histData.color};">HIST: ${histData.value.toFixed(2)}</div>
                    `;
                }
                break;

            case 'KDJ':
                const kData = param.seriesData.get(currentIndicatorSeries[0]);
                const dData = param.seriesData.get(currentIndicatorSeries[1]);
                const jData = param.seriesData.get(currentIndicatorSeries[2]);
                if (kData && dData && jData) {
                    indicatorHtml = `
                        <div><strong>KDJ</strong></div>
                        <div style="color: ${currentIndicatorSeries[0].options().color};">K: ${kData.value.toFixed(2)}</div>
                        <div style="color: ${currentIndicatorSeries[1].options().color};">D: ${dData.value.toFixed(2)}</div>
                        <div style="color: ${currentIndicatorSeries[2].options().color};">J: ${jData.value.toFixed(2)}</div>
                    `;
                }
                break;

            case 'RSI':
                indicatorHtml = '<div><strong>RSI</strong></div>';
                currentIndicatorSeries.forEach(series => {
                    const rsiData = param.seriesData.get(series);
                    if (rsiData) {
                        const titleText = series.rsiTitle || series.options().title || 'RSI';
                        indicatorHtml += `<div style="color: ${series.options().color};">${titleText}: ${rsiData.value.toFixed(2)}</div>`;
                    }
                });
                break;
        }

        infoEl.innerHTML = indicatorHtml;

        // 同步其他图表的十字准星
        if (currentIndicatorSeries.length > 0) {
            const dataPoint = getCrosshairDataPoint(currentIndicatorSeries[0], param);
            syncCrosshair(chart, candlestickSeries, dataPoint);
            syncCrosshair(volumeChart, volumeSeries, dataPoint);
        }
    });

}

// async function loadInitialData() {
//     try {
//         const response = await fetch(`${API_BASE}/training/${currentTraining.id}/data`);
//         const data = await response.json();
//
//         // 更新股票信息
//         document.getElementById('stock-name').textContent = data.stock_name || '未知股票';
//
//         // 加载初始K线数据
//         if (data.kline_data && data.kline_data.length > 0) {
//             candlestickSeries.setData(data.kline_data);
//             volumeSeries.setData(data.volume_data);
//
//             // 加载移动平均线数据
//             if (data.ma_data) {
//                 maSeries[5].setData(data.ma_data[5] || []);
//                 maSeries[10].setData(data.ma_data[10] || []);
//                 maSeries[20].setData(data.ma_data[20] || []);
//             }
//
//             // 更新当前日期和价格信息
//             const currentBar = data.kline_data[data.kline_data.length - 1];
//             updateCurrentInfo(currentBar, data.progress);
//
//             // 加载交易标记
//             updateTradeMarkers(data.trade_markers || []);
//         }
//
//         // 加载技术指标
//         await loadTechnicalIndicator(currentIndicatorType);
//
//         updateAccountInfo();
//
//     } catch (error) {
//         console.error('加载初始数据失败:', error);
//         alert('加载数据失败');
//     }
// }
/**
 * 加载初始训练数据。
 * 包含一次自动重置和重试的容错逻辑。
 */
async function loadInitialData() {
    // 内部函数，用于执行实际的数据加载尝试
    const attemptToLoad = async () => {
        const maQuery = maPeriods.join(',');
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/data?ma_periods=${maQuery}&${getViewPeriodQuery()}`);
        if (!response.ok) {
            // 如果响应不成功，直接抛出错误，由外部的catch块处理
            throw new Error(`Server responded with status: ${response.status}`);
        }
        const data = await response.json();

        // 更新股票信息
        document.getElementById('stock-name').textContent = data.stock_name || '未知股票';
        applyTrainingSnapshot(data);

        // 加载技术指标
        await loadTechnicalIndicator(currentIndicatorType);

        updateAccountInfo();
    };

    try {
        // 第一次尝试加载数据
        await attemptToLoad();
    } catch (error) {
        console.error('初次加载初始数据失败:', error);
        console.log('正在尝试自动重置训练并重新加载...');

        try {
            // 自动重置训练
            const resetResponse = await fetch(`${API_BASE}/training/${currentTraining.id}/reset`, {
                method: 'POST'
            });

            if (!resetResponse.ok) {
                // 如果连重置都失败了，那就没有办法了
                throw new Error('自动重置训练失败，无法恢复。');
            }

            console.log('训练已成功重置，正在进行第二次加载尝试...');

            // 清理UI上的旧交易记录
            document.getElementById('trade-history').innerHTML = '<div class="no-trades">暂无交易记录</div>';

            // 第二次尝试加载数据
            await attemptToLoad();

            console.log('第二次加载成功！');

        } catch (finalError) {
            console.error('自动重置或第二次加载失败:', finalError);
            // 只有在重试也失败后，才向用户显示最终的错误提示
            alert('加载数据失败，请尝试重新开始一局训练。');

            // 加载失败后，最好将用户带回到主界面
            resetToMainAppState();
        }
    }
}

function updateCurrentInfo(barData, progress) {
    if (!barData) return;
    const palette = getThemePalette();

    const date = new Date(barData.time * 1000);
    const formattedDate = `${date.getFullYear()}/${(date.getMonth() + 1).toString().padStart(2, '0')}/${date.getDate().toString().padStart(2, '0')}`;
    document.getElementById('current-date').textContent = formattedDate;
    document.getElementById('current-price').textContent = `¥${barData.close.toFixed(2)}`;

    // 显示当前bar ID
    document.getElementById('current-bar-id').textContent = `Bar ID: ${barData.bar_id || 'N/A'}`;

    // 更新当日详情
    document.getElementById('open-price').textContent = `¥${barData.open.toFixed(2)}`;
    document.getElementById('high-price').textContent = `¥${barData.high.toFixed(2)}`;
    document.getElementById('low-price').textContent = `¥${barData.low.toFixed(2)}`;
    document.getElementById('close-price').textContent = `¥${barData.close.toFixed(2)}`;

    // 更新成交量
    if (barData.volume !== undefined) {
        let volText = barData.volume;
        if (volText >= 100000000) {
            volText = (volText / 100000000).toFixed(2) + '亿';
        } else if (volText >= 10000) {
            volText = (volText / 10000).toFixed(2) + '万';
        } else {
            volText = volText.toString();
        }
        document.getElementById('volume').textContent = volText;
    } else {
        document.getElementById('volume').textContent = `--`;
    }

    // 计算涨跌幅（优先使用后端的lastClose，其次退化到图表的前一根的数据）
    if (progress && progress.current_bar_id > 1) {
        let prevClose = barData.lastClose;
        if (prevClose === undefined) {
            // 如果后端没有传lastClose，则尝试从本地的K线图表获取最后第二根数据的收盘价
            const localData = latestRenderedKlineData;
            if (localData && localData.length >= 2) {
                prevClose = localData[localData.length - 2].close;
            }
        }
        
        if (prevClose !== undefined && prevClose > 0) {
            const changePercent = ((barData.close - prevClose) / prevClose * 100).toFixed(2);
            document.getElementById('change-percent').textContent = `${changePercent}%`;
            document.getElementById('change-percent').style.color = changePercent > 0 ? palette.positive : changePercent < 0 ? palette.negative : palette.neutral;
        } else {
            document.getElementById('change-percent').textContent = `--%`;
            document.getElementById('change-percent').style.color = palette.neutral;
        }
    } else {
        document.getElementById('change-percent').textContent = `--%`;
        document.getElementById('change-percent').style.color = palette.neutral;
    }

    // 更新进度信息
    if (progress) {
        document.getElementById('training-progress').textContent =
            `进度: ${progress.training_progress.toFixed(1)}% (${progress.current_bar_id}/${progress.total_bars - progress.preview_bars})`;
    }
}

// function updateTradeMarkers(markers) {
//     if (!tradeMarkerSeries || !markers) return;
//
//     const markerData = markers.map(marker => ({
//         time: marker.time,
//         position: marker.type === 'B' ? 'aboveBar' : 'belowBar',
//         color: marker.type === 'B' ? '#ff4d4f' : '#008000',
//         shape: marker.type === 'B' ? 'arrowDown' : 'arrowUp',
//         text: marker.type,
//         size: 1
//     }));
//
//     LightweightCharts.createSeriesMarkers(candlestickSeries, markerData);
// }
function updateTradeMarkers(markers, cooldownList, signalList) {
    if (!tradeMarkerSeries || !markers) return;

    // 1. 获取所有K线数据并构建一个以时间为键的Map，方便快速查找
    const allCandlestickData = latestRenderedKlineData;
    const candlestickMap = new Map();
    allCandlestickData.forEach(data => {
        candlestickMap.set(data.time, data);
    });

    const markerData = markers.map(marker => {
        const klineData = candlestickMap.get(marker.time);
        let shape;

        if (klineData) {
            // 判断K线是涨是跌
            const isKlineUp = klineData.close > klineData.open;

            if (isKlineUp) {
                // 在红K上：箭头朝下 (表示在K线顶部买卖)
                shape = 'arrowDown';
            } else {
                // 平盘K线，默认朝上
                shape = 'arrowUp';
            }

        } else {
            // 如果找不到对应的K线数据，使用默认形状
            shape = marker.type === 'B' ? 'arrowDown' : 'arrowUp';
        }

        return {
            time: marker.time,
            position: shape === 'arrowDown' ? 'aboveBar' : 'belowBar',
            color: marker.type === 'B' ? '#ff4d4f' : '#008000',
            shape: shape,
            text: marker.type,
            size: 1
        };
    });

    // 2. 清仓后的禁买期标记（橙色方块 + 剩余交易日）
    (cooldownList || []).forEach(item => {
        if (!item || !item.time) return;
        markerData.push({
            time: item.time,
            position: 'aboveBar',
            color: '#f59e0b',
            shape: 'square',
            text: item.remaining ? ('禁买' + item.remaining) : '禁买',
            size: 1
        });
    });

    // 3. 顶/底背离信号（箭头方向区别于买卖点方块类标记）
    (signalList || []).forEach(item => {
        if (!item || !item.time) return;
        markerData.push({
            time: item.time,
            position: item.position || (item.type === 'top_divergence' ? 'aboveBar' : 'belowBar'),
            color: item.color || (item.type === 'top_divergence' ? '#ff4d4f' : '#16a34a'),
            shape: item.shape || (item.type === 'top_divergence' ? 'arrowDown' : 'arrowUp'),
            text: item.text || (item.type === 'top_divergence' ? '顶背离' : '底背离'),
            size: 1
        });
    });

    markerData.sort((a, b) => a.time - b.time);

    // 3. 复用同一个 markers 插件，避免每次刷新重复叠加
    if (!tradeMarkersPlugin) {
        tradeMarkersPlugin = LightweightCharts.createSeriesMarkers(candlestickSeries, markerData);
    } else {
        tradeMarkersPlugin.setMarkers(markerData);
    }
}

// 回放控制
function togglePlayback() {
    if (isPlaying) {
        pausePlayback();
    } else {
        startPlayback();
    }
}

function startPlayback() {
    isPlaying = true;
    document.querySelector('.play-icon').classList.add('hidden');
    document.querySelector('.pause-icon').classList.remove('hidden');

    const speed = parseFloat(document.getElementById('playback-speed').value);
    const interval = speed * 1000;

    playbackInterval = setInterval(nextBar, interval);
}

function pausePlayback() {
    isPlaying = false;
    document.querySelector('.play-icon').classList.remove('hidden');
    document.querySelector('.pause-icon').classList.add('hidden');

    if (playbackInterval) {
        clearInterval(playbackInterval);
        playbackInterval = null;
    }
}

function updatePlaybackSpeed() {
    if (isPlaying) {
        pausePlayback();
        startPlayback();
    }
}

async function nextBar() {
    try {
        const previousLogicalRange = chart?.timeScale().getVisibleLogicalRange();
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/next`, {
            method: 'POST'
        });

        if (response.ok) {
            const data = await response.json();

            if (data.finished) {
                // 训练结束
                pausePlayback();
                showReport(data.report);
                return false;
            } else {
                // 更新图表数据
                if (data.new_bar) {
                    if (currentPeriod === 'weekly') {
                        await refreshTrainingView({ preserveRange: true });
                    } else {
                        candlestickSeries.update(data.new_bar);
                        upsertRenderedBar(data.new_bar);

                        if (data.requires_full_refresh) {
                            await updateAdjustment(shiftLogicalRange(previousLogicalRange, 1));
                        } else {
                            if (data.new_volume) {
                                volumeSeries.update(data.new_volume);
                            }

                            updateCurrentInfo(data.new_bar, data.progress);
                            if (currentTraining) {
                                currentTraining.latestProgress = data.progress || null;
                            }

                            if (data.progress && data.progress.current_bar_id !== undefined) {
                                lastKnownBarId = data.progress.current_bar_id;
                            }

                            await updateMovingAverages();
                            await loadTechnicalIndicator(currentIndicatorType);
                            await ensureIndicatorSeries();
                            setVisibleRangeAll(shiftLogicalRange(previousLogicalRange, 1));
                            await updateChipDistribution();
                        }
                    }

                    if (data.progress && data.progress.current_bar_id !== undefined) {
                        lastKnownBarId = data.progress.current_bar_id;
                    }
                }

                updateAccountInfo();

                // 禁买期标记 / 背离信号随新K线一起刷新
                if (data.cooldown_markers || data.signal_markers) {
                    if (data.cooldown_markers) cooldownMarkersData = data.cooldown_markers;
                    if (data.signal_markers) signalMarkersData = data.signal_markers;
                    try {
                        updateTradeMarkers(currentTraining?.tradeMarkers || [], cooldownMarkersData, signalMarkersData);
                    } catch (markerError) {
                        console.warn('刷新禁买期/背离标记失败:', markerError);
                    }
                }

                return true;
            }
        } else {
            const error = await response.json();
            console.error('获取下一根K线失败:', error);
            return false;
        }
    } catch (error) {
        console.error('获取下一根K线失败:', error);
        return false;
    }
}

async function updateMovingAverages() {
    try {
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/data?${getViewPeriodQuery()}`);
        const data = await response.json();

        if (data.ma_data) {
            // 只更新最新的数据点
            maPeriods.forEach(p => {
                const mData = data.ma_data[p];
                if (maSeries[p] && mData && mData.length > 0) {
                    maSeries[p].update(mData[mData.length - 1]);
                }
            });
        }
    } catch (error) {
        console.error('更新移动平均线失败:', error);
    }
}

async function loadTechnicalIndicator(indicatorType) {
    const visibleLogicalRange = chart.timeScale().getVisibleLogicalRange();
    try {
        // 获取DOM元素，并检查是否存在
        const indicatorChartElement = document.getElementById('indicator-chart');
        const indicatorCanvasElement = document.getElementById('indicator-canvas');
        const indicatorHeaderElement = document.getElementById('indicator-header');

        // 如果之前显示的是BOLL，先移除主图上的BOLL线
        if (bollSeries.upper) {
            chart.removeSeries(bollSeries.upper);
            chart.removeSeries(bollSeries.middle);
            chart.removeSeries(bollSeries.lower);
            bollSeries = {}; // 清空

            // 立即清除界面残留的 BOLL 标签
            const bollInfoEl = document.getElementById('boll-info-content');
            if (bollInfoEl) {
                bollInfoEl.remove();
            }
            
            renderChartLegend();
        }

        // 清除下方指标图表的所有现有系列
        if (currentIndicatorSeries.length > 0) {
            const staleSeries = currentIndicatorSeries;
            currentIndicatorSeries = []; // 先清空引用，避免异常时残留脏状态
            staleSeries.forEach(series => {
                try {
                    indicatorChart.removeSeries(series);
                } catch (e) {
                    // 图表重建后旧系列可能已失效，忽略即可，不能中断后续绘制
                    console.warn('移除旧指标系列失败（可忽略）:', e);
                }
            });
        }

        // 图表可能是在容器尺寸尚未稳定时创建的，这里按当前容器重新校正一次尺寸，
        // 否则指标图会缺少右侧价格轴、或线宽/高度错位
        if (indicatorChart && indicatorCanvasElement) {
            const w = indicatorCanvasElement.clientWidth;
            const h = indicatorCanvasElement.clientHeight;
            if (w > 0 && h > 0) {
                indicatorChart.resize(w, h);
            }
        }

        if (indicatorCanvasElement) {
            indicatorCanvasElement.style.display = (indicatorType === 'BOLL') ? 'none' : 'block';
        }
        if (indicatorChartElement) {
            indicatorChartElement.classList.toggle('indicator-collapsed', indicatorType === 'BOLL');
        }
        if (indicatorHeaderElement) {
            indicatorHeaderElement.style.display = 'block'; // 确保选择器总是可见
        }

        // 如果选择的是BOLL，则直接在主图上绘制并返回
        if (indicatorType === 'BOLL') {
            const response = await fetch(`${API_BASE}/training/${currentTraining.id}/indicators/BOLL?${getViewPeriodQuery()}`);
            const data = await response.json();
            if (data.type === 'BOLL' && data.data) {
                const upperData = data.data.map(item => ({ time: item.time, value: item.upper }));
                const middleData = data.data.map(item => ({ time: item.time, value: item.middle }));
                const lowerData = data.data.map(item => ({ time: item.time, value: item.lower }));

                // 在主图表(chart)上添加BOLL线
                bollSeries.upper = chart.addSeries(LightweightCharts.LineSeries, {
                    color: '#ff6b6b',
                    lineWidth: 2,
                    priceLineVisible: false,
                    crosshairMarkerVisible: false,
                    lastValueVisible: false
                });
                bollSeries.middle = chart.addSeries(LightweightCharts.LineSeries, {
                    color: '#4ecdc4',
                    lineWidth: 2,
                    priceLineVisible: false,
                    crosshairMarkerVisible: false,
                    lastValueVisible: false
                });
                bollSeries.lower = chart.addSeries(LightweightCharts.LineSeries, {
                    color: '#45b7d1',
                    lineWidth: 2,
                    priceLineVisible: false,
                    crosshairMarkerVisible: false,
                    lastValueVisible: false
                });

                bollSeries.upper.setData(upperData);
                bollSeries.middle.setData(middleData);
                bollSeries.lower.setData(lowerData);
                renderChartLegend();
            }
        } else {
            // --- 如果不是BOLL，则按原逻辑在下方图表绘制 ---
            const response = await fetch(`${API_BASE}/training/${currentTraining.id}/indicators/${indicatorType}?${getViewPeriodQuery()}`);
            const data = await response.json();

            // 根据指标类型创建新的系列 (此部分代码保持不变)
            if (data.type === 'MACD' && data.data) {
                const difData = data.data.map(item => ({ time: item.time, value: item.dif }));
                const deaData = data.data.map(item => ({ time: item.time, value: item.dea }));
                const histogramData = data.data.map(item => ({
                    time: item.time,
                    value: item.histogram,
                    color: item.histogram >= 0 ? '#ff4d4f' : '#008000'
                }));

                const difSeries = indicatorChart.addSeries(LightweightCharts.LineSeries, {
                    color: '#ff6b6b',
                    lineWidth: 1,
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false
                });
                const deaSeries = indicatorChart.addSeries(LightweightCharts.LineSeries, {
                    color: '#4ecdc4',
                    lineWidth: 1,
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false
                });
                const histogramSeries = indicatorChart.addSeries(LightweightCharts.HistogramSeries, {
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false
                });
                difSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
                deaSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
                histogramSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });

                currentIndicatorSeries.push(difSeries, deaSeries, histogramSeries);

                difSeries.setData(difData);
                deaSeries.setData(deaData);
                histogramSeries.setData(histogramData);
                renderIndicatorLegend();

            } else if (data.type === 'RSI' && data.data && data.periods) {
                const rsiColors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#f9c74f', '#90be6d', '#f8961e'];
                data.periods.forEach((period, index) => {
                    const rsiData = data.data.map(item => ({ time: item.time, value: item[`rsi${period}`] }));
                    const rsiSeries = indicatorChart.addSeries(LightweightCharts.LineSeries, {
                        color: rsiColors[index % rsiColors.length],
                        lineWidth: 1,
                        crosshairMarkerVisible: false,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    rsiSeries.rsiTitle = `RSI(${period})`;
                    currentIndicatorSeries.push(rsiSeries);
                    rsiSeries.setData(rsiData);
                    rsiSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
                });
                renderIndicatorLegend();

            } else if (data.type === 'KDJ' && data.data) {
                const kData = data.data.map(item => ({ time: item.time, value: item.k }));
                const dData = data.data.map(item => ({ time: item.time, value: item.d }));
                const jData = data.data.map(item => ({ time: item.time, value: item.j }));

                const kSeries = indicatorChart.addSeries(LightweightCharts.LineSeries, {
                    color: '#ff6b6b',
                    lineWidth: 1,
                    crosshairMarkerVisible: false
                });
                const dSeries = indicatorChart.addSeries(LightweightCharts.LineSeries, {
                    color: '#4ecdc4',
                    lineWidth: 1,
                    crosshairMarkerVisible: false
                });
                const jSeries = indicatorChart.addSeries(LightweightCharts.LineSeries, {
                    color: '#45b7d1',
                    lineWidth: 1,
                    crosshairMarkerVisible: false
                });
                kSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
                dSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
                jSeries.applyOptions({ lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });

                currentIndicatorSeries.push(kSeries, dSeries, jSeries);
                kSeries.setData(kData);
                dSeries.setData(dData);
                jSeries.setData(jData);
                renderIndicatorLegend();
            }
        }

    } catch (error) {
        console.error(`加载技术指标失败: ${error}`);
    } finally {
        // 2. 恢复之前保存的可见逻辑范围
        // 只有在范围有效时才恢复
        if (visibleLogicalRange !== null) {
            indicatorChart.timeScale().setVisibleLogicalRange(visibleLogicalRange);
        }
    }
}

function changeIndicator() {
    const select = document.getElementById('indicator-select');
    currentIndicatorType = select.value;
    loadTechnicalIndicator(currentIndicatorType);
}

/**
 * 保底自愈：如果指标面板里一个系列都没有（异常中断、图表重建后引用失效等），
 * 再补渲染一次，避免出现“有水印、无价格轴、无 DIF/DEA”的空面板
 */
async function ensureIndicatorSeries() {
    if (!indicatorChart) return;
    if (currentIndicatorType === 'BOLL') {
        if (!bollSeries.upper) await loadTechnicalIndicator(currentIndicatorType);
        return;
    }
    if (currentIndicatorSeries.length === 0) {
        console.warn('指标系列为空，触发一次自动重绘');
        await loadTechnicalIndicator(currentIndicatorType);
    }
}

// 复权设置
async function updateAdjustment(targetRange = null) {
    const checkedAdjustment = document.querySelector('input[name="adjustment"]:checked');
    const adjustment = checkedAdjustment ? checkedAdjustment.value : 'forward';

    const maQuery = maPeriods.join(',');
    try {
        const visibleRange = targetRange || chart.timeScale().getVisibleLogicalRange();
        
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/adjustment?ma_periods=${maQuery}&${getViewPeriodQuery()}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ adjustment })
        });

        if (response.ok) {
            const data = await response.json();
            applyTrainingSnapshot({
                ...data,
                progress: currentTraining?.latestProgress || null,
                trade_markers: currentPeriod === 'daily' ? (currentTraining?.tradeMarkers || []) : []
            });
            renderChartLegend();
            
            if (visibleRange !== null) {
                setVisibleRangeAll(visibleRange);
            }
            
            await updateChipDistribution();
        }
    } catch (error) {
        console.error('更新复权设置失败:', error);
    }
}

// 交易操作
// 当前可买 / 可卖的最大手数（由账户接口刷新）
let maxBuyLots = 0;
let maxSellLots = 0;

function limitTradePercent() {
    // 滑块只保留 11 档：0% / 10% / … / 100%，取整到最近的 10 的倍数
    ['buy', 'sell'].forEach((side) => {
        const input = document.getElementById(`${side}-percent`);
        if (!input) return;
        let value = parseFloat(input.value);
        if (isNaN(value)) value = 100;
        value = Math.round(value / 10) * 10;
        if (value < 0) value = 0;
        if (value > 100) value = 100;
        input.value = String(value);
    });
}

function getTradePercent(side = 'buy') {
    const input = document.getElementById(`${side}-percent`);
    if (!input) return 0;
    const value = parseFloat(input.value);
    if (isNaN(value) || value <= 0) return 0;
    // 只可能是 10 的倍数，这里再做一次兜底
    return Math.min(100, Math.max(0, Math.round(value / 10) * 10));
}

/**
 * 滑块联动：显示百分比与折算后的手数，拖动即更新（0% 表示不下单）
 */
function updateTradePercentHint(side) {
    const label = document.getElementById(`${side}-percent-value`);
    if (!label) return;
    const percent = getTradePercent(side);
    if (percent <= 0) {
        label.textContent = '0% · 不交易';
        return;
    }
    const lots = resolveTradeQuantity(percent, side);
    const maxLots = side === 'buy' ? maxBuyLots : maxSellLots;
    if (!maxLots || maxLots <= 0) {
        label.textContent = `${percent}%`;
        return;
    }
    label.textContent = `${percent}% · ${lots}手`;
}

/**
 * 把百分比换算成手数：买入按最大可买手数、卖出按最大可卖手数折算
 * 100% 直接取上限，避免取整损失
 */
function resolveTradeQuantity(percent, side) {
    if (!percent || percent <= 0) return 0;
    const maxLots = side === 'buy' ? maxBuyLots : maxSellLots;
    if (!maxLots || maxLots <= 0) return 0;
    if (percent >= 100) return maxLots;
    return Math.floor(maxLots * percent / 100);
}

async function executeBuy(priceType = 'close') {
    if (priceType === 'open') {
        const hasNext = await nextBar();
        if (!hasNext) {
            return; // 训练结束或出错
        }
    }

    const percent = getTradePercent('buy');
    if (!percent) {
        alert('买入比例是 0%：把滑块调到 10% 以上再买（100% = 用可用资金能买的最大手数）');
        return;
    }

    const quantity = resolveTradeQuantity(percent, 'buy');
    if (!quantity || quantity <= 0) {
        alert(`当前最多可买 ${maxBuyLots} 手，按 ${percent}% 折算不足 1 手，请调高比例或等资金更充裕时再买`);
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/trade`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                action: 'buy',
                quantity: quantity,
                price_type: priceType
            })
        });

        if (response.ok) {
            const result = await response.json();
            updateAccountInfo();
            addTradeRecord(result.trade);
            if (result.cooldown_markers) {
                cooldownMarkersData = result.cooldown_markers;
            }
            if (result.signal_markers) {
                signalMarkersData = result.signal_markers;
            }
            updateTradeMarkers(result.trade_markers, cooldownMarkersData, signalMarkersData);
            if (result.trade_markers) {
                lastKnownTradeCount = result.trade_markers.length;
            }
        } else {
            const error = await response.json();
            alert(error.message || '买入失败');
        }
    } catch (error) {
        console.error('买入失败:', error);
        alert('买入失败');
    }
}

async function executeSell(priceType = 'close') {
    if (priceType === 'open') {
        const hasNext = await nextBar();
        if (!hasNext) {
            return; // 训练结束或出错
        }
    }

    const percent = getTradePercent('sell');
    if (!percent) {
        alert('卖出比例是 0%：把滑块调到 10% 以上再卖（100% = 清掉可卖持仓）');
        return;
    }

    const quantity = resolveTradeQuantity(percent, 'sell');
    if (!quantity || quantity <= 0) {
        alert(`当前最多可卖 ${maxSellLots} 手，按 ${percent}% 折算不足 1 手（或无可用持仓）`);
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/trade`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                action: 'sell',
                quantity: quantity,
                price_type: priceType
            })
        });

        if (response.ok) {
            const result = await response.json();
            updateAccountInfo();
            addTradeRecord(result.trade);
            if (result.cooldown_markers) {
                cooldownMarkersData = result.cooldown_markers;
            }
            if (result.signal_markers) {
                signalMarkersData = result.signal_markers;
            }
            updateTradeMarkers(result.trade_markers, cooldownMarkersData, signalMarkersData);
        } else {
            const error = await response.json();
            alert(error.message || '卖出失败');
        }
    } catch (error) {
        console.error('卖出失败:', error);
        alert('卖出失败');
    }
}

// 账户信息更新
async function updateAccountInfo() {
    try {
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/account`);
        const account = await response.json();

        document.getElementById('total-assets').textContent = `¥${account.total_assets.toLocaleString()}`;
        document.getElementById('available-cash').textContent = `¥${account.available_cash.toLocaleString()}`;
        document.getElementById('position-value').textContent = `¥${account.position_value.toLocaleString()}`;
        document.getElementById('floating-pnl').textContent = `¥${account.floating_pnl.toLocaleString()}`;
        document.getElementById('floating-pnl').style.color = account.floating_pnl > 0 ? '#ff4d4f' : account.floating_pnl < 0 ? '#008000' : '#000000';

        // 更新最大可交易数量（同时缓存给百分比换算用）
        maxBuyLots = account.max_buyable_quantity || 0;
        document.getElementById('max-buy-quantity').textContent = maxBuyLots;
        if (account.position_summary) {
            maxSellLots = Math.floor((account.position_summary.available_shares || 0) / 100);
            document.getElementById('max-sell-quantity').textContent = maxSellLots;
        }
        else {
            maxSellLots = 0;
            document.getElementById('max-sell-quantity').textContent = '0';
        }
        updateTradePercentHint('buy');
        updateTradePercentHint('sell');

        // 更新持仓信息
        updatePositionInfo(account.position_summary);

        // 成本 / 止损 / 止盈辅助线
        updatePositionGuideLines(account.position_summary);

        // 同步拉取交易记录（解决 AI / 后台自动交易所缺失的面板历史记录）
        await updateTradeHistory();

    } catch (error) {
        console.error('更新账户信息失败:', error);
    }
}

// 获取并刷新整个交易历史列表
async function updateTradeHistory() {
    try {
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/trade_records`);
        if (!response.ok) return;
        const records = await response.json();
        
        const container = document.getElementById('trade-history');
        if (!records || records.length === 0) {
            container.innerHTML = '<div class="no-trades">暂无交易记录</div>';
            return;
        }

        container.innerHTML = '';
        // 倒序排列，新的在上面
        const displayRecords = records.reverse().slice(0, 10);
        
        displayRecords.forEach(trade => {
            const tradeItem = document.createElement('div');
            tradeItem.className = `trade-item ${trade.action}`;
            tradeItem.innerHTML = `
                <div class="trade-header">
                    <span class="trade-action">${trade.action === 'buy' ? '买入' : '卖出'}</span>
                    <span class="trade-time">${trade.trade_date}</span>
                </div>
                <div class="trade-details">
                    <div>Bar ID: ${trade.bar_id}</div>
                    <div>数量: ${trade.quantity} 手</div>
                    <div>价格: ¥${trade.price.toFixed(2)}</div>
                    <div>金额: ¥${trade.net_amount.toFixed(2)}</div>
                </div>
            `;
            container.appendChild(tradeItem);
        });
    } catch (e) {
        console.error('获取交易历史失败', e);
    }
}

// 自动同步状态
function startAutoSync() {
    if (autoSyncInterval) clearInterval(autoSyncInterval);
    lastKnownBarId = null;
    lastKnownTradeCount = null;

    autoSyncInterval = setInterval(async () => {
        if (!currentTraining || isPlaying) return;

        const isTrainingInterfaceVisible = !document.getElementById('training-interface').classList.contains('hidden');
        if (!isTrainingInterfaceVisible) return;

        try {
            const resp = await fetch(`${API_BASE}/training/${currentTraining.id}/sync_status`);
            if (resp.status === 404) {
                stopAutoSync();
                return;
            }
            if (resp.ok) {
                const data = await resp.json();
                let needsRefresh = false;

                if (lastKnownBarId !== null && data.current_bar_id !== lastKnownBarId) {
                    needsRefresh = true;
                }
                if (lastKnownTradeCount !== null && data.trade_markers_count !== lastKnownTradeCount) {
                    needsRefresh = true;
                }

                if (needsRefresh) {
                    await loadInitialData();
                }

                lastKnownBarId = data.current_bar_id;
                lastKnownTradeCount = data.trade_markers_count;
            }
        } catch (e) { }
    }, 500);
}

function stopAutoSync() {
    if (autoSyncInterval) {
        clearInterval(autoSyncInterval);
        autoSyncInterval = null;
    }
}

function updatePositionInfo(positionSummary) {
    const container = document.getElementById('current-positions');

    if (!positionSummary || positionSummary.total_shares === 0) {
        container.innerHTML = '<div class="no-positions">暂无持仓</div>';
        return;
    }

    container.innerHTML = `
        <div class="position-summary">
            <div class="position-item">
                <span>总持股:</span>
                <span>${(positionSummary.total_shares / 100).toFixed(2).toLocaleString()} 手</span>
            </div>
            <div class="position-item">
                <span>可卖:</span>
                <span>${(positionSummary.available_shares / 100).toFixed(2).toLocaleString()} 手</span>
            </div>
            <div class="position-item">
                <span>成本价:</span>
                <span>¥${positionSummary.average_cost.toFixed(2)}</span>
            </div>
            <div class="position-item">
                <span>现价:</span>
                <span>¥${positionSummary.current_price.toFixed(2)}</span>
            </div>
            <div class="position-item">
                <span>盈亏:</span>
                <span class="${positionSummary.pnl_percent >= 0 ? 'positive' : 'negative'}">${positionSummary.pnl_percent.toFixed(2)}%</span>
            </div>
        </div>
    `;
}

function addTradeRecord(trade) {
    // 改为直接调用全量更新
    updateTradeHistory();
}

// 成本 / 止损 / 止盈辅助线
const POSITION_GUIDE_DEFAULT_STOP = 10;
const POSITION_GUIDE_DEFAULT_TAKE = 20;
let positionGuidePrices = { cost: null, stop: null, take: null };

/**
 * 让价格轴范围包含辅助线，否则止损/止盈线会落在可视区间外而看不见
 */
function buildAutoscaleProvider() {
    return function (original) {
        const info = original();
        if (!info || !info.priceRange) return info;
        const prices = positionGuidePrices;
        if (!prices || (prices.cost === null && prices.stop === null && prices.take === null)) {
            return info;
        }
        let minValue = info.priceRange.minValue;
        let maxValue = info.priceRange.maxValue;
        [prices.stop, prices.cost, prices.take].forEach(p => {
            if (p === null || p === undefined || !isFinite(p)) return;
            if (p < minValue) minValue = p;
            if (p > maxValue) maxValue = p;
        });
        info.priceRange = { minValue: minValue, maxValue: maxValue };
        return info;
    };
}

function refreshAutoscale() {
    if (!candlestickSeries) return;
    try {
        candlestickSeries.applyOptions({ autoscaleInfoProvider: buildAutoscaleProvider() });
    } catch (e) {
        console.warn('刷新价格轴范围失败:', e);
    }
}

function clearPositionGuideLines() {
    positionGuidePrices = { cost: null, stop: null, take: null };
    if (!candlestickSeries) {
        positionGuideLines = { cost: null, stop: null, take: null };
        return;
    }
    ['cost', 'stop', 'take'].forEach(key => {
        if (positionGuideLines[key]) {
            try {
                candlestickSeries.removePriceLine(positionGuideLines[key]);
            } catch (e) {
                console.warn('移除辅助线失败:', e);
            }
            positionGuideLines[key] = null;
        }
    });
    refreshAutoscale();
}

function getGuidePercent(inputId, fallback) {
    const el = document.getElementById(inputId);
    const value = el ? parseFloat(el.value) : NaN;
    if (isNaN(value) || value < 0) return fallback;
    return value;
}

/**
 * 根据持仓成本绘制 成本线 / 止损线 / 止盈线
 * @param {object|null} positionSummary 账户接口返回的 position_summary
 */
function updatePositionGuideLines(positionSummary) {
    if (!candlestickSeries) return;

    const shares = positionSummary ? Number(positionSummary.total_shares || 0) : 0;
    const cost = positionSummary ? Number(positionSummary.average_cost || 0) : 0;
    if (!shares || !cost || isNaN(cost)) {
        clearPositionGuideLines();
        return;
    }

    const stopPct = getGuidePercent('stop-loss-percent', POSITION_GUIDE_DEFAULT_STOP);
    const takePct = getGuidePercent('take-profit-percent', POSITION_GUIDE_DEFAULT_TAKE);
    const stopPrice = stopPct > 0 ? cost * (1 - stopPct / 100) : null;
    const takePrice = takePct > 0 ? cost * (1 + takePct / 100) : null;

    positionGuidePrices = { cost: cost, stop: stopPrice, take: takePrice };

    const guides = [
        {
            key: 'cost',
            enabled: true,
            price: cost,
            color: 'rgba(107, 114, 128, 0.9)',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            title: `成本 ${cost.toFixed(2)}`
        },
        {
            key: 'stop',
            enabled: stopPrice !== null,
            price: stopPrice,
            color: 'rgba(229, 72, 77, 0.9)',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            title: stopPrice === null ? '' : `止损 -${stopPct}% ${stopPrice.toFixed(2)}`
        },
        {
            key: 'take',
            enabled: takePrice !== null,
            price: takePrice,
            color: 'rgba(27, 154, 100, 0.9)',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            title: takePrice === null ? '' : `止盈 +${takePct}% ${takePrice.toFixed(2)}`
        }
    ];

    guides.forEach(guide => {
        if (!guide.enabled) {
            if (positionGuideLines[guide.key]) {
                try {
                    candlestickSeries.removePriceLine(positionGuideLines[guide.key]);
                } catch (e) {
                    console.warn('移除辅助线失败:', e);
                }
                positionGuideLines[guide.key] = null;
            }
            return;
        }
        const options = {
            price: guide.price,
            color: guide.color,
            lineWidth: guide.lineWidth,
            lineStyle: guide.lineStyle,
            axisLabelVisible: true,
            title: guide.title
        };
        if (positionGuideLines[guide.key]) {
            positionGuideLines[guide.key].applyOptions(options);
        } else {
            positionGuideLines[guide.key] = candlestickSeries.createPriceLine(options);
        }
    });

    refreshAutoscale();
}

// 训练控制

/**
 * 强制平仓函数
 * 会持续尝试卖出所有持仓，直到持仓清空。
 * 如果当天有T+1限制，会自动进入下一天再尝试。
 * @returns {Promise<boolean>} - 返回一个Promise，成功清仓则resolve(true)，否则resolve(false)。
 */
async function forceLiquidatePosition() {
    console.log("开始执行强制平仓流程...");

    // 设置一个最大尝试天数，防止无限循环
    const maxAttempts = 10;
    let attempts = 0;

    while (attempts < maxAttempts) {
        try {
            // 1. 获取最新的账户信息
            const accountResponse = await fetch(`${API_BASE}/training/${currentTraining.id}/account`);
            if (!accountResponse.ok) {
                alert('强制平仓失败：无法获取账户信息。');
                return false;
            }
            const account = await accountResponse.json();

            const totalShares = account.position_summary?.total_shares || 0;
            const availableShares = account.position_summary?.available_shares || 0;

            // 2. 如果持仓已清空，则成功退出循环
            if (totalShares === 0) {
                console.log("持仓已全部清空。");
                return true;
            }

            // 3. 如果有可卖的股票，就卖掉它们
            if (availableShares > 0) {
                console.log(`检测到可卖持仓 ${availableShares} 股，正在执行卖出...`);
                const sellQuantity = Math.floor(availableShares / 100); // 转换为“手”

                const sellResponse = await fetch(`${API_BASE}/training/${currentTraining.id}/trade`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'sell', quantity: sellQuantity })
                });

                if (!sellResponse.ok) {
                    const error = await sellResponse.json();
                    alert(`强制卖出部分持仓失败: ${error.message}`);
                    return false;
                }

                const result = await sellResponse.json();
                updateAccountInfo();
                addTradeRecord(result.trade);
                if (result.cooldown_markers) {
                    cooldownMarkersData = result.cooldown_markers;
                }
                if (result.signal_markers) {
                    signalMarkersData = result.signal_markers;
                }
                updateTradeMarkers(result.trade_markers, cooldownMarkersData, signalMarkersData);
                console.log(`成功卖出 ${sellQuantity} 手。`);

                // 卖出后再次检查，如果已经全部卖完，直接成功返回
                if (account.position_summary.total_shares - availableShares === 0) {
                    console.log("持仓已全部清空。");
                    return true;
                }
            }

            // 4. 如果还有持仓但当天不可卖，则进入下一天
            console.log("当天有T+1限制或已无更多可卖股票，进入下一个交易日...");
            await nextBar(); // 调用 nextBar 进入下一天

            // 增加一个小的延时，等待UI和后端状态更新
            await new Promise(resolve => setTimeout(resolve, 100));

        } catch (error) {
            console.error('强制平仓过程中发生错误:', error);
            alert('强制平仓过程中发生错误，请检查控制台。');
            return false;
        }
        attempts++;
    }

    alert('强制平仓失败：已超过最大尝试天数，仍有持仓未卖出。');
    return false;
}

async function endTraining() {
    // 1. 首先获取当前账户状态，检查是否有持仓
    const accountResponse = await fetch(`${API_BASE}/training/${currentTraining.id}/account`);
    if (!accountResponse.ok) {
        alert('无法获取账户信息，结束训练失败。');
        return;
    }
    const account = await accountResponse.json();
    const hasPosition = account.position_summary?.total_shares > 0;

    // 2. 如果有持仓，进行二次确认
    if (hasPosition) {
        if (!confirm('您当前仍有持仓，系统将自动为您强制平仓。确定要结束训练吗？')) {
            return; // 用户取消，则不执行任何操作
        }

        // 用户确认，开始强制平仓流程
        const liquidationSuccess = await forceLiquidatePosition();

        // 如果平仓失败，则中止结束流程
        if (!liquidationSuccess) {
            alert('自动平仓失败，无法结束训练。请手动处理或重置训练。');
            return;
        }
    }
    // 如果没有持仓，或者平仓成功后，继续执行原来的结束逻辑
    else {
        // 对于没有持仓的情况，也进行一次确认
        if (!confirm('确定要结束当前训练吗？')) {
            return;
        }
    }

    // 3. 所有持仓已清空，正式调用后端的 end 接口
    try {
        console.log("所有持仓已清空，正在生成最终报告...");
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/end`, {
            method: 'POST'
        });

        if (response.ok) {
            const report = await response.json();
            pausePlayback();
            showReport(report);
        } else {
            const error = await response.json();
            alert(`结束训练失败: ${error.message}`);
        }
    } catch (error) {
        console.error('结束训练失败:', error);
        alert('结束训练失败');
    }
}

async function resetTraining() {
    if (!confirm('确定要重置当前训练吗？所有交易记录将被清除。')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/training/${currentTraining.id}/reset`, {
            method: 'POST'
        });

        if (response.ok) {
            pausePlayback();
            await loadInitialData();

            // 清除交易记录显示
            document.getElementById('trade-history').innerHTML = '<div class="no-trades">暂无交易记录</div>';
        }
    } catch (error) {
        console.error('重置训练失败:', error);
        alert('重置训练失败');
    }
}

/**
 * 更新报告摘要区域的辅助函数
 * @param {HTMLElement} parentElement - 父容器元素
 * @param {object} report - 报告数据对象
 */
function updateReportSummary(parentElement, report) {
    // 使用 Map 定义标签和对应的值，更易于管理
    const summaryItems = new Map([
        ['股票代码:', report.stock_code],
        ['训练期间:', `${report.start_date} 至 ${report.end_date}`],
        ['初始资金:', `¥${report.initial_capital.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`],
        ['最终资产:', `¥${report.final_capital.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`],
        ['总交易次数:', `${report.total_trades} 次`],
        ['交易胜率:', `${(report.trade_win_rate || 0).toFixed(2)}%`],
        ['最大回撤:', `${(report.max_drawdown || 0).toFixed(2)}%`]
    ]);

    parentElement.innerHTML = `
        <h3>训练总结</h3>
        <div class="summary-grid"></div>
    `;
    const grid = parentElement.querySelector('.summary-grid');

    // 循环创建摘要项
    summaryItems.forEach((value, label) => {
        const item = document.createElement('div');
        item.className = 'summary-item';
        item.innerHTML = `<span class="label">${label}</span><span class="value">${value}</span>`;
        grid.appendChild(item);
    });

    // 处理需要额外逻辑的摘要项
    const totalReturnItem = document.createElement('div');
    totalReturnItem.className = 'summary-item';
    totalReturnItem.innerHTML = `
        <span class="label">总收益率:</span>
        <span class="value ${report.total_return >= 0 ? 'positive' : 'negative'}">
            ${report.total_return.toFixed(2)}%
        </span>`;
    grid.appendChild(totalReturnItem);
}


/**
 * 创建并填充交易明细表格的辅助函数
 * @param {HTMLElement} parentElement - 父容器元素
 * @param {Array} tradeDetails - 交易明细数组
 */
function createTradeDetailsTable(parentElement, tradeDetails) {
    parentElement.innerHTML = `
        <h3>交易明细</h3>
        <div class="trade-details-table">
            <table>
                <thead>
                    <tr>
                        <th>Bar</th>
                        <th>日期</th>
                        <th>操作</th>
                        <th>价格</th>
                        <th>数量</th>
                        <th>金额</th>
                        <th>税费</th>
                        <th>净金额</th>
                    </tr>
                </thead>
                <tbody></tbody>
                <tfoot></tfoot>
            </table>
        </div>
    `;

    const tbody = parentElement.querySelector('tbody');
    const tfoot = parentElement.querySelector('tfoot');

    // 初始化合计数据
    const totals = {
        totalAmount: 0,
        totalCommission: 0,
        totalProfit: 0,
    };

    // 动态创建表格行
    tradeDetails.forEach(trade => {
        const row = tbody.insertRow(); // 创建新行

        const isBuy = trade.action === 'buy';
        const totalFee = trade.commission + trade.stamp_tax;
        const profit = isBuy ? -(trade.amount + totalFee) : (trade.amount - totalFee);

        // 填充单元格
        row.innerHTML = `
            <td>${trade.bar_id}</td>
            <td>${trade.date}</td>
            <td class="${trade.action}">${isBuy ? '买入' : '卖出'}</td>
            <td>¥${trade.price.toFixed(2)}</td>
            <td>${trade.quantity}</td>
            <td>${isBuy ? '-' : ''}¥${trade.amount.toFixed(2)}</td>
            <td>-¥${totalFee.toFixed(2)}</td>
            <td>${profit >= 0 ? '¥' : '-¥'}${Math.abs(profit).toFixed(2)}</td>
        `;

        // 累加合计值
        if (!isBuy) {
            totals.totalAmount += trade.amount;
        }
        else {
            totals.totalAmount -= trade.amount;
        }
        totals.totalProfit += profit;
        totals.totalCommission += totalFee;
    });

    // 创建并插入合计行
    const totalRow = tfoot.insertRow();
    totalRow.className = 'total-row'; // 添加样式类以便高亮
    totalRow.innerHTML = `
        <td colspan="5"><strong>合计</strong></td>
        <td><strong>¥${totals.totalAmount.toFixed(2)}</strong></td>
        <td><strong>-¥${totals.totalCommission.toFixed(2)}</strong></td>
        <td><strong>${totals.totalProfit >= 0 ? '¥' : '-¥'}${Math.abs(totals.totalProfit).toFixed(2)}</strong></td>
    `;
}


/**
 * 请求 AI 智能复盘点评
 */
async function requestAIAnalysis(force = false) {
    const aiBtn = document.getElementById('ai-analyze-btn');
    const originalText = aiBtn ? aiBtn.innerHTML : '';

    if (force) {
        const ok = confirm('重新生成会用当前提示词再调用一次模型，消耗一次 token。\n如果只是想看之前的复盘，直接点历史记录即可（不会调用模型）。\n\n继续重新生成吗？');
        if (!ok) return;
    }
    
    try {
        if (aiBtn) {
            aiBtn.disabled = true;
            aiBtn.innerHTML = '⏳ 正在请求AI分析，请稍候...';
        }
        
        const response = await fetch(`${API_BASE}/training/analyze_report`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                report: currentReportData,
                user: currentUser,
                force: !!force
            })
        });

        if (response.ok) {
            const result = await response.json();

            renderAICommentarySection(result.ai_commentary, !!result.cached);
            // 点评已写入历史库，刷新列表上的“已存 AI 点评”标记
            loadTrainingHistory();
            // 结构化点评也落盘了，重新拉一遍让曲线上的标记可用
            if (currentReportData && currentReportData.session_id) {
                loadFillReviewsForReport(currentReportData);
            }

            // Hide the button since we got the result
            if (aiBtn) aiBtn.classList.add('hidden');
        } else {
            const error = await response.json();
            alert(`AI 分析失败: ${error.error || '未知错误'}`);
        }
    } catch (error) {
        console.error('AI 分析请求失败:', error);
        alert('网络请求失败，请检查服务连接。');
    } finally {
        if (aiBtn) {
            aiBtn.disabled = false;
            aiBtn.innerHTML = originalText;
        }
    }
}

/**
 * 复盘：全程K线 + 同步时间轴的收益曲线（线性/对数可切换）
 */
let reportPriceChart = null;
let reportEquityChart = null;
let reportEquitySeries = null;
let reportEquityIsLog = false;
let reportChartSyncing = false;

function disposeReportCharts() {
    [reportPriceChart, reportEquityChart].forEach((instance) => {
        if (!instance) return;
        try { instance.remove(); } catch (e) { /* 忽略已销毁的实例 */ }
    });
    reportPriceChart = null;
    reportEquityChart = null;
    reportEquitySeries = null;
}

function applyEquityScaleMode(isLog) {
    reportEquityIsLog = !!isLog;
    if (reportEquityChart) {
        try {
            reportEquityChart.priceScale('right').applyOptions({ mode: isLog ? 1 : 0 });
        } catch (e) {
            console.error('切换收益曲线坐标失败:', e);
        }
    }
    const linearBtn = document.getElementById('equity-scale-linear');
    const logBtn = document.getElementById('equity-scale-log');
    if (linearBtn && logBtn) {
        linearBtn.classList.toggle('active', !isLog);
        logBtn.classList.toggle('active', isLog);
    }
    if (typeof frScheduleRender === 'function') frScheduleRender();
}

function renderReportCharts(report) {
    const section = document.getElementById('report-chart-section');
    if (!section) return;

    const kline = (report && report.kline_series) || [];
    const curve = (report && report.equity_curve) || [];
    if (!kline.length || !curve.length) {
        section.classList.add('hidden');
        disposeReportCharts();
        return;
    }

    section.classList.remove('hidden');
    disposeReportCharts();

    const priceEl = document.getElementById('report-price-chart');
    const equityEl = document.getElementById('report-equity-chart');
    const palette = getThemePalette();

    const baseOptions = {
        layout: {
            background: { type: 'solid', color: palette.chartBg },
            textColor: palette.text,
        },
        grid: {
            vertLines: { color: palette.grid },
            horzLines: { color: palette.grid },
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: palette.border, minimumWidth: 76 },
        timeScale: {
            borderColor: palette.border,
            timeVisible: true,
            secondsVisible: false,
        },
    };

    reportPriceChart = LightweightCharts.createChart(priceEl, {
        ...baseOptions,
        width: priceEl.clientWidth,
        height: 280,
    });
    const priceSeries = reportPriceChart.addSeries(LightweightCharts.CandlestickSeries, {
        upColor: 'rgba(255, 77, 79, 0)',
        downColor: palette.negative,
        borderUpColor: palette.positive,
        borderDownColor: palette.negative,
        wickUpColor: palette.positive,
        wickDownColor: palette.negative,
        borderVisible: true,
    });
    priceSeries.setData(kline.map((row) => ({
        time: row.time,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
    })));

    // 买卖点标记
    const timeByBarId = {};
    kline.forEach((row) => { timeByBarId[row.bar_id] = row.time; });
    const markers = (report.trade_details || [])
        .filter((trade) => timeByBarId[trade.bar_id] !== undefined)
        .map((trade) => ({
            time: timeByBarId[trade.bar_id],
            position: trade.action === 'buy' ? 'belowBar' : 'aboveBar',
            color: trade.action === 'buy' ? palette.positive : palette.negative,
            shape: trade.action === 'buy' ? 'arrowUp' : 'arrowDown',
            text: `${trade.action === 'buy' ? '买' : '卖'}${trade.quantity}手`,
        }));
    if (markers.length && LightweightCharts.createSeriesMarkers) {
        LightweightCharts.createSeriesMarkers(priceSeries, markers);
    }

    reportEquityChart = LightweightCharts.createChart(equityEl, {
        ...baseOptions,
        width: equityEl.clientWidth,
        height: 180,
        rightPriceScale: { borderColor: palette.border, minimumWidth: 76, scaleMargins: { top: 0.12, bottom: 0.12 } },
        timeScale: { ...baseOptions.timeScale, visible: true },
        // 收益曲线的缩放/平移只跟随上方 K 线图，避免两条时间轴互相驱动
        handleScroll: false,
        handleScale: false,
    });
    reportEquitySeries = reportEquityChart.addSeries(LightweightCharts.LineSeries, {
        color: '#1d6fdc',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
        title: '净值指数',
    });
    reportEquitySeries.setData(curve.map((point) => ({
        time: point.time,
        value: point.equity_index,
    })));
    try {
        reportEquitySeries.createPriceLine({
            price: 100,
            color: palette.border,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: '初始资金',
        });
    } catch (e) {
        console.warn('初始资金基准线绘制失败:', e);
    }

    // 两条时间轴联动
    const link = (from, to) => {
        if (!from || !to) return;
        try {
            from.timeScale().subscribeVisibleLogicalRangeChange((range) => {
                if (!range || reportChartSyncing) return;
                reportChartSyncing = true;
                try { to.timeScale().setVisibleLogicalRange(range); } catch (e) { /* 忽略 */ }
                reportChartSyncing = false;
            });
        } catch (e) {
            console.warn('时间轴联动失败:', e);
        }
    };
    // 时间轴联动：K 线图单向驱动收益曲线（鼠标缩放/平移都在 K 线图上操作）
    link(reportPriceChart, reportEquityChart);

    // 缩放/拖动后重算点评标记位置
    try {
        reportEquityChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            frScheduleRender();
        });
    } catch (e) { /* 忽略，标记层会退化为不刷新 */ }

    try {
        reportPriceChart.timeScale().fitContent();
        reportEquityChart.timeScale().fitContent();
    } catch (e) { /* 忽略 */ }

    applyEquityScaleMode(reportEquityIsLog);

    // V2.3：成交事实标记 + 重点交易深度面板接到收益曲线上
    loadFillReviewsForReport(report);
}

/* ============================================================
 * V2.3 曲线交易事实 + 重点交易深度点评
 * 买红 #e25555 / 卖绿 #1b9a64 / 重点金 #f0be3c
 * 普通买卖标记只呈现成交事实（不含任何 AI 评价）；
 * AI 只对完整交易周期做深度点评，面板独立于 180px 曲线容器。
 * ============================================================ */
let frState = {
    token: 0,
    report: null,
    sessionId: '',
    fills: [],
    keys: [],
    clusters: [],
    available: false,
    hasAi: false,
    coverage: null,
    errors: [],
    loading: false,
    activeKey: null,        // 当前打开的事实卡片（bar_id|side）
    activeCycle: null,      // 当前打开的重点交易周期
    anchor: null,
    baseTimeIndex: null,
};
let frFrame = 0;

function frSessionIdOf(report) {
    if (!report) return '';
    if (report.session_id) return report.session_id;
    if (typeof currentTraining !== 'undefined' && currentTraining && currentTraining.id) return currentTraining.id;
    return '';
}

function frReportIndex(report) {
    const barTime = {};
    const timeEquity = {};
    ((report && report.kline_series) || []).forEach((row) => {
        if (row && row.bar_id !== undefined && row.bar_id !== null) {
            barTime[String(row.bar_id)] = row.time;
        }
    });
    ((report && report.equity_curve) || []).forEach((p) => {
        if (p && p.time !== undefined) timeEquity[String(p.time)] = p.equity_index;
    });
    return { barTime: barTime, timeEquity: timeEquity };
}

function frBarTimeOf(barId) {
    const idx = frState.baseTimeIndex;
    if (!idx || !idx.barTime) return '';
    const v = idx.barTime[String(barId)];
    if (typeof v === 'string') {
        // 字符串时间：'YYYY-MM-DD HH:MM' 或 'YYYY-MM-DDTHH:MM'
        const m = v.match(/[ T](\d{2}):(\d{2})/);
        return m ? m[1] + ':' + m[2] : '';
    }
    if (typeof v !== 'number') return '';
    const d = new Date(v * 1000);
    // 时间戳是数据源的 UTC 零点时说明是日线/周线：不显示假的盘中时间
    const hh = d.getUTCHours();
    const mm = d.getUTCMinutes();
    if (hh === 0 && mm === 0) return '';
    return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
}

function frReset(report) {
    frState.token += 1;
    frState.report = report || null;
    frState.sessionId = frSessionIdOf(report || {});
    frState.fills = [];
    frState.keys = [];
    frState.clusters = [];
    frState.available = false;
    frState.hasAi = false;
    frState.coverage = null;
    frState.errors = [];
    frState.loading = false;
    frState.activeKey = null;
    frState.activeCycle = null;
    frState.baseTimeIndex = null;
    frCloseCard();
    frCloseKeyPanel();
    const overlay = document.getElementById('fill-review-overlay');
    if (overlay) overlay.innerHTML = '';
    frSetNotice('');
    document.getElementById('fill-review-panel')?.classList.add('hidden');
}

function frSetNotice(text, tone) {
    const el = document.getElementById('fill-review-notice');
    if (!el) return;
    if (!text) {
        el.classList.add('hidden');
        el.textContent = '';
        el.dataset.tone = '';
        return;
    }
    el.textContent = text;
    el.dataset.tone = tone || 'info';
    el.classList.remove('hidden');
}

async function loadFillReviewsForReport(report) {
    frReset(report);
    if (!report) return;
    const sid = frState.sessionId;
    const user = currentUser || localStorage.getItem('currentUser');
    if (!sid || !user) {
        frSetNotice('这次复盘没有可用的会话编号，无法定位成交位置。');
        return;
    }
    const token = frState.token;
    frState.loading = true;
    try {
        const resp = await fetch(`${API_BASE}/users/${encodeURIComponent(user)}/history/${encodeURIComponent(sid)}/fill-reviews`);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        if (token !== frState.token) return; // 用户已切到别的报告

        frState.fills = (data.fills || []).map((f) => ({ ...f, side: String(f.side || '').toLowerCase() }));
        frState.keys = data.key_trade_reviews || [];
        frState.available = !!data.available;
        frState.hasAi = !!data.has_ai_analysis;
        frState.coverage = data.coverage || null;
        frState.errors = data.errors || [];

        const idx = frReportIndex(report);
        frState.baseTimeIndex = idx;
        frState.clusters = frBuildClusters(frState.fills, idx);

        document.getElementById('fill-review-panel')?.classList.remove('hidden');
        frRenderOverlay();
        frUpdateNotice();
    } catch (e) {
        if (token !== frState.token) return;
        frSetNotice('读取成交记录失败：' + e.message + '（曲线上的买卖事实仍以报告成交数据为准）', 'warn');
    } finally {
        if (token === frState.token) frState.loading = false;
    }
}

function frUpdateNotice() {
    const fs = frState;
    const cov = fs.coverage || {};
    if (!fs.hasAi) {
        frSetNotice('本次复盘还没有 AI 点评。买卖标记仍可查看每一笔实际成交的日期、价格、数量与持仓变化；生成 AI 点评后才会出现金色重点交易深度点评。', 'info');
        return;
    }
    if (!fs.keys.length) {
        frSetNotice('本轮 AI 没有选出达到深评标准的重点交易。只对完整交易周期做深度点评，小仓位试错、普通止盈与常规减仓不单独点评。', 'info');
        return;
    }
    let text = '本轮精选 ' + fs.keys.length + ' 笔重点交易，点金色星标查看整周期深度点评；其余成交只在曲线上标注事实位置。';
    if (cov.trades && cov.used_trades && cov.trades > cov.used_trades) {
        text += '本轮共 ' + cov.trades + ' 笔成交，按 150 笔上限只把前 ' + cov.used_trades + ' 笔送给模型，其余 ' + (cov.skipped_trades || 0) + ' 笔不在 AI 分析范围内。';
    }
    frSetNotice(text, 'info');
}

function frBuildClusters(fills, idx) {
    const groups = {};
    fills.forEach((f) => {
        const key = `${f.bar_id}|${f.side}`;
        if (!groups[key]) {
            groups[key] = { key: key, barId: f.bar_id, side: f.side, cycle: f.trade_cycle_id, fills: [] };
        }
        groups[key].fills.push(f);
    });
    const list = Object.values(groups).sort((a, b) => Number(a.barId) - Number(b.barId));
    list.forEach((c) => {
        c.time = idx.barTime[String(c.barId)];
        c.equity = c.time !== undefined ? idx.timeEquity[String(c.time)] : undefined;
    });
    return list;
}

function frProject(cluster) {
    if (!reportEquityChart || !reportEquitySeries) return null;
    if (cluster.time === undefined || cluster.equity === undefined) return null;
    let x; let y;
    try {
        x = reportEquityChart.timeScale().timeToCoordinate(cluster.time);
        y = reportEquitySeries.priceToCoordinate(cluster.equity);
    } catch (e) {
        return null;
    }
    if (x === null || x === undefined || y === null || y === undefined) return null;
    if (!isFinite(x) || !isFinite(y)) return null;
    return { x: x, y: y };
}

function frDisplayGroups() {
    const groups = [];
    const placed = [];
    frState.clusters.forEach((c) => {
        const pos = frProject(c);
        if (!pos) return;
        const existing = placed.find((g) => g.side === c.side && Math.abs(g.x - pos.x) < 44);
        if (existing) {
            existing.fills = existing.fills.concat(c.fills);
            existing.clusters.push(c);
            return;
        }
        const g = { key: c.key, side: c.side, x: pos.x, y: pos.y, fills: c.fills.slice(), clusters: [c] };
        placed.push(g);
        groups.push(g);
    });
    return groups;
}

function frRenderOverlay() {
    const overlay = document.getElementById('fill-review-overlay');
    if (!overlay) return;
    overlay.innerHTML = '';
    const fs = frState;
    if (!fs.report) return;
    if (!reportEquityChart || !reportEquitySeries) return;
    if (!fs.clusters.length) return;

    const groups = frDisplayGroups();
    groups.forEach((g) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        const isBuy = g.side === 'buy';
        btn.className = 'fr-marker ' + (isBuy ? 'fr-marker-buy' : 'fr-marker-sell') + (g.fills.length > 1 ? ' fr-marker-cluster' : '');
        btn.dataset.key = g.key;
        btn.title = isBuy ? '点击查看这一笔买入的成交事实' : '点击查看这一笔卖出的成交事实';
        btn.textContent = `${isBuy ? '▲ 买' : '▼ 卖'}${g.fills.length > 1 ? '×' + g.fills.length : ''}`;
        btn.style.left = g.x + 'px';
        btn.style.top = (isBuy ? g.y - 6 : g.y + 6) + 'px';
        btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            const card = document.getElementById('fill-review-card');
            if (frState.activeKey === g.key && card && !card.classList.contains('hidden')) {
                frCloseCard();
                return;
            }
            frOpenClusterCard(g, g.x, g.y);
        });
        overlay.appendChild(btn);
    });

    // 重点交易：淡金色完整周期区间 + 金色星标
    const cyclePoints = {};
    fs.fills.forEach((f) => {
        const cyc = f.trade_cycle_id;
        if (!cyc) return;
        const idx = fs.baseTimeIndex || {};
        const time = idx.barTime ? idx.barTime[String(f.bar_id)] : undefined;
        const eq = time !== undefined && idx.timeEquity ? idx.timeEquity[String(time)] : undefined;
        if (time === undefined || eq === undefined) return;
        let x; let y;
        try {
            x = reportEquityChart.timeScale().timeToCoordinate(time);
            y = reportEquitySeries.priceToCoordinate(eq);
        } catch (e) { return; }
        if (x === null || y === null) return;
        (cyclePoints[cyc] = cyclePoints[cyc] || []).push({ x: x, y: y, fill_id: f.fill_id });
    });

    fs.keys.forEach((k) => {
        const pts = cyclePoints[k.trade_cycle_id];
        if (!pts || !pts.length) return;
        const xs = pts.map((p) => p.x);
        const minX = Math.min.apply(null, xs);
        const maxX = Math.max.apply(null, xs);
        const band = document.createElement('div');
        band.className = 'fr-cycle-band';
        band.style.left = (minX - 6) + 'px';
        band.style.width = Math.max(12, maxX - minX + 12) + 'px';
        overlay.appendChild(band);

        const first = pts[0];
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'fr-key-marker';
        btn.dataset.cycle = k.trade_cycle_id;
        btn.title = '点击查看这个周期的完整深度点评';
        btn.textContent = '★ 重点';
        btn.style.left = first.x + 'px';
        btn.style.top = (first.y - 34) + 'px';
        btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            const panel = document.getElementById('key-trade-panel');
            if (frState.activeCycle === k.trade_cycle_id && panel && !panel.classList.contains('hidden')) {
                frCloseKeyPanel();
                return;
            }
            frOpenKeyPanel(k);
        });
        overlay.appendChild(btn);
    });
}

function frScheduleRender() {
    if (frFrame) return;
    frFrame = requestAnimationFrame(() => {
        frFrame = 0;
        frRenderOverlay();
        if (frState.activeKey) frPositionCard();
    });
}

function frCloseCard() {
    const card = document.getElementById('fill-review-card');
    if (card) {
        card.classList.add('hidden');
        card.innerHTML = '';
    }
    frState.activeKey = null;
    frState.anchor = null;
    frSyncActiveMarker();
}

function frSyncActiveMarker() {
    const overlay = document.getElementById('fill-review-overlay');
    if (!overlay) return;
    overlay.querySelectorAll('.fr-marker, .fr-key-marker').forEach((el) => {
        const match = (el.dataset.key && el.dataset.key === frState.activeKey)
            || (el.dataset.cycle && el.dataset.cycle === frState.activeCycle);
        el.classList.toggle('fr-marker-active', !!match);
    });
}

function frPositionCard() {
    const card = document.getElementById('fill-review-card');
    const wrap = document.getElementById('report-equity-chart-wrap');
    if (!card || !wrap || card.classList.contains('hidden')) return;
    if (!frState.anchor) return;
    const x = frState.anchor.x;
    const y = frState.anchor.y;
    const mobile = window.innerWidth < 760 || wrap.clientWidth < 540;
    card.classList.toggle('fr-card-mobile', mobile);
    if (mobile) {
        card.style.left = '';
        card.style.top = '';
        card.style.maxHeight = '';
        return;
    }
    const ww = wrap.clientWidth;
    const wh = wrap.clientHeight;
    card.style.maxHeight = Math.max(120, wh - 12) + 'px';
    const cw = card.offsetWidth || 300;
    const ch = Math.min(card.offsetHeight || 180, Math.max(120, wh - 12));
    let left = x + 18;
    if (left + cw > ww - 6) left = x - cw - 18;
    if (left < 6) left = 6;
    let top = y - ch / 2;
    if (top + ch > wh - 6) top = wh - ch - 6;
    if (top < 6) top = 6;
    card.style.left = left + 'px';
    card.style.top = top + 'px';
}

function frShowCard(html, x, y, key) {
    const card = document.getElementById('fill-review-card');
    if (!card) return;
    card.innerHTML = html;
    card.classList.remove('hidden');
    frState.activeKey = key || null;
    frState.anchor = { x: x, y: y };
    frPositionCard();
    frSyncActiveMarker();
}

/* 普通成交事实：只列交易事实，不带任何 AI 评价 */
function frFactItem(f) {
    const isBuy = f.side === 'buy';
    const time = frBarTimeOf(f.bar_id);
    const dateText = String(f.date || '') + (time ? ' ' + time : '');
    return `<div class="fr-fact-item">
        <div class="fr-fact-head">
            <span class="fr-dir ${isBuy ? 'fr-dir-buy' : 'fr-dir-sell'}">${isBuy ? '买入' : '卖出'}</span>
            <span class="fr-mono">${escapeHtml(String(f.fill_id || ''))}</span>
            <span class="fr-fact-action">${escapeHtml(String(f.action_type || ''))}</span>
        </div>
        <div class="fr-fact-grid">
            <span>日期</span><b>${escapeHtml(dateText)}</b>
            <span>价格</span><b>${escapeHtml(String(f.price))}</b>
            <span>数量</span><b>${escapeHtml(String(f.quantity))} 股</b>
            <span>Bar ID</span><b class="fr-mono">${escapeHtml(String(f.bar_id))}</b>
            <span>周期</span><b class="fr-mono">${escapeHtml(String(f.trade_cycle_id || ''))}</b>
            <span>持仓</span><b>${escapeHtml(String(f.position_before))} → ${escapeHtml(String(f.position_after))} 股</b>
        </div>
    </div>`;
}

function frOpenClusterCard(group, x, y) {
    const fills = group.fills;
    const sideLabel = group.side === 'buy' ? '买入' : '卖出';
    const head = `<div class="fr-card-head">
        <span class="fr-card-title">${fills.length > 1 ? `本位置${sideLabel} ×${fills.length}` : `这一笔${sideLabel}成交`}</span>
        <button type="button" class="fr-card-close" data-act="close" aria-label="关闭">×</button>
    </div>`;
    const cycles = Array.from(new Set(fills.map((f) => f.trade_cycle_id).filter(Boolean)))
        .filter((c) => frState.keys.some((k) => k.trade_cycle_id === c));
    const links = cycles.map((c) => `<button type="button" class="fr-link-btn" data-act="cycle" data-cycle="${escapeHtml(c)}">查看 ${escapeHtml(c)} 完整交易周期点评</button>`).join('');
    frShowCard(`${head}<div class="fr-card-body fr-card-body-facts">${fills.map(frFactItem).join('')}${links}</div>`, x, y, group.key);
}

function frCloseKeyPanel() {
    const panel = document.getElementById('key-trade-panel');
    const body = document.getElementById('key-trade-body');
    const label = document.getElementById('kt-cycle-label');
    if (panel) panel.classList.add('hidden');
    if (body) body.innerHTML = '';
    if (label) label.textContent = '';
    frState.activeCycle = null;
    frSyncActiveMarker();
}

function frOpenKeyPanel(k) {
    if (!k) return;
    const panel = document.getElementById('key-trade-panel');
    const body = document.getElementById('key-trade-body');
    const label = document.getElementById('kt-cycle-label');
    if (!panel || !body) return;
    const cycleFills = frState.fills.filter((f) => f.trade_cycle_id === k.trade_cycle_id);
    const first = cycleFills[0] || null;
    const last = cycleFills.length ? cycleFills[cycleFills.length - 1] : null;
    const closed = last && Number(last.position_after) === 0;
    const period = first
        ? `${first.date}${frBarTimeOf(first.bar_id) ? ' ' + frBarTimeOf(first.bar_id) : ''} → ${last ? last.date : ''}`
        : '时间缺失';
    const list = (v, emptyText) => (Array.isArray(v) && v.length
        ? `<ul class="fr-bullets">${v.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>`
        : `<div class="fr-muted">${emptyText}</div>`);
    const evid = (k.evidence_fill_ids || []).map((fid) => `<button type="button" class="fr-chip" data-act="focus" data-fill="${escapeHtml(fid)}">${escapeHtml(fid)}</button>`).join(' ');
    const facts = cycleFills.map(frFactItem).join('');
    if (label) {
        label.textContent = `${k.trade_cycle_id} · ${cycleFills.length} 笔成交 · ${closed ? '已清仓' : '期末仍持仓'}`;
    }
    body.innerHTML = `
        <div class="kt-overview">
            <div class="kt-ov-item"><span>周期编号</span><b class="fr-mono">${escapeHtml(k.trade_cycle_id)}</b></div>
            <div class="kt-ov-item"><span>首次建仓</span><b>${escapeHtml(first ? first.date : '—')}</b></div>
            <div class="kt-ov-item"><span>最终清仓</span><b>${escapeHtml(closed && last ? last.date : '期末仍持仓')}</b></div>
            <div class="kt-ov-item"><span>区间</span><b>${escapeHtml(period)}</b></div>
            <div class="kt-ov-item"><span>标题</span><b>${escapeHtml(k.title || '—')}</b></div>
        </div>
        <div class="kt-section">
            <div class="kt-section-title">全部相关成交 · 主要操作过程</div>
            <div class="kt-fills">${facts || '<div class="fr-muted">该周期没有可用成交记录</div>'}</div>
        </div>
        <div class="kt-section">
            <div class="kt-section-title">AI 总体评价</div>
            <div class="kt-text">${escapeHtml(k.summary || '无')}</div>
        </div>
        <div class="kt-section">
            <div class="kt-section-title">主要优点</div>${list(k.strengths, '无')}
        </div>
        <div class="kt-section">
            <div class="kt-section-title">核心问题</div>${list(k.issues, '无')}
        </div>
        <div class="kt-section">
            <div class="kt-section-title">经验总结</div>
            <div class="kt-text">${escapeHtml(k.lesson || '无')}</div>
        </div>
        <div class="kt-section">
            <div class="kt-section-title">后续改进建议</div>${list(k.next_rules, '无')}
        </div>
        <div class="kt-section">
            <div class="kt-section-title">证据成交（点击定位到曲线上那一笔）</div>
            <div class="fr-chips">${evid || '<span class="fr-muted">无</span>'}</div>
        </div>`;
    panel.classList.remove('hidden');
    frState.activeCycle = k.trade_cycle_id;
    frSyncActiveMarker();
    if (typeof panel.scrollIntoView === 'function') {
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function frFocusFill(fillId) {
    const cluster = frState.clusters.find((c) => c.fills.some((f) => f.fill_id === fillId));
    if (!cluster) {
        frSetNotice(`找不到 ${fillId} 对应的曲线位置（该笔成交可能没有映射到 K 线）。`, 'warn');
        return;
    }
    const wrap = document.getElementById('report-equity-chart-wrap');
    if (wrap && typeof wrap.scrollIntoView === 'function') {
        wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    const pos = frProject(cluster);
    if (!pos) {
        frSetNotice(`${fillId} 在当前视图里点不到（时间或净值缺失），缩放图表后再试。`, 'warn');
        return;
    }
    const fake = { key: cluster.key, side: cluster.side, x: pos.x, y: pos.y, fills: cluster.fills.slice() };
    frOpenClusterCard(fake, pos.x, pos.y);
}

function frBindCardEvents() {
    const card = document.getElementById('fill-review-card');
    if (!card) return;
    card.addEventListener('click', (ev) => {
        const act = ev.target.closest('[data-act]');
        if (!act) return;
        ev.stopPropagation();
        const action = act.dataset.act;
        if (action === 'close') frCloseCard();
        if (action === 'cycle') {
            const k = frState.keys.find((x) => x.trade_cycle_id === act.dataset.cycle);
            if (k) frOpenKeyPanel(k);
        }
        if (action === 'focus') frFocusFill(act.dataset.fill);
    });
}

function frBindGlobalEvents() {
    if (frState.globalBound) return;
    frState.globalBound = true;
    document.addEventListener('mousedown', (ev) => {
        const card = document.getElementById('fill-review-card');
        if (!card || card.classList.contains('hidden')) return;
        if (card.contains(ev.target)) return;
        if (ev.target.closest && ev.target.closest('.fr-marker, .fr-key-marker')) return;
        frCloseCard();
    });
    document.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Escape') return;
        const card = document.getElementById('fill-review-card');
        if (card && !card.classList.contains('hidden')) {
            frCloseCard();
            return;
        }
        const panel = document.getElementById('key-trade-panel');
        if (panel && !panel.classList.contains('hidden')) frCloseKeyPanel();
    });
    document.getElementById('kt-close')?.addEventListener('click', frCloseKeyPanel);
    const panel = document.getElementById('key-trade-panel');
    if (panel && !panel.dataset.bound) {
        panel.dataset.bound = '1';
        panel.addEventListener('click', (ev) => {
            const act = ev.target.closest('[data-act]');
            if (!act) return;
            if (act.dataset.act === 'focus') frFocusFill(act.dataset.fill);
        });
    }
}
function showReport(report) {
    // 保存当前报告数据供 AI 分析使用
    currentReportData = report;
    setTrainingViewOnlyMode(false, { showBackToReport: false });
    
    // 切换界面可见性
    document.getElementById('training-interface').classList.add('hidden');
    document.getElementById('report-interface').classList.remove('hidden');
    document.getElementById('main-app').classList.remove('training-mode');

    // 恢复工具栏状态
    toggleToolbarForTraining(false);

    // 获取报告内容的容器
    const reportContent = document.getElementById('report-content');
    reportContent.innerHTML = ''; // 清空旧内容

    // 检查用户是否开启了 AI API
    checkAIStatusAndShowButton();

    // 创建并添加摘要和交易详情
    const summarySection = document.createElement('div');
    summarySection.className = 'report-summary';
    updateReportSummary(summarySection, report); // 使用辅助函数填充摘要

    const detailsSection = document.createElement('div');
    detailsSection.className = 'trade-details-section';
    createTradeDetailsTable(detailsSection, report.trade_details); // 使用辅助函数创建表格

    // 将生成好的模块添加到主容器中
    reportContent.appendChild(summarySection);

    reportContent.appendChild(detailsSection);

    // 全程K线与收益曲线
    renderReportCharts(report);

    // 更新用户统计
    loadUserStatistics();
}

/**
 * 检查AI状态并显示/隐藏AI分析按钮
 */
async function checkAIStatusAndShowButton() {
    const aiBtn = document.getElementById('ai-analyze-btn');
    if (!currentUser || !aiBtn) return;
    
    try {
        const response = await fetch(`${API_BASE}/users/${currentUser}/settings`);
        if (response.ok) {
            const settings = await response.json();
            if (settings.enable_ai_api) {
                aiBtn.classList.remove('hidden');
            } else {
                aiBtn.classList.add('hidden');
            }
        }
    } catch (e) {
        console.error('Failed to check AI status:', e);
    }
}

async function viewFullChart() {
    if (!currentTraining && !currentReportData) {
        alert('找不到训练会话数据，无法查看完整走势');
        return;
    }
    
    // Use session_id from report data if available, otherwise from currentTraining
    const trainingId = currentReportData ? currentReportData.session_id : currentTraining.id;
    if (!currentTraining) {
        currentTraining = { id: trainingId, latestProgress: null, tradeMarkers: [] };
    }

    const maQuery = maPeriods.join(',');
    try {
        const response = await fetch(`${API_BASE}/training/${trainingId}/full_data?ma_periods=${maQuery}&${getViewPeriodQuery()}`);
        if (!response.ok) {
            throw new Error('获取完整数据失败');
        }
        
        const data = await response.json();
        
        // Hide report interface and show training interface
        document.getElementById('report-interface').classList.add('hidden');
        document.getElementById('training-interface').classList.remove('hidden');
        document.getElementById('main-app').classList.add('training-mode');
        toggleToolbarForTraining(true);
        
        // Update chart data
        if (data.kline_data && data.kline_data.length > 0) {
            applyTrainingSnapshot(data);
            
            // Re-load technical indicators for full range
            await loadTechnicalIndicator(currentIndicatorType);
            await updateChipDistribution();
            
            // Adjust time scale to fit all data
            chart.timeScale().fitContent();
        }
        
        setTrainingViewOnlyMode(true, { showBackToReport: true });
        
    } catch (error) {
        console.error('查看完整走势失败:', error);
        alert('获取完整走势数据失败');
    }
}

// 工具函数
function formatNumber(num) {
    return num.toLocaleString();
}

function formatCurrency(num) {
    return `¥${num.toLocaleString()}`;
}

function formatPercent(num) {
    return `${num.toFixed(2)}%`;
}

// ---------------------------------------------------------------- 历史问题档案

const rhState = { issues: [], currentId: null, filtersReady: false };

function escapeHtml(text) {
    return String(text == null ? '' : text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function rhFetch(path, options) {
    if (!currentUser) return Promise.reject(new Error('未选择用户'));
    return fetch(`${API_BASE}/users/${encodeURIComponent(currentUser)}${path}`, options);
}

async function openReviewHistory() {
    document.getElementById('review-history-modal')?.classList.remove('hidden');
    document.getElementById('rh-detail')?.classList.add('hidden');
    await loadReviewHistory();
    await loadReviewBackups();
}

async function loadReviewHistory() {
    try {
        const params = new URLSearchParams();
        const map = {
            category: 'rh-filter-category', ai_status: 'rh-filter-ai',
            user_status: 'rh-filter-user', severity: 'rh-filter-severity', q: 'rh-search'
        };
        Object.entries(map).forEach(([key, id]) => {
            const v = document.getElementById(id)?.value || '';
            if (v) params.set(key, v);
        });
        const res = await rhFetch(`/review-history?${params.toString()}`);
        const data = await res.json();
        if (!res.ok) { alert(data.error || '读取历史问题失败'); return; }
        rhState.issues = data.issues || [];
        renderRhFilters(data.filters || {});
        renderRhStats(data.summary || {}, data.review_count || 0);
        renderRhList();
        const meta = document.getElementById('rh-meta');
        if (meta) meta.textContent = `共复盘 ${data.review_count || 0} 次｜档案更新于 ${data.updated_at || '—'}`;
    } catch (e) {
        console.error('读取历史问题失败:', e);
    }
}

function renderRhFilters(filters) {
    if (rhState.filtersReady) return;
    const cat = document.getElementById('rh-filter-category');
    if (cat && (filters.categories || []).length) {
        cat.innerHTML = '<option value="">全部分类</option>' +
            filters.categories.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    }
    const st = document.getElementById('rh-edit-status');
    if (st && (filters.user_statuses || []).length) {
        st.innerHTML = filters.user_statuses.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    }
    rhState.filtersReady = true;
}

function renderRhStats(s, reviewCount) {
    const box = document.getElementById('rh-stats');
    if (!box) return;
    const cards = [
        ['问题总数', s.total || 0],
        ['持续出现', s.recurring || 0],
        ['有改善迹象', s.improving || 0],
        ['新发现', s.new || 0],
        ['待我处理', s.pending || 0]
    ];
    box.innerHTML = cards.map(([label, value]) =>
        `<div class="rh-stat"><span class="rh-stat-value">${value}</span><span class="rh-stat-label">${label}</span></div>`
    ).join('') + `<div class="rh-stat"><span class="rh-stat-value">${reviewCount || 0}</span><span class="rh-stat-label">已复盘次数</span></div>`;
}

function rhStatusClass(status) {
    return `rh-chip rh-ai-${String(status || 'NEW').toLowerCase()}`;
}

function renderRhList() {
    const list = document.getElementById('rh-list');
    const empty = document.getElementById('rh-empty');
    if (!list) return;
    if (!rhState.issues.length) {
        list.innerHTML = '';
        empty?.classList.remove('hidden');
        return;
    }
    empty?.classList.add('hidden');
    list.innerHTML = rhState.issues.map(i => {
        const active = i.issue_id === rhState.currentId ? ' rh-item-active' : '';
        return `
            <div class="rh-item${active}" data-issue-id="${escapeHtml(i.issue_id)}">
                <div class="rh-item-main">
                    <div class="rh-item-title"><span class="rh-id">${escapeHtml(i.issue_id)}</span>${escapeHtml(i.title)}</div>
                    <div class="rh-item-sub">${escapeHtml(i.category)}｜严重度 ${escapeHtml(i.severity)}｜出现 ${i.occurrence_count || 0} 次｜最近 ${escapeHtml(i.last_seen || '—')}</div>
                </div>
                <div class="rh-item-chips">
                    <span class="${rhStatusClass(i.status_ai)}">${escapeHtml(i.status_ai || '')}</span>
                    <span class="rh-chip rh-user">${escapeHtml(i.status_user || '')}</span>
                </div>
            </div>`;
    }).join('');
    list.querySelectorAll('.rh-item').forEach(el => {
        el.addEventListener('click', () => openIssueDetail(el.dataset.issueId));
    });
}

async function openIssueDetail(issueId) {
    try {
        const res = await rhFetch(`/review-history/${encodeURIComponent(issueId)}`);
        const data = await res.json();
        if (!res.ok) { alert(data.error || '读取问题详情失败'); return; }
        const issue = data.issue;
        rhState.currentId = issueId;
        renderRhList();

        document.getElementById('rh-detail-title').textContent = `${issue.issue_id} ${issue.title}`;
        document.getElementById('rh-detail-meta').innerHTML = [
            `分类：${escapeHtml(issue.category)}`,
            `AI 观察：<span class="${rhStatusClass(issue.status_ai)}">${escapeHtml(issue.status_ai)}</span>`,
            `严重度：${escapeHtml(issue.severity)}`,
            `出现次数：${issue.occurrence_count || 0}`,
            `首次 ${escapeHtml(issue.first_seen || '—')}`,
            `最近 ${escapeHtml(issue.last_seen || '—')}`,
            `最近复盘：${escapeHtml(issue.last_review_id || '—')}`
        ].join('　·　');

        const statusSel = document.getElementById('rh-edit-status');
        if (statusSel) {
            const opts = data.user_statuses || [];
            statusSel.innerHTML = opts.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
            statusSel.value = issue.status_user || opts[0] || '';
        }
        document.getElementById('rh-edit-description').value = issue.description || '';
        document.getElementById('rh-edit-rule').value = issue.recommended_rule || '';
        document.getElementById('rh-edit-note').value = issue.user_note || '';
        document.getElementById('rh-save-hint').textContent = '';

        const ev = issue.evidence || [];
        document.getElementById('rh-evidence').innerHTML = ev.length ? `
            <table class="rh-table"><thead><tr><th>复盘</th><th>日期</th><th>Bar</th><th>fill_id</th><th>证据</th></tr></thead>
            <tbody>${ev.map(e => `<tr><td>${escapeHtml(e.review_id)}</td><td>${escapeHtml(e.date)}</td><td>${escapeHtml(e.bar_id)}</td><td>${escapeHtml(e.fill_id)}</td><td>${escapeHtml(e.description)}</td></tr>`).join('')}</tbody></table>` : '<div class="rh-meta">暂无证据</div>';

        const ob = issue.ai_observations || [];
        document.getElementById('rh-observations').innerHTML = ob.length ? `
            <table class="rh-table"><thead><tr><th>时间</th><th>复盘</th><th>结论</th><th>观察</th></tr></thead>
            <tbody>${ob.map(o => `<tr><td>${escapeHtml(o.at)}</td><td>${escapeHtml(o.review_id)}</td><td>${escapeHtml(o.observation_status)}</td><td>${escapeHtml(o.observation)}</td></tr>`).join('')}</tbody></table>` : '<div class="rh-meta">暂无观察记录</div>';

        const ver = issue.versions || [];
        document.getElementById('rh-versions').innerHTML = ver.length ? `
            <table class="rh-table"><thead><tr><th>时间</th><th>来源</th><th>操作</th><th>说明</th></tr></thead>
            <tbody>${ver.map(v => `<tr><td>${escapeHtml(v.at)}</td><td>${escapeHtml(v.by)}</td><td>${escapeHtml(v.op)}</td><td>${escapeHtml(v.detail)}</td></tr>`).join('')}</tbody></table>` : '<div class="rh-meta">暂无版本记录</div>';

        document.getElementById('rh-detail')?.classList.remove('hidden');
        document.getElementById('rh-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
        console.error('读取问题详情失败:', e);
        alert('读取问题详情失败');
    }
}

async function saveIssueDetail() {
    if (!rhState.currentId) return;
    const payload = {
        description: document.getElementById('rh-edit-description').value,
        recommended_rule: document.getElementById('rh-edit-rule').value,
        user_note: document.getElementById('rh-edit-note').value,
        status_user: document.getElementById('rh-edit-status').value
    };
    try {
        const res = await rhFetch(`/review-history/${encodeURIComponent(rhState.currentId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) { alert(data.error || '保存失败'); return; }
        document.getElementById('rh-save-hint').textContent = '已保存，AI 下一轮不会再覆盖这些字段';
        await loadReviewHistory();
        await openIssueDetail(rhState.currentId);
    } catch (e) {
        console.error('保存历史问题失败:', e);
        alert('保存失败');
    }
}

let coachHistory = [];
let coachBusy = false;

function setCoachContext(text) {
    const el = document.getElementById('ai-coach-context');
    if (el) el.textContent = text;
}

function resetCoachChat(closePanel = false) {
    coachHistory = [];
    clearBarHighlight();
    const box = document.getElementById('ai-coach-messages');
    if (box) {
        box.innerHTML = '<div class="ai-coach-empty">陪练只读取当前 Bar 及之前的 K 线、指标和你的持仓。它不会预测后面怎么走，也不会替你下单。<br>先推进几根 K 线，再问它结构、量能或仓位问题。</div>';
    }
    setCoachContext('只看到当前 Bar 及之前的数据');
    if (closePanel) {
        document.getElementById('ai-coach-panel')?.classList.add('hidden');
    }
}

function toggleCoachPanel(forceVisible) {
    const panel = document.getElementById('ai-coach-panel');
    if (!panel) return;
    const willShow = typeof forceVisible === 'boolean' ? forceVisible : panel.classList.contains('hidden');
    if (willShow) {
        const id = currentTraining && (currentTraining.id || currentTraining.session_id);
        if (!id) {
            alert('训练还没开始，AI 陪练要在一轮训练里使用');
            return;
        }
        panel.classList.remove('hidden');
        document.getElementById('ai-coach-input')?.focus();
    } else {
        panel.classList.add('hidden');
    }
}

function renderCoachText(text) {
    const safe = escapeHtml(text);
    return safe.replace(/\b(BAR|Bar|bar)\s*(-?\d+)\b/g, (_, _label, barId) =>
        `<span class="coach-bar-ref" data-bar="${barId}" title="在图上高亮 Bar ${barId}">Bar ${barId}</span>`);
}

function findRenderedBar(barId) {
    const list = latestRenderedKlineData || [];
    return list.find((bar) => Number(bar.bar_id) === barId) || null;
}

function clearBarHighlight() {
    try {
        if (chart) chart.clearCrosshairPosition();
        if (volumeChart) volumeChart.clearCrosshairPosition();
    } catch (error) { /* 图表未初始化时忽略 */ }
    document.querySelectorAll('.bar-highlight-overlay').forEach((el) => el.remove());
}

function drawBarHighlight(bar) {
    const chartEl = document.getElementById('chart');
    const container = chartEl && chartEl.parentElement;
    if (!chartEl || !container || !chart || !candlestickSeries) return;
    const x = chart.timeScale().timeToCoordinate(bar.time);
    const yHigh = candlestickSeries.priceToCoordinate(bar.high);
    const yLow = candlestickSeries.priceToCoordinate(bar.low);
    let overlay = container.querySelector('.bar-highlight-overlay');
    if (x == null || yHigh == null || yLow == null) {
        overlay?.remove();
        return;
    }
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'bar-highlight-overlay';
        container.appendChild(overlay);
    }
    const index = latestRenderedKlineData.indexOf(bar);
    const neighbor = latestRenderedKlineData[index + 1] || latestRenderedKlineData[index - 1];
    const neighborX = neighbor ? chart.timeScale().timeToCoordinate(neighbor.time) : null;
    const width = neighborX != null ? Math.max(3, Math.abs(neighborX - x)) : 8;
    overlay.style.left = `${chartEl.offsetLeft + x - width / 2}px`;
    overlay.style.top = `${chartEl.offsetTop + Math.min(yHigh, yLow) - 6}px`;
    overlay.style.width = `${width}px`;
    overlay.style.height = `${Math.abs(yLow - yHigh) + 12}px`;
}

function highlightChartBar(barId, focus = false) {
    const bar = findRenderedBar(barId);
    if (!bar || !chart || !candlestickSeries) return false;
    if (focus) {
        const index = latestRenderedKlineData.indexOf(bar);
        chart.timeScale().setVisibleLogicalRange({
            from: Math.max(0, index - 15),
            to: Math.min(latestRenderedKlineData.length - 1, index + 15),
        });
    }
    try {
        chart.setCrosshairPosition(bar.close, bar.time, candlestickSeries);
        if (volumeChart && volumeSeries) volumeChart.setCrosshairPosition(bar.volume, bar.time, volumeSeries);
    } catch (error) {
        console.warn('Bar 高亮失败:', error);
    }
    requestAnimationFrame(() => drawBarHighlight(bar));
    return true;
}

function appendCoachMessage(role, content, meta) {
    const box = document.getElementById('ai-coach-messages');
    if (!box) return;
    box.querySelector('.ai-coach-empty')?.remove();
    const bubble = document.createElement('div');
    bubble.className = `ai-coach-msg ${role}`;
    if (role === 'assistant') {
        bubble.innerHTML = renderCoachText(content);
    } else {
        bubble.textContent = content;
    }
    if (meta) {
        const note = document.createElement('div');
        note.className = 'ai-coach-meta';
        note.textContent = meta;
        bubble.appendChild(note);
    }
    box.appendChild(bubble);
    box.scrollTop = box.scrollHeight;
}

async function sendCoachQuestion(rawQuestion) {
    const question = String(rawQuestion || '').trim();
    if (!question || coachBusy) return;
    const trainingId = currentTraining && (currentTraining.id || currentTraining.session_id);
    if (!trainingId) {
        alert('训练还没开始，AI 陪练要在一轮训练里使用');
        return;
    }

    coachBusy = true;
    const sendBtn = document.getElementById('ai-coach-send-btn');
    const input = document.getElementById('ai-coach-input');
    if (sendBtn) { sendBtn.disabled = true; sendBtn.textContent = '思考中…'; }
    if (input) input.value = '';
    appendCoachMessage('user', question);

    const priorTurns = coachHistory.slice(-6);
    coachHistory.push({ role: 'user', content: question });
    try {
        const res = await fetch(`${API_BASE}/training/${encodeURIComponent(trainingId)}/coach`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, history: priorTurns })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '陪练接口返回失败');
        appendCoachMessage('assistant', data.answer, `Bar ${data.meta?.bar_id ?? '—'} · ${data.meta?.date ?? '—'} · 仅基于已发生数据`);
        coachHistory.push({ role: 'assistant', content: data.answer });
        if (data.meta) {
            setCoachContext(`当前 Bar ${data.meta.bar_id}（${data.meta.date}）· 可见 ${data.meta.visible_bars} 根 · 模型 ${data.meta.model}`);
        }
    } catch (error) {
        console.error('AI 陪练失败:', error);
        appendCoachMessage('error', error.message || '陪练请求失败，请稍后再试');
        coachHistory.pop();
    } finally {
        coachBusy = false;
        if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = '发送'; }
        document.getElementById('ai-coach-input')?.focus();
    }
}

async function exportReportMarkdown() {
    const sid = (currentReportData && currentReportData.session_id)
        || (currentTraining && (currentTraining.id || currentTraining.session_id));
    if (!currentUser || !sid) {
        alert('还没有可导出的复盘报告，请先完成一次训练或打开一条历史记录');
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/users/${encodeURIComponent(currentUser)}/history/${encodeURIComponent(sid)}/export`);
        const data = await res.json();
        if (!res.ok) { alert(data.error || '导出失败'); return; }
        const blob = new Blob([data.markdown || ''], { type: 'text/markdown;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = data.filename || '复盘数据包.md';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) {
        console.error('导出复盘数据包失败:', e);
        alert('导出失败');
    }
}

async function exportReviewHistory() {
    try {
        const res = await rhFetch('/review-history/export');
        const data = await res.json();
        if (!res.ok) { alert(data.error || '导出失败'); return; }
        const blob = new Blob([data.markdown || ''], { type: 'text/markdown;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'trade_review_history.md';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) {
        console.error('导出失败:', e);
        alert('导出失败');
    }
}

async function loadReviewBackups() {
    try {
        const res = await rhFetch('/review-history/backups');
        const data = await res.json();
        const sel = document.getElementById('rh-backup-list');
        if (!sel) return;
        const list = data.backups || [];
        sel.innerHTML = list.length
            ? list.map(b => `<option value="${escapeHtml(b.name)}">${escapeHtml(b.name)}</option>`).join('')
            : '<option value="">暂无备份</option>';
    } catch (e) {
        console.error('读取备份失败:', e);
    }
}

async function backupReviewHistory() {
    try {
        const res = await rhFetch('/review-history/backup', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) { alert(data.error || '备份失败'); return; }
        alert(`已备份：${data.name}`);
        await loadReviewBackups();
    } catch (e) {
        console.error('备份失败:', e);
        alert('备份失败');
    }
}

async function restoreReviewHistory() {
    const sel = document.getElementById('rh-backup-list');
    const name = sel?.value || '';
    if (!name) { alert('没有可恢复的备份'); return; }
    if (!confirm(`确定用备份 ${name} 覆盖当前档案吗？恢复前会自动备份当前档案。`)) return;
    try {
        const res = await rhFetch('/review-history/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await res.json();
        if (!res.ok) { alert(data.error || '恢复失败'); return; }
        alert(data.message || '已恢复');
        await loadReviewHistory();
        await loadReviewBackups();
    } catch (e) {
        console.error('恢复失败:', e);
        alert('恢复失败');
    }
}

