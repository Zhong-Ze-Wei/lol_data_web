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

    <!-- 数据区域 - AI查询和趣味数据放在同一行 -->
    <el-row :gutter="20" class="data-section">
      <!-- AI问答功能 - 左侧 -->
      <el-col :span="12">
        <el-card class="ai-card" shadow="hover">
          <div slot="header" class="ai-header">
            <span class="section-title">🤖 AI智能问答</span>
          </div>
          <div class="ai-content">
            <p class="ai-description">智能分析赛事数据，提供实时流式回答</p>
            <el-input
              type="textarea"
              :rows="1"
              placeholder="请输入您的问题..."
              v-model="aiQuery"
              class="ai-input"
              @keyup.enter.native="submitAIQuery"
            ></el-input>
            <div class="ai-buttons">
              <el-button 
                type="primary" 
                class="ai-button"
                @click="submitAIQuery"
                :loading="aiLoading"
              >
                {{ aiLoading ? '思考中...' : '发送问题' }}
              </el-button>
              <el-button 
                type="info" 
                class="ai-clear-button"
                @click="clearAIChat"
                :disabled="aiLoading || (!aiResult && !aiStreaming)"
              >
                清空对话
              </el-button>
            </div>
            <div v-if="aiResult || aiStreaming" class="ai-result-container">
              <div class="ai-result">
                <h4>AI回答：</h4>
                <!-- 使用v-html确保链接可以被正确渲染 -->
                <p v-html="formattedAIResult"></p>
                <div v-if="aiStreaming" class="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
      
      <!-- 趣味数据 - 右侧 -->
      <el-col :span="12">
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
                  <div class="value">{{ formatGameTime(match.game_time) }}<br><small>{{ formatDate(match.date) }}</small></div>
                </div>
              </div>
            </el-tab-pane>
            <!-- 新增最长比赛时间TOP3 -->
            <el-tab-pane label="最长比赛">
              <div class="fun-data-list">
                <div 
                  v-for="(match, index) in longestMatches" 
                  :key="match.id"
                  class="fun-data-item"
                  :class="getRankClass(index)"
                >
                  <div class="rank">{{ index + 1 }}</div>
                  <div class="name">{{ match.blue_team_name }} vs {{ match.red_team_name }}</div>
                  <div class="value">{{ formatGameTime(match.game_time) }}<br><small>{{ formatDate(match.date) }}</small></div>
                </div>
              </div>
            </el-tab-pane>
            <!-- 新增单场击杀最多选手TOP3 -->
            <el-tab-pane label="击杀榜">
              <div class="fun-data-list">
                <div 
                  v-for="(player, index) in topKills" 
                  :key="player.name"
                  class="fun-data-item"
                  :class="getRankClass(index)"
                >
                  <div class="rank">{{ index + 1 }}</div>
                  <div class="name">{{ player.name }} ({{ player.team_name }})</div>
                  <div class="value">{{ player.kills }} 杀 ({{ player.hero }})</div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
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
  computed: {
  formattedAIResult() {
    if (!this.aiResult) return '';

    try {
      // 尝试解析JSON
      const result = typeof this.aiResult === 'string' ? JSON.parse(this.aiResult) : this.aiResult;

      // 只返回answer字段
      if (result && result.answer) {
        // 处理选手链接
        let answer = result.answer;

        // 如果有data数据，为选手名添加链接
        if (result.data && result.data.length > 0) {
          result.data.forEach(player => {
            if (player.id && player.name) {
              // 将选手名替换为带链接的版本(使用选手名而非ID)
              const playerLink = `<a href="/player/${encodeURIComponent(player.name)}" class="player-link">${player.name}</a>`;
              answer = answer.replace(new RegExp(player.name, 'g'), playerLink);
            }
          });
        }

        return answer;
      }

      // 如果没有answer字段，返回原始结果的字符串表示
      return typeof result === 'string' ? result : JSON.stringify(result);
    } catch (e) {
      // 如果解析失败，直接返回原始字符串
      return this.aiResult;
    }
  }
},
  data() {
    return {
      topPlayers: [],
      topTeams: [],
      fastestMatches: [],
      // 新增数据
      longestMatches: [],
      topKills: [],
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
      aiLoading: false,
      aiStreaming: false,
      streamInterval: null
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
    clearAIChat() {
      // 清空对话
      this.aiQuery = '';
      this.aiResult = '';
      this.aiStreaming = false;
      clearInterval(this.streamInterval);
    },
    
    async submitAIQuery() {
      if (!this.aiQuery.trim()) {
        this.$message.warning('请输入问题内容');
        return;
      }
      
      // 清除之前的结果和定时器
      this.aiLoading = true;
      this.aiResult = '';
      this.aiStreaming = true;
      clearInterval(this.streamInterval);
      
      try {
        console.log('发送AI查询:', this.aiQuery);
        
        // 调用后端AI接口
        const response = await fetch('/api/ai/query', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ prompt: this.aiQuery })
        });
        
        console.log('API响应状态:', response.status);
        
        if (!response.ok) {
          const errorText = await response.text();
          console.error('API错误响应:', errorText);
          throw new Error(`HTTP error! Status: ${response.status}, Details: ${errorText}`);
        }
        
        const data = await response.json();
        console.log('API响应数据:', data);
        
        // 检查API返回的结果
        if (data.result && data.result.error) {
          // 如果有错误，直接显示错误信息
          console.error('API返回错误:', data.result.error);
          this.aiResult = `抱歉，处理您的问题时出现了错误：\n${data.result.error}\n\n请尝试重新提问或使用不同的问题表述。`;
          this.aiLoading = false;
          this.aiStreaming = false;
          return;
        }
        
        // 获取API返回的结果
        const apiResult = data.result;
        console.log('处理后的API结果:', apiResult);
        
        // 只保存API结果对象，不转换为字符串
        this.aiResult = apiResult;
        
        // 将answer部分分成多个部分，模拟流式输出
        const answerText = apiResult && apiResult.answer ? apiResult.answer : '抱歉，无法获取有效的回答。';
        const chunks = this.chunkText(answerText);
        
        let currentIndex = 0;
        let currentText = '';
        
        // 延迟一段时间后开始流式输出
        setTimeout(() => {
          this.aiLoading = false;
          
          // 使用setInterval模拟流式输出
          this.streamInterval = setInterval(() => {
            if (currentIndex < chunks.length) {
              currentText += chunks[currentIndex];
              // 只更新answer部分，保留完整的apiResult对象
              this.aiResult = {
                ...apiResult,
                answer: currentText
              };
              currentIndex++;
              
              // 自动滚动到AI回答区域
              this.$nextTick(() => {
                const resultContainer = document.querySelector('.ai-result-container');
                if (resultContainer) {
                  resultContainer.scrollTop = resultContainer.scrollHeight;
                }
              });
            } else {
              // 输出完成后清除定时器
              clearInterval(this.streamInterval);
              this.aiStreaming = false;
            }
          }, 100); // 每100毫秒添加一段文本，使输出更流畅
        }, 500);
      } catch (error) {
        console.error('AI查询失败:', error);
        this.aiResult = {
          answer: `抱歉，查询过程中出现了错误：${error.message}`,
          data: [],
          question: this.aiQuery,
          sql: ''
        };
        this.aiLoading = false;
        this.aiStreaming = false;
      }
    },
    
    // 将文本分成小块，用于模拟流式输出
    chunkText(text) {
      // 如果文本很短，直接返回
      if (text.length < 50) return [text];
      
      const chunks = [];
      // 不再添加开场白，直接进入正文
      
      // 按句子或段落分割文本
      const sentences = text.split(/(?<=[.!?。！？])\s+/);
      
      for (const sentence of sentences) {
        if (sentence.trim()) {
          // 如果句子很长，进一步分割
          if (sentence.length > 100) {
            const parts = this.splitLongSentence(sentence);
            chunks.push(...parts);
          } else {
            chunks.push(sentence + " ");
          }
        }
      }
      
      return chunks;
    },
    
    // 分割长句子
    splitLongSentence(sentence) {
      const parts = [];
      let currentPart = "";
      const words = sentence.split(" ");
      
      for (const word of words) {
        if (currentPart.length + word.length > 50) {
          parts.push(currentPart);
          currentPart = word + " ";
        } else {
          currentPart += word + " ";
        }
      }
      
      if (currentPart) {
        parts.push(currentPart);
      }
      
      return parts;
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

        // 获取结束最慢的战斗TOP3（新增）
        const longestMatchesResponse = await fetch('/api/longest-matches');
        const longestMatchesResult = await longestMatchesResponse.json();
        if (longestMatchesResult.status === 'success') {
          this.longestMatches = longestMatchesResult.matches || [];
        }

        // 获取单场击杀数最高的TOP3选手（新增）
        const topKillsResponse = await fetch('/api/top-kills');
        const topKillsResult = await topKillsResponse.json();
        if (topKillsResult.status === 'success') {
          this.topKills = topKillsResult.players || [];
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
    },

    formatDate(dateString) {
      if (!dateString) return '';
      const date = new Date(dateString);
      return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
    }
  }
}
</script>

<style scoped>
.home-container {
  padding: 10px;
  max-width: 1200px;
  margin: -20px auto 0; /* 使页面整体上移 */
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
  height: 520px;
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
  height: 520px; /* 进一步增加卡片高度 */
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


.ai-description {
  font-size: 20px;
  color: #666;
  margin-bottom: 10px; /* 减少下边距 */
  text-align: center;
}

.player-link {
  color: #409EFF;
  text-decoration: none;
  font-weight: 500;
}

.player-link:hover {
  text-decoration: underline;
}

.ai-input {
  margin-bottom: 15px;
}

.ai-button {
  width: 100%;
  background: linear-gradient(90deg, #2a9d8f, #1d7874);
  border: none;
}

.ai-result-container {
  max-height: 280px; /* 进一步增加结果容器高度 */
  overflow-y: auto;
  margin-top: 5px; /* 减少顶部边距 */
}

.ai-result {
  margin-top: 10px;
  padding: 10px;
  background: #e8f4f3;
  border-radius: 8px;
  font-size: 14px;
}

/* 打字指示器动画 */
.typing-indicator {
  display: flex;
  padding: 6px 0;
}

.typing-indicator span {
  height: 8px;
  width: 8px;
  margin: 0 2px;
  background-color: #2a9d8f;
  border-radius: 50%;
  display: inline-block;
  animation: typing 1.4s infinite ease-in-out both;
}

.typing-indicator span:nth-child(1) {
  animation-delay: -0.32s;
}

.typing-indicator span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes typing {
  0%, 80%, 100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
  }
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