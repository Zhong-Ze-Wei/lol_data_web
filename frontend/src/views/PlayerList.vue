<template>
  <div class="player-list-container">
    <!-- 标题和欢迎信息 -->
    <el-row :gutter="20">
      <el-col :span="24">
        <el-card class="welcome-card" shadow="hover">
          <div slot="header" class="welcome-header">
            <h2>🏆 选手展示</h2>
          </div>
          <p class="welcome-text">在这里您可以查看所有职业选手的信息，通过筛选条件查找您感兴趣的选手。</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选表单 -->
    <div class="filter-form">
      <el-form :inline="true" :model="filterForm" class="filter-form-inline">
        <div class="form-row">
          <el-form-item label="战队名称">
            <el-input
              v-model="filterForm.team_name"
              placeholder="请输入战队名称"
              clearable
            />
          </el-form-item>

          <el-form-item label="分路">
            <el-select v-model="filterForm.position" placeholder="选择分路" clearable>
              <el-option label="上单" value="a"></el-option>
              <el-option label="打野" value="b"></el-option>
              <el-option label="中单" value="c"></el-option>
              <el-option label="ADC" value="d"></el-option>
              <el-option label="辅助" value="e"></el-option>
            </el-select>
          </el-form-item>
        </div>

        <el-form-item>
          <el-button type="primary" @click="fetchPlayers">筛选</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 选手列表展示 -->
    <div class="player-grid">
      <el-card
        v-for="player in players"
        :key="player.name"
        class="player-card"
        @click.native="goToPlayerDetail(player.name)"
      >
        <div class="player-card-content">
          <el-image
            :src="player.pic || noPhotoImage"
            class="player-img"
            fit="cover"
            :alt="player.name + '头像'"
            lazy
          >
            <div slot="placeholder" class="image-slot">
              <i class="el-icon-loading"></i>
            </div>
            <div slot="error" class="image-slot">
              <i class="el-icon-user-solid"></i>
            </div>
          </el-image>

          <div class="player-info">
            <h3>{{ player.name }}</h3>
            <p>战队：{{ player.team_name }}</p>
            <p>分路：{{ positionMapping[player.position] }}</p>
            <p>最近比赛：{{ player.latest_date }}</p>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 分页 -->
    <div class="pagination-container" v-if="pagination.pages > 1">
      <el-pagination
        @current-change="handlePageChange"
        :current-page="pagination.page"
        :page-count="pagination.pages"
        layout="prev, pager, next"
        background
      />
    </div>
  </div>
</template>

<script>
export default {
  name: 'PlayerList',
  data() {
    return {
      filterForm: {
        team_name: '',
        position: ''
      },
      players: [],
      pagination: {
        page: 1,
        pages: 1,
        has_prev: false,
        has_next: false
      },
      positionMapping: {
        'a': '上单',
        'b': '打野',
        'c': '中单',
        'd': 'ADC',
        'e': '辅助'
      }
    }
  },
  mounted() {
    this.fetchPlayers();
  },
  methods: {
    async fetchPlayers() {
      try {
        const params = new URLSearchParams();
        if (this.filterForm.team_name) {
          params.append('team_name', this.filterForm.team_name);
        }
        if (this.filterForm.position) {
          params.append('position', this.filterForm.position);
        }
        params.append('page', this.pagination.page);

        const response = await fetch(`/player/api/list?${params.toString()}`);
        const data = await response.json();

        this.players = data.players;
        this.pagination = data.pagination;
      } catch (error) {
        this.$message.error('获取选手数据失败');
        console.error(error);
      }
    },
    handlePageChange(page) {
      this.pagination.page = page;
      this.fetchPlayers();
    },
    goToPlayerDetail(name) {
      this.$router.push(`/player/${encodeURIComponent(name)}`);
    }
  }
}
</script>

<style scoped>
.player-list-container {
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

.filter-form {
  background: #f5f7fa;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 30px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.form-row {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
}

.player-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
}

.player-card {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.player-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
}

.player-card-content {
  text-align: center;
}

.player-img {
  width: 100%;
  height: 200px;
  border-radius: 8px 8px 0 0;
}

.player-info h3 {
  margin: 15px 0 10px;
  font-size: 18px;
}

.player-info p {
  margin: 5px 0;
  color: #666;
  font-size: 14px;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 30px;
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

/* 移动端适配 */
@media (max-width: 768px) {
  .player-list-container {
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
  
  .filter-form {
    padding: 15px;
    margin-bottom: 20px;
  }
  
  .form-row {
    flex-direction: column;
    gap: 10px;
  }
  
  .player-grid {
    grid-template-columns: repeat(auto-fill, minmax(100%, 1fr));
    gap: 15px;
  }
  
  .player-info h3 {
    font-size: 16px;
  }
  
  .player-info p {
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
  
  .filter-form {
    padding: 10px;
  }
  
  .player-grid {
    gap: 10px;
  }
  
  .player-info h3 {
    font-size: 14px;
  }
  
  .player-info p {
    font-size: 12px;
  }
}
</style>