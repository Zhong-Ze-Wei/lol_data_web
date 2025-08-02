<template>
  <div class="home-container">
    <!-- 标题和欢迎信息 -->
    <el-row :gutter="20">
      <el-col :span="24">
        <el-card class="welcome-card" shadow="hover">
          <div slot="header" class="welcome-header">
            <h2>🎮 欢迎来到LOL职业赛事数据平台</h2>
          </div>
          <p class="welcome-text">这是一个专注于英雄联盟职业赛事数据分析的平台，提供选手表现、战队对比、比赛回顾等丰富内容。</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- 统计数据 -->
    <el-row :gutter="20" justify="space-around" class="stats-section">
      <el-col :span="8" class="stat-item">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-number" 
               @mouseenter="enlargeNumber"
               @mouseleave="resetNumber"
               :style="{ transform: stats.matchesTransform }">
            {{ formatNumber(stats.matches) || 0 }}
          </div>
          <div class="stat-label">比赛场次</div>
        </el-card>
      </el-col>
      <el-col :span="8" class="stat-item">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-number" 
               @mouseenter="enlargeNumber"
               @mouseleave="resetNumber"
               :style="{ transform: stats.playersTransform }">
            {{ formatNumber(stats.players) || 0 }}
          </div>
          <div class="stat-label">职业选手</div>
        </el-card>
      </el-col>
      <el-col :span="8" class="stat-item">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-number" 
               @mouseenter="enlargeNumber"
               @mouseleave="resetNumber"
               :style="{ transform: stats.teamsTransform }">
            {{ formatNumber(stats.teams) || 0 }}
          </div>
          <div class="stat-label">职业战队</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 数据区域 - 趣味数据和AI查询放在同一行 -->
    <el-row :gutter="20" class="data-section">
      <!-- 趣味数据 - 左侧 -->
      <el-col :span="16">
        <el-card class="data-card" shadow="hover">
          <div slot="header" class="data-header">
            <span class="section-title">📊 趣味数据</span>
          </div>
          <el-tabs type="border-card">
            <el-tab-pane label="选手参赛榜">
              <div class="fun-data-list">
                <div 
                  v-for="(player, index) in topPlayers" 
                  :key="player.name"
                  class="fun-data-item"
                  :class="getRankClass(index)"
                >
                  <div class="rank">{{ index + 1 }}</div>
                  <div class="name">{{ player.name }}</div>
                  <div class="value">{{ player.matches_count }} 场</div>
                </div>
              </div>
            </el-tab-pane>
            <el-tab-pane label="战队胜率榜">
              <div class="fun-data-list">
                <div 
                  v-for="(team, index) in topTeams" 
                  :key="team.team_name"
                  class="fun-data-item"
                  :class="getRankClass(index)"
                >
                  <div class="rank">{{ index + 1 }}</div>
                  <div class="name">{{ team.team_name }}</div>
                  <div class="value">{{ team.win_rate }}%</div>
                </div>
              </div>
            </el-tab-pane>
            <el-tab-pane label="最快比赛">
              <div class="fun-data-list">
                <div 
                  v-for="(match, index) in fastestMatches" 
                  :key="match.id"
                  class="fun-data-item"
                  :class="getRankClass(index)"
                >
                  <div class="rank">{{ index + 1 }}</div>
                  <div class="name">{{ match.blue_team_name }} vs {{ match.red_team_name }}</div>
                  <div class="value">{{ formatGameTime(match.game_time) }}</div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-col>
      
      <!-- AI查询小窗口 - 右侧 -->
      <el-col :span="8">
        <el-card class="ai-card" shadow="hover">
          <div slot="header" class="ai-header">
            <span class="section-title">🤖 AI数据分析</span>
          </div>
          <div class="ai-content">
            <p class="ai-description">智能分析赛事数据，提供深度洞察</p>
            <el-input
              type="textarea"
              :rows="3"
              placeholder="请输入您想查询的数据分析问题..."
              v-model="aiQuery"
              class="ai-input"
            ></el-input>
            <el-button 
              type="primary" 
              class="ai-button"
              @click="submitAIQuery"
              :loading="aiLoading"
            >
              {{ aiLoading ? '分析中...' : '开始分析' }}
            </el-button>
            <div v-if="aiResult" class="ai-result">
              <h4>分析结果：</h4>
              <p>{{ aiResult }}</p>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷链接 -->
    <el-row :gutter="20" class="quick-links">
      <el-col :span="8">
        <el-card class="link-card" @click.native="goToPlayers" shadow="hover">
          <i class="el-icon-user link-icon"></i>
          <h3>选手数据</h3>
          <p>查看所有职业选手的比赛数据和表现统计</p>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="link-card" @click.native="goToMatches" shadow="hover">
          <i class="el-icon-tickets link-icon"></i>
          <h3>比赛回顾</h3>
          <p>回顾经典比赛的详细数据和分析</p>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="link-card" @click.native="goToTeams" shadow="hover">
          <i class="el-icon-office-building link-icon"></i>
          <h3>战队数据</h3>
          <p>查看职业战队的详细信息和战绩</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- 自我介绍 -->
    <el-row :gutter="20" class="about-section">
      <el-col :span="24">
        <el-card class="about-card" shadow="hover">
          <a href="https://github.com/Zhong-Ze-Wei" target="_blank" class="about-link">
            <el-image
              :src="require('@/assets/my_photo.jpg')"
              class="about-image"
              fit="cover"
              lazy
            ></el-image>
            <div class="about-text">
              <h3>👋 这里是zz的游戏空间</h3>
              <p>和我一起用数据分析万物</p>
              <div class="social-links">
                <el-button type="primary" icon="el-icon-star-off" size="mini" plain>GitHub</el-button>
                <el-button type="success" icon="el-icon-chat-dot-round" size="mini" plain>联系我</el-button>
              </div>
            </div>
          </a>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
export default {
  name: 'Home',
  data() {
    return {
      topPlayers: [],
      topTeams: [],
      fastestMatches: [],
      stats: {
        matches: 0,
        players: 0,
        teams: 0,
        matchesTransform: 'scale(1)',
        playersTransform: 'scale(1)',
        teamsTransform: 'scale(1)'
      },
      aiQuery: '',
      aiResult: '',
      aiLoading: false
    };
  },
  mounted() {
    this.fetchFunData();
    this.fetchStats();
  },
  methods: {
    goToPlayers() {
      this.$router.push('/player');
    },
    goToMatches() {
      this.$router.push('/match');
    },
    goToTeams() {
      // 暂时跳转到战队列表页面，后续可以修改
      this.$router.push('/team');
    },
    submitAIQuery() {
      if (!this.aiQuery.trim()) {
        this.$message.warning('请输入查询内容');
        return;
      }
      
      this.aiLoading = true;
      this.aiResult = '';
      
      // 模拟AI查询过程
      setTimeout(() => {
        this.aiResult = '这是一个模拟的AI分析结果。在实际应用中，这里会显示基于您输入问题的数据分析结果。';
        this.aiLoading = false;
      }, 1500);
    },
    async fetchFunData() {
      try {
        // 获取参赛最多的选手TOP3
        const playersResponse = await fetch('/api/top-players');
        const playersResult = await playersResponse.json();
        if (playersResult.status === 'success') {
          this.topPlayers = playersResult.players || [];
        }

        // 获取胜率最高的战队TOP3
        const teamsResponse = await fetch('/api/top-teams');
        const teamsResult = await teamsResponse.json();
        if (teamsResult.status === 'success') {
          this.topTeams = teamsResult.teams || [];
        }

        // 获取结束最快的战斗TOP3
        const matchesResponse = await fetch('/api/fastest-matches');
        const matchesResult = await matchesResponse.json();
        if (matchesResult.status === 'success') {
          this.fastestMatches = matchesResult.matches || [];
        }
      } catch (error) {
        console.error('获取趣味数据失败:', error);
      }
    },
    async fetchStats() {
      try {
        const response = await fetch('/api/stats');
        const result = await response.json();
        
        if (result.status === 'success') {
          this.stats = result.stats;
        } else {
          console.error('获取统计数据失败:', result.msg);
          // 设置默认值以防API失败时显示0
          this.stats = {
            matches: 1247,
            players: 864,
            teams: 128
          };
        }
      } catch (error) {
        console.error('获取统计数据失败:', error);
        // API调用失败时使用模拟数据
        this.stats = {
          matches: 1247,
          players: 864,
          teams: 128
        };
      }
    },
    formatNumber(num) {
      // 直接返回完整数字，不再使用k或w的缩写形式
      // 确保返回的是格式化的数字字符串
      if (num === undefined || num === null) return '0';
      return num.toString();
    },
    enlargeNumber(event) {
      const statType = event.target.textContent.includes('比赛') ? 'matches' :
                      event.target.textContent.includes('选手') ? 'players' : 'teams';
      this.stats[`${statType}Transform`] = 'scale(1.1)';
    },
    resetNumber(event) {
      const statType = event.target.textContent.includes('比赛') ? 'matches' :
                      event.target.textContent.includes('选手') ? 'players' : 'teams';
      this.stats[`${statType}Transform`] = 'scale(1)';
    },
    getFullNumber(num) {
      return num.toLocaleString();
    },
    getRankClass(index) {
      if (index === 0) return 'first';
      if (index === 1) return 'second';
      if (index === 2) return 'third';
      return '';
    },
    formatGameTime(seconds) {
      if (!seconds) return '';
      const minutes = Math.floor(seconds / 60);
      const secs = seconds % 60;
      return `${minutes}分${secs}秒`;
    }
  }
}
</script>

<style scoped>
.home-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
  background: linear-gradient(135deg, #f5f7fa 0%, #e4edf9 100%);
  min-height: 100vh;
}

.welcome-card {
  margin-bottom: 20px;
  border-radius: 15px;
  background: linear-gradient(120deg, #ffffff, #f8f9ff);
  border: none;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
}

.welcome-header {
  background: linear-gradient(90deg, #4361ee, #3a0ca3);
  color: white;
  border-radius: 8px 8px 0 0;
  padding: 15px 20px;
}

.welcome-header h2 {
  margin: 0;
  font-weight: 600;
}

.welcome-text {
  font-size: 16px;
  color: #555;
  line-height: 1.6;
  margin: 20px 0;
  padding: 0 15px;
}

.stats-section {
  margin-bottom: 20px;
}

.stat-card {
  text-align: center;
  border-radius: 15px;
  background: linear-gradient(120deg, #ffffff, #f8f9ff);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
  border: none;
  height: 120px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  position: relative;
}

.stat-number {
  font-size: 32px;
  font-weight: 700;
  color: #4361ee;
  cursor: pointer;
  transition: all 0.3s ease;
  transform: scale(1);
}

.stat-number:hover {
  transform: scale(1.05);
}

.stat-label {
  font-size: 14px;
  color: #6c757d;
  margin-top: 5px;
}

.data-section {
  margin-bottom: 20px;
}

.data-card {
  height: 400px;
  border-radius: 15px;
  background: white;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
  border: none;
}

.data-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(90deg, #7209b7, #f72585);
  color: white;
  border-radius: 8px 8px 0 0;
  padding: 15px 20px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
}

.fun-data-list {
  padding: 20px 0;
}

.fun-data-item {
  display: flex;
  align-items: center;
  padding: 15px 20px;
  margin-bottom: 15px;
  border-radius: 8px;
  background: #f8f9fa;
  transition: all 0.3s;
}

.fun-data-item:hover {
  background: #e9ecef;
  transform: translateX(5px);
}

.fun-data-item.first {
  background: linear-gradient(90deg, #fff8e1, #ffecb3);
  border-left: 5px solid #ffc107;
}

.fun-data-item.second {
  background: linear-gradient(90deg, #e3f2fd, #bbdefb);
  border-left: 5px solid #2196f3;
}

.fun-data-item.third {
  background: linear-gradient(90deg, #fce4ec, #f8bbd0);
  border-left: 5px solid #e91e63;
}

.fun-data-item .rank {
  font-size: 20px;
  font-weight: bold;
  width: 30px;
  color: #6c757d;
}

.fun-data-item.first .rank {
  color: #ffc107;
}

.fun-data-item.second .rank {
  color: #2196f3;
}

.fun-data-item.third .rank {
  color: #e91e63;
}

.fun-data-item .name {
  flex: 1;
  font-size: 16px;
  font-weight: 500;
  color: #495057;
}

.fun-data-item .value {
  font-size: 16px;
  font-weight: bold;
  color: #4361ee;
}

/* AI查询窗口样式 */
.ai-card {
  height: 400px;
  border-radius: 15px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
  border: none;
  background: linear-gradient(120deg, #ffffff, #f8f9ff);
}

.ai-header {
  background: linear-gradient(90deg, #2a9d8f, #1d7874);
  color: white;
  border-radius: 8px 8px 0 0;
  padding: 15px 20px;
}

.ai-content {
  padding: 15px;
}

.ai-description {
  font-size: 14px;
  color: #666;
  margin-bottom: 15px;
  text-align: center;
}

.ai-input {
  margin-bottom: 15px;
}

.ai-button {
  width: 100%;
  background: linear-gradient(90deg, #2a9d8f, #1d7874);
  border: none;
}

.ai-result {
  margin-top: 15px;
  padding: 10px;
  background: #e8f4f3;
  border-radius: 8px;
  font-size: 14px;
}

.ai-result h4 {
  margin: 0 0 10px;
  color: #2a9d8f;
}

.quick-links {
  margin-bottom: 20px;
}

.link-card {
  cursor: pointer;
  text-align: center;
  transition: all 0.3s;
  height: 180px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 15px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
}

.link-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.25) !important;
}

.link-icon {
  font-size: 48px;
  margin-bottom: 15px;
}

.link-card h3 {
  margin: 0 0 10px;
  font-size: 22px;
  font-weight: 600;
}

.link-card p {
  margin: 0;
  font-size: 14px;
  opacity: 0.9;
}

.about-section {
  margin-top: 20px;
}

.about-card {
  border-radius: 15px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
  border: none;
  background: linear-gradient(120deg, #ffffff, #f8f9ff);
}

.about-card:hover {
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.15) !important;
}

.about-link {
  display: flex;
  align-items: center;
  text-decoration: none;
  color: inherit;
  padding: 20px;
}

.about-image {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  margin-right: 20px;
  border: 3px solid #4361ee;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.about-text h3 {
  margin: 0 0 10px;
  color: #333;
  font-size: 22px;
  font-weight: 600;
}

.about-text p {
  margin: 10px 0;
  color: #666;
  font-size: 16px;
}

.social-links {
  margin-top: 15px;
}

.social-links .el-button {
  margin-right: 10px;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .home-container {
    padding: 10px;
  }
  
  .welcome-stats {
    padding: 15px 5px;
  }
  
  .stat-number {
    font-size: 24px;
  }
  
  .about-link {
    flex-direction: column;
    text-align: center;
  }
  
  .about-image {
    margin-right: 0;
    margin-bottom: 15px;
  }
  
  /* 在小屏幕上将双列布局改为单列 */
  .data-section .el-col {
    width: 100%;
    margin-bottom: 20px;
  }
}
</style>