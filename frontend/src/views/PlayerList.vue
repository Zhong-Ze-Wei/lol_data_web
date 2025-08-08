<template>
  <div class="player-list-container">
    <h1>选手展示</h1>

    <!-- 筛选表单 -->
    <div class="filter-form">
      <el-form :inline="true" :model="filterForm" class="filter-form-inline">
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

        <el-form-item>
          <el-button type="primary" @click="fetchPlayers">筛选</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 加载状态指示器 -->
    <div v-if="loading" class="loading-container">
      <el-skeleton :rows="5" animated />
      <el-skeleton :rows="5" animated />
      <el-skeleton :rows="5" animated />
    </div>

    <!-- 选手列表展示 -->
    <div v-else class="player-grid">
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
          >
            <div slot="error" class="image-slot">
              <i class="el-icon-user-solid"></i>
            </div>
          </el-image>

          <div class="player-info">
            <h3>{{ player.name }}</h3>
            <p>战队：{{ player.team_name }}</p>
            <p>分路：{{ positionMapping[player.position] }}</p>
            <p>出场次数：{{ player.appearance_count || 0 }}</p>
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
      loading: false,
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
      
      // 滚动到列表顶部而不是页面顶部
      const listContainer = document.querySelector('.player-grid');
      if (listContainer) {
        listContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
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

.filter-form {
  background: #f5f7fa;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 30px;
}

.player-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
}

.player-card {
  cursor: pointer;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  border-radius: 12px;
  overflow: hidden;
}

.player-card:hover {
  transform: translateY(-8px);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.15);
}

.player-card-content {
  text-align: center;
  padding: 20px;
  background: linear-gradient(120deg, #ffffff, #f8f9ff);
}

.player-img {
  width: 100%;
  height: 200px;
  border-radius: 8px 8px 0 0;
}

.player-info h3 {
  margin: 15px 0 10px;
  font-size: 20px;
  font-weight: 600;
  color: #333;
}

.player-info p {
  margin: 8px 0;
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
</style>
