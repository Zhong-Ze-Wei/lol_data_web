<template>
  <div class="player-detail-container" v-loading="loading">
    <el-page-header @back="goBack" :content="playerName + ' 的比赛记录'"></el-page-header>

    <div v-if="!loading && players.length > 0">
      <!-- 标题和欢迎信息 -->
      <el-row :gutter="20">
        <el-col :span="24">
          <el-card class="welcome-card" shadow="hover">
            <div slot="header" class="welcome-header">
              <h2>🏆 选手比赛记录</h2>
            </div>
            <p class="welcome-text">{{ playerName }} 参与的所有比赛记录和数据表现。</p>
          </el-card>
        </el-col>
      </el-row>

      <div class="page-header">
        <h1 class="page-title">{{ playerName }} 的比赛记录</h1>
      </div>
      <!-- 在移动端使用卡片形式展示 -->
      <div class="mobile-view" v-if="$isMobile">
        <el-card 
          v-for="player in players" 
          :key="player.match_id" 
          class="match-card"
          @click.native="viewMatchDetail(player.match_id)"
        >
          <div class="match-header">
            <div class="match-date">{{ player.date }}</div>
            <el-tag :type="player.result === '1' ? 'success' : 'danger'" size="mini">
              {{ player.result === '1' ? '胜' : '负' }}
            </el-tag>
          </div>
          <div class="match-content">
            <div class="hero-info">
              <strong>英雄:</strong> {{ player.hero }}
            </div>
            <div class="kda-info">
              <strong>KDA:</strong> {{ player.kda }} ({{ player.kills }}/{{ player.deaths }}/{{ player.assists }})
            </div>
          </div>
          <el-button 
            size="mini" 
            type="primary" 
            class="detail-button"
            @click.stop="viewMatchDetail(player.match_id)"
          >
            查看详情
          </el-button>
        </el-card>
      </div>
      
      <!-- 在桌面端使用表格形式展示 -->
      <el-table :data="players" style="width: 100%" stripe v-else>
        <el-table-column prop="date" label="比赛日期" width="120"></el-table-column>
        <el-table-column prop="hero" label="英雄"></el-table-column>
        <el-table-column prop="kda" label="KDA"></el-table-column>
        <el-table-column prop="kills" label="击杀"></el-table-column>
        <el-table-column prop="deaths" label="死亡"></el-table-column>
        <el-table-column prop="assists" label="助攻"></el-table-column>
        <el-table-column label="结果" width="80">
          <template slot-scope="scope">
            <el-tag :type="scope.row.result === '1' ? 'success' : 'danger'">
              {{ scope.row.result === '1' ? '胜' : '负' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template slot-scope="scope">
            <el-button
              size="mini"
              @click="viewMatchDetail(scope.row.match_id)"
            >
              查看详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-empty v-else-if="!loading" description="没有找到该选手参与的比赛"></el-empty>
  </div>
</template>

<script>
export default {
  name: 'PlayerDetail',
  data() {
    return {
      playerName: '',
      players: [],
      loading: true
    }
  },
  computed: {
    $isMobile() {
      return window.innerWidth < 768;
    }
  },
  mounted() {
    this.playerName = this.$route.params.name;
    this.fetchPlayerMatches();
  },
  methods: {
    async fetchPlayerMatches() {
      this.loading = true;
      try {
        const response = await fetch(`/player/api/${this.playerName}`);
        const data = await response.json();

        if (data.error) {
          this.$message.error(data.error);
          return;
        }

        this.players = data.players;
      } catch (error) {
        this.$message.error('获取选手数据失败');
        console.error(error);
      } finally {
        this.loading = false;
      }
    },
    goBack() {
      this.$router.go(-1);
    },
    viewMatchDetail(matchId) {
      this.$router.push(`/match/${matchId}`);
    }
  }
}
</script>

<style scoped>
.player-detail-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
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

.el-page-header {
  margin-bottom: 20px;
}

/* 移动端样式 */
.mobile-view {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.match-card {
  cursor: pointer;
  transition: all 0.3s;
}

.match-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.match-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #eee;
}

.match-date {
  font-weight: bold;
  color: #333;
}

.match-content {
  margin-bottom: 15px;
}

.hero-info, .kda-info {
  margin-bottom: 5px;
  font-size: 14px;
}

.detail-button {
  width: 100%;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .player-detail-container {
    padding: 10px;
  }
  
  .welcome-card {
    margin-bottom: 15px;
    border-radius: 10px;
  }
  
  .welcome-header {
    padding: 12px 15px;
  }
  
  .welcome-header h2 {
    font-size: 20px;
  }
  
  .welcome-text {
    font-size: 14px;
    margin: 15px 0;
    padding: 0 10px;
  }
  
  .match-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 5px;
  }
  
  .hero-info, .kda-info {
    font-size: 13px;
  }
}

@media (max-width: 480px) {
  .welcome-header h2 {
    font-size: 18px;
  }
  
  .welcome-text {
    font-size: 13px;
  }
  
  .player-detail-container {
    padding: 5px;
  }
  
  .match-card {
    padding: 10px;
  }
  
  .hero-info, .kda-info {
    font-size: 12px;
  }
}
</style>