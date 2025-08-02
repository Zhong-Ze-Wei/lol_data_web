<template>
  <div class="team-list-container">
    <!-- 标题和欢迎信息 -->
    <el-row :gutter="20">
      <el-col :span="24">
        <el-card class="welcome-card" shadow="hover">
          <div slot="header" class="welcome-header">
            <h2>🏆 所有战队</h2>
          </div>
          <p class="welcome-text">在这里您可以查看所有参与职业赛事的战队信息，了解他们的成员构成和战绩表现。</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选表单 -->
    <div class="filter-form">
      <el-form :inline="true" :model="filterForm" class="filter-form-inline">
        <div class="form-row">
          <div class="form-group">
            <el-form-item label="战队名称">
              <el-input
                v-model="filterForm.team_name"
                placeholder="请输入战队名称"
                clearable
              />
            </el-form-item>
          </div>
        </div>

        <el-form-item>
          <el-button type="primary" @click="fetchTeams">筛选</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 战队列表 -->
    <div class="team-list" v-loading="loading">
      <el-card
        v-for="team in teams"
        :key="team.id"
        class="team-card"
        @click.native="goToTeamDetail(team.team_name)"
        shadow="hover"
      >
        <div class="team-card-content">
          <div class="team-info">
            <div class="team-name">{{ team.team_name }}</div>
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
  name: 'TeamList',
  data() {
    return {
      loading: false,
      filterForm: {
        team_name: ''
      },
      teams: [],
      pagination: {
        page: 1,
        pages: 1,
        has_prev: false,
        has_next: false
      }
    }
  },
  mounted() {
    this.fetchTeams();
  },
  methods: {
    async fetchTeams() {
      // 添加加载状态
      this.loading = true;
      try {
        const params = new URLSearchParams();
        if (this.filterForm.team_name) {
          params.append('team_name', this.filterForm.team_name);
        }
        params.append('page', this.pagination.page);

        // 修改API端点以获取不重复的战队列表
        const response = await fetch(`/team/api/distinct?${params.toString()}`);
        const data = await response.json();

        if (data.error) {
          this.$message.error(data.error);
          return;
        }

        this.teams = data.teams;
        this.pagination = data.pagination;
      } catch (error) {
        this.$message.error('获取战队数据失败');
        console.error(error);
      } finally {
        this.loading = false;
      }
    },
    handlePageChange(page) {
      this.pagination.page = page;
      this.fetchTeams();
    },
    goToTeamDetail(teamName) {
      this.$router.push(`/team/${teamName}`);
    }
  }
}
</script>

<style scoped>
.team-list-container {
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

.form-group {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}

.team-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
  min-height: 400px;
}

.team-card {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  border-radius: 15px;
  background: linear-gradient(120deg, #ffffff, #f8f9ff);
  border: none;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1) !important;
}

.team-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.15) !important;
}

.team-card-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 30px 20px;
}

.team-info {
  text-align: center;
  padding: 0 20px;
  width: 100%;
}

.team-name {
  font-size: 20px;
  font-weight: bold;
  color: #333;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 30px;
}
</style>