<template>
  <div class="match-detail-container" v-loading="loading">
    <el-page-header @back="goBack" :content="matchTitle"></el-page-header>

    <div v-if="!loading && match">
      <div class="match-header">
        <h2 class="match-title">{{ match.red_team_name }} vs {{ match.blue_team_name }}</h2>
        <p class="match-date">{{ match.date }}</p>
        <p class="match-duration">比赛时长: {{ formatGameTime(match.game_time) }} | MVP: {{ match.mvp }}</p>
      </div>

      <el-row :gutter="20" class="teams-container">
        <!-- 红方 -->
        <el-col :span="12">
          <el-card class="team-card red-team">
            <div slot="header" class="team-header">
              <h3>{{ redTeam.team_name }} 选手</h3>
            </div>

            <div class="team-stats">
              <el-row>
                <el-col :span="12">
                  <p><strong>总击杀:</strong> {{ redTeam.kill }} | <strong>总死亡:</strong> {{ redTeam.death }}</p>
                </el-col>
                <el-col :span="12">
                  <p><strong>经济:</strong> {{ redTeam.money }} | <strong>推塔:</strong> {{ redTeam.tower }}</p>
                </el-col>
              </el-row>
            </div>

            <div
              v-for="player in getPlayersByTeam(match.players, redTeam.team_name)"
              :key="player.name"
              class="player-card"
            >
              <el-row>
                <el-col :span="6">
                  <el-image
                    :src="player.pic || noPhotoImage"
                    class="player-img clickable"
                    fit="cover"
                    @click="goToPlayerDetail(player.name)"
                  >
                    <div slot="error" class="image-slot">
                      <i class="el-icon-user-solid"></i>
                    </div>
                  </el-image>
                </el-col>
                <el-col :span="18">
                  <h4 class="clickable" @click="goToPlayerDetail(player.name)">{{ player.name }}（{{ positionMapping[player.position] }}）</h4>
                  <p><strong>英雄:</strong> {{ player.hero }}（等级: {{ player.hero_lv }}）</p>
                  <p><strong>KDA:</strong> {{ player.kda }}（{{ player.kills }}/{{ player.deaths }}/{{ player.assists }}） | <strong>参团率:</strong> {{ player.part }}</p>
                  <p><strong>经济:</strong> {{ player.money }} | <strong>补刀:</strong> {{ player.hits }}</p>
                  <p><strong>输出伤害:</strong> {{ player.atk }}（占比: {{ player.atk_p }}，分均: {{ player.atk_m }}）</p>
                  <p><strong>承受伤害:</strong> {{ player.def_ }}（占比: {{ player.def_p }}，分均: {{ player.def_m }}）</p>
                </el-col>
              </el-row>
            </div>
          </el-card>
        </el-col>

        <!-- 蓝方 -->
        <el-col :span="12">
          <el-card class="team-card blue-team">
            <div slot="header" class="team-header">
              <h3>{{ blueTeam.team_name }} 选手</h3>
            </div>

            <div class="team-stats">
              <el-row>
                <el-col :span="12">
                  <p><strong>总击杀:</strong> {{ blueTeam.kill }} | <strong>总死亡:</strong> {{ blueTeam.death }}</p>
                </el-col>
                <el-col :span="12">
                  <p><strong>经济:</strong> {{ blueTeam.money }} | <strong>推塔:</strong> {{ blueTeam.tower }}</p>
                </el-col>
              </el-row>
            </div>

            <div
              v-for="player in getPlayersByTeam(match.players, blueTeam.team_name)"
              :key="player.name"
              class="player-card"
            >
              <el-row>
                <el-col :span="6">
                  <el-image
                    :src="player.pic || noPhotoImage"
                    class="player-img clickable"
                    fit="cover"
                    @click="goToPlayerDetail(player.name)"
                  >
                    <div slot="error" class="image-slot">
                      <i class="el-icon-user-solid"></i>
                    </div>
                  </el-image>
                </el-col>
                <el-col :span="18">
                  <h4 class="clickable" @click="goToPlayerDetail(player.name)">{{ player.name }}（{{ positionMapping[player.position] }}）</h4>
                  <p><strong>英雄:</strong> {{ player.hero }}（等级: {{ player.hero_lv }}）</p>
                  <p><strong>KDA:</strong> {{ player.kda }}（{{ player.kills }}/{{ player.deaths }}/{{ player.assists }}） | <strong>参团率:</strong> {{ player.part }}</p>
                  <p><strong>经济:</strong> {{ player.money }} | <strong>补刀:</strong> {{ player.hits }}</p>
                  <p><strong>输出伤害:</strong> {{ player.atk }}（占比: {{ player.atk_p }}，分均: {{ player.atk_m }}）</p>
                  <p><strong>承受伤害:</strong> {{ player.def_ }}（占比: {{ player.def_p }}，分均: {{ player.def_m }}）</p>
                </el-col>
              </el-row>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <el-empty v-else-if="!loading" description="没有找到比赛数据"></el-empty>
  </div>
</template>

<script>
import noPhotoImage from '@/assets/no_photo.png';

export default {
  name: 'MatchDetail',
  data() {
    return {
      noPhotoImage,
      matchId: 0,
      match: null,
      loading: true,
      positionMapping: {
        'a': '上单',
        'b': '打野',
        'c': '中单',
        'd': 'ADC',
        'e': '辅助'
      }
    }
  },
  computed: {
    matchTitle() {
      if (!this.match) return '比赛详情';
      return `${this.match.red_team_name} vs ${this.match.blue_team_name}`;
    },
    redTeam() {
      return this.match ? this.match.red_team : {};
    },
    blueTeam() {
      return this.match ? this.match.blue_team : {};
    }
  },
  mounted() {
    this.matchId = parseInt(this.$route.params.match_id);
    this.fetchMatchDetail();
  },
  methods: {
    async fetchMatchDetail() {
      this.loading = true;
      try {
        const response = await fetch(`/match/api/${this.matchId}`);
        const data = await response.json();

        if (data.error) {
          this.$message.error(data.error);
          return;
        }

        this.match = data;
      } catch (error) {
        this.$message.error('获取比赛数据失败');
        console.error(error);
      } finally {
        this.loading = false;
      }
    },
    goBack() {
      this.$router.go(-1);
    },
    formatGameTime(seconds) {
      if (!seconds) return '';
      const minutes = Math.floor(seconds / 60);
      const secs = seconds % 60;
      return `${minutes}分${secs}秒`;
    },
    getPlayersByTeam(players, teamName) {
      return players.filter(player => player.team_name === teamName);
    },
    goToPlayerDetail(name) {
      // 使用正确的路由参数名和格式
      this.$router.push(`/player/${encodeURIComponent(name)}`);
    }
  }
}
</script>

<style scoped>
.match-detail-container {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.match-header {
  text-align: center;
  margin-bottom: 30px;
}

.match-title {
  margin: 10px 0;
  font-size: 24px;
}

.match-date, .match-duration {
  color: #666;
  margin: 5px 0;
}

.teams-container {
  margin-top: 20px;
}

.team-card {
  margin-bottom: 20px;
}

.team-card.red-team {
  border-color: #F56C6C;
}

.team-card.blue-team {
  border-color: #409EFF;
}

.team-header h3 {
  margin: 0;
  text-align: center;
}

.team-stats {
  margin-bottom: 20px;
  padding: 10px;
  background-color: #f5f7fa;
  border-radius: 4px;
}

.player-card {
  padding: 15px;
  border: 1px solid #EBEEF5;
  border-radius: 4px;
  margin-bottom: 15px;
  background-color: #fff;
}

.player-card:last-child {
  margin-bottom: 0;
}

.player-img {
  width: 80px;
  height: 80px;
  border-radius: 50%;
}

.image-slot {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background: #f5f7fa;
  color: #909399;
  font-size: 30px;
}

.clickable {
  cursor: pointer;
}

.clickable:hover {
  color: #409EFF;
  text-decoration: underline;
}
</style>
