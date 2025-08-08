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
      <el-table :data="players" style="width: 100%" stripe v-else class="player-match-table">
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

<style lang="scss" scoped>
@import '@/assets/styles/_variables.scss';
@import '@/assets/styles/mixins';

.player-match-table {
  background-color: rgba($lol-card-bg, 0.7);
  border: 1px solid rgba($lol-secondary, 0.2);
  border-radius: $border-radius;
  margin-top: $spacing-medium;
  
  /deep/ th {
    background-color: rgba($lol-primary, 0.2) !important;
    color: $lol-secondary;
    font-weight: bold;
    border-bottom: 1px solid rgba($lol-secondary, 0.2);
  }
  
  /deep/ tr {
    background-color: rgba($lol-card-bg, 0.5);
    color: $lol-text;
    
    &:hover {
      background-color: rgba($lol-primary, 0.1) !important;
    }
  }
  
  /deep/ .el-table__row--striped {
    background-color: rgba($lol-card-bg, 0.3) !important;
  }
  
  /deep/ .el-tag {
    border: none;
    font-weight: bold;
    
    &.el-tag--success {
      background-color: rgba($lol-success, 0.2);
      color: $lol-success;
    }
    
    &.el-tag--danger {
      background-color: rgba($lol-danger, 0.2);
      color: $lol-danger;
    }
  }
  
  /deep/ .el-button {
    background-color: rgba($lol-secondary, 0.1);
    border-color: rgba($lol-secondary, 0.3);
    color: $lol-secondary;
    
    &:hover {
      background-color: rgba($lol-secondary, 0.2);
    }
  }
}

.player-detail-container {
  padding: $spacing-medium;
  max-width: 1200px;
  margin: 0 auto;
}

.welcome-card {
  @include lol-card;
  margin-bottom: $spacing-medium;
  background: linear-gradient(120deg, rgba($lol-card-bg, 0.9), rgba($lol-card-bg, 0.7));
  border: 1px solid rgba($lol-secondary, 0.2);
}

.welcome-header {
  background: linear-gradient(90deg, $lol-primary, darken($lol-primary, 10%));
  color: $lol-secondary;
  border-radius: 8px 8px 0 0;
  padding: $spacing-small $spacing-medium;
}

.welcome-header h2 {
  margin: 0;
  font-weight: 600;
  font-family: 'BeaufortforLOL', sans-serif;
}

.welcome-text {
  font-size: 16px;
  color: $lol-text;
  line-height: 1.6;
  margin: $spacing-medium 0;
  padding: 0 $spacing-small;
}

.el-page-header {
  margin-bottom: $spacing-medium;
}

/* 移动端样式 */
.mobile-view {
  display: flex;
  flex-direction: column;
  gap: $spacing-small;
}

.match-card {
  @include lol-card;
  cursor: pointer;
  background-color: rgba($lol-card-bg, 0.8);
  border: 1px solid rgba($lol-secondary, 0.2);
  transition: all 0.3s ease;
  
  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba($lol-primary, 0.15);
  }
  
  /deep/ .el-card__body {
    padding: $spacing-small;
  }
}

.match-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: $spacing-small;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba($lol-secondary, 0.2);
}

.match-date {
  font-weight: bold;
  color: $lol-secondary;
}

.match-content {
  margin-bottom: $spacing-small;
}

.hero-info, .kda-info {
  margin-bottom: 5px;
  font-size: 14px;
  color: $lol-text;
}

.detail-button {
  width: 100%;
}

/* 移动端适配 */
@include mobile {
  .player-detail-container {
    padding: $spacing-small;
  }
  
  .welcome-card {
    margin-bottom: $spacing-small;
  }
  
  .welcome-header {
    padding: 10px $spacing-small;
    
    h2 {
      font-size: 20px;
    }
  }
  
  .welcome-text {
    font-size: 14px;
    margin: $spacing-small 0;
    padding: 0 8px;
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
    padding: $spacing-small;
  }
  
  .hero-info, .kda-info {
    font-size: 12px;
  }
}
</style>