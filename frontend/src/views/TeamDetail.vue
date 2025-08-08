<template>
  <div class="team-detail-container" v-loading="loading">
    <el-page-header @back="goBack" content="战队详情"></el-page-header>

    <div v-if="!loading && team">
      <!-- 标题和欢迎信息 -->
      <el-row :gutter="20">
        <el-col :span="24">
          <el-card class="welcome-card" shadow="hover">
            <div slot="header" class="welcome-header">
              <h2>🏆 战队详情</h2>
            </div>
            <p class="welcome-text">{{ team.team_name }} 的详细信息和战队成员列表。</p>
          </el-card>
        </el-col>
      </el-row>

      <div class="page-header">
        <h1 class="page-title">{{ team.team_name }}</h1>
      </div>

      <el-row :gutter="20" class="team-info-container">
        <el-col :span="12">
          <el-card class="team-stats-card">
            <div slot="header" class="stats-header">
              <h3>基本信息</h3>
            </div>

            <div class="team-basic-info">
              <el-row>
                <el-col :span="12">
                  <p><strong>战队名称:</strong> {{ team.team_name }}</p>
                </el-col>
              </el-row>

              <el-row>
                <el-col :span="12">
                  <p><strong>比赛场次:</strong> {{ team.matches_count }}</p>
                </el-col>
                <el-col :span="12">
                  <p><strong>胜率:</strong> {{ team.win_rate }}%</p>
                </el-col>
              </el-row>
            </div>
          </el-card>
        </el-col>

        <el-col :span="12">
          <el-card class="team-logo-card">
            <div slot="header" class="logo-header">
              <h3>战队Logo</h3>
            </div>

            <div class="team-logo-container">
              <el-image
                :src="team.logo || noPhotoImage"
                class="team-logo"
                fit="cover"
              >
                <div slot="error" class="image-slot">
                  <i class="el-icon-picture-outline"></i>
                </div>
              </el-image>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="20" class="team-stats-container">
        <el-col :span="24">
          <el-card class="team-detailed-stats">
            <div slot="header" class="detailed-stats-header">
              <h3>战队成员</h3>
            </div>

            <el-table :data="team.players" style="width: 100%" stripe>
              <el-table-column prop="player_name" label="选手名称">
                <template slot-scope="scope">
                  <span class="player-name">{{ scope.row.player_name }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="position" label="位置" width="120">
                <template slot-scope="scope">
                  <el-tag :type="getPositionTagType(scope.row.position)">
                    {{ positionMapping[scope.row.position] }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template slot-scope="scope">
                  <el-button
                    size="mini"
                    type="primary"
                    @click="goToPlayerDetail(scope.row.player_name)"
                  >
                    查看详情
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <el-empty v-else-if="!loading" description="没有找到战队数据"></el-empty>
  </div>
</template>

<script>
import noPhotoImage from '@/assets/no_photo.png';

export default {
  name: 'TeamDetail',
  data() {
    return {
      noPhotoImage,
      teamName: '',
      team: null,
      loading: true,
      positionMapping: {
        'top': '上单',
        'jungle': '打野',
        'mid': '中单',
        'adc': '射手',
        'support': '辅助'
      },
      positionTagTypes: {
        'top': 'primary',
        'jungle': 'success',
        'mid': 'warning',
        'adc': 'danger',
        'support': 'info'
      }
    }
  },
  mounted() {
    this.teamName = this.$route.params.team_name;
    this.fetchTeamDetail();
  },
  methods: {
    async fetchTeamDetail() {
      this.loading = true;
      try {
        const response = await fetch(`/team/api/${encodeURIComponent(this.teamName)}`);
        const data = await response.json();

        if (data.error) {
          this.$message.error(data.error);
          return;
        }

        this.team = data;
      } catch (error) {
        this.$message.error('获取战队数据失败');
        console.error(error);
      } finally {
        this.loading = false;
      }
    },
    goBack() {
      this.$router.go(-1);
    },
    getPositionTagType(position) {
      return this.positionTagTypes[position] || 'info';
    },
    goToPlayerDetail(playerName) {
      this.$router.push(`/player/${playerName}`);
    }
  }
}
</script>

<style scoped>
.team-detail-container {
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

.team-header {
  text-align: center;
  margin-bottom: 30px;
  padding: 20px;
  background: linear-gradient(120deg, #e0f7fa, #bbdefb);
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.team-title {
  margin: 10px 0;
  font-size: 28px;
  color: #0d47a1;
  font-weight: bold;
}

.team-info-container {
  margin-bottom: 20px;
}

.team-stats-card, .team-logo-card {
  margin-bottom: 20px;
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.stats-header h3, .logo-header h3, .detailed-stats-header h3 {
  margin: 0;
  text-align: center;
  color: #1976d2;
}

.team-basic-info {
  padding: 20px;
}

.team-basic-info p {
  font-size: 16px;
  margin: 10px 0;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.team-basic-info p:last-child {
  border-bottom: none;
}

.team-basic-info strong {
  color: #1976d2;
}

.team-logo-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
}

.team-logo {
  width: 200px;
  height: 200px;
  border-radius: 50%;
  border: 3px solid #1976d2;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.image-slot {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 200px;
  height: 200px;
  background: #f5f7fa;
  color: #909399;
  font-size: 48px;
  border-radius: 50%;
}

.team-detailed-stats {
  margin-bottom: 20px;
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.detailed-stats-header {
  background: linear-gradient(90deg, #1976d2, #42a5f5);
  color: white;
  border-radius: 8px 8px 0 0;
  padding: 15px 20px;
}

.player-name {
  font-weight: bold;
  color: #1976d2;
  cursor: pointer;
}

.player-name:hover {
  text-decoration: underline;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .team-detail-container {
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

  .team-header {
    padding: 15px;
    margin-bottom: 20px;
  }

  .team-title {
    font-size: 24px;
  }

  .team-basic-info {
    padding: 15px;
  }

  .team-basic-info p {
    font-size: 14px;
  }

  .team-logo {
    width: 150px;
    height: 150px;
  }

  .image-slot {
    width: 150px;
    height: 150px;
    font-size: 36px;
  }
}

@media (max-width: 480px) {
  .welcome-header h2 {
    font-size: 18px;
  }

  .welcome-text {
    font-size: 13px;
  }

  .team-title {
    font-size: 20px;
  }

  .team-basic-info {
    padding: 10px;
  }

  .team-basic-info p {
    font-size: 13px;
  }

  .team-logo {
    width: 120px;
    height: 120px;
  }

  .image-slot {
    width: 120px;
    height: 120px;
    font-size: 28px;
  }
}
</style>