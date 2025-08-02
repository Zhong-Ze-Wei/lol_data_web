<template>
  <div class="match-list-container">
    <!-- 标题和欢迎信息 -->
    <el-row :gutter="20">
      <el-col :span="24">
        <el-card class="welcome-card" shadow="hover">
          <div slot="header" class="welcome-header">
            <h2>⚔️ 所有比赛</h2>
          </div>
          <p class="welcome-text">在这里您可以查看所有职业比赛的记录，通过筛选条件查找您感兴趣的比赛。</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选表单 -->
    <div class="filter-form">
      <el-form :inline="true" :model="filterForm" class="filter-form-inline">
        <div class="form-row">
          <div class="form-group">
            <el-form-item label="战队1名称">
              <el-input
                v-model="filterForm.team_name1"
                placeholder="请输入战队1名称"
                clearable
              />
            </el-form-item>

            <el-form-item label="战队2名称">
              <el-input
                v-model="filterForm.team_name2"
                placeholder="请输入战队2名称"
                clearable
              />
            </el-form-item>
          </div>

          <div class="form-group">
            <el-form-item label="开始时间">
              <el-date-picker
                v-model="filterForm.start_date"
                type="month"
                placeholder="选择开始月份"
                format="yyyy-MM"
                value-format="yyyy-MM"
              />
            </el-form-item>

            <el-form-item label="结束时间">
              <el-date-picker
                v-model="filterForm.end_date"
                type="month"
                placeholder="选择结束月份"
                format="yyyy-MM"
                value-format="yyyy-MM"
              />
            </el-form-item>
          </div>
        </div>

        <el-form-item>
          <el-button type="primary" @click="fetchMatches">筛选</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 比赛列表 -->
    <div class="match-list">
      <el-card
        v-for="match in matches"
        :key="match.match_id"
        class="match-card"
        @click.native="goToMatchDetail(match.match_id)"
      >
        <div class="match-card-content">
          <div class="team red-team" :style="{ color: match.red_color }">
            {{ match.red_team_name }}
          </div>

          <div class="match-info">
            <div class="match-date">{{ match.date }}</div>
          </div>

          <div class="team blue-team" :style="{ color: match.blue_color }">
            {{ match.blue_team_name }}
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
  name: 'MatchList',
  data() {
    return {
      filterForm: {
        team_name1: '',
        team_name2: '',
        start_date: '',
        end_date: ''
      },
      matches: [],
      pagination: {
        page: 1,
        pages: 1,
        has_prev: false,
        has_next: false
      }
    }
  },
  mounted() {
    this.fetchMatches();
  },
  methods: {
    async fetchMatches() {
      try {
        const params = new URLSearchParams();
        if (this.filterForm.team_name1) {
          params.append('team_name1', this.filterForm.team_name1);
        }
        if (this.filterForm.team_name2) {
          params.append('team_name2', this.filterForm.team_name2);
        }
        if (this.filterForm.start_date) {
          params.append('start_date', this.filterForm.start_date);
        }
        if (this.filterForm.end_date) {
          params.append('end_date', this.filterForm.end_date);
        }
        params.append('page', this.pagination.page);

        const response = await fetch(`/match/api/list?${params.toString()}`);
        const data = await response.json();

        if (data.error) {
          this.$message.error(data.error);
          return;
        }

        this.matches = data.matches;
        this.pagination = data.pagination;
      } catch (error) {
        this.$message.error('获取比赛数据失败');
        console.error(error);
      }
    },
    handlePageChange(page) {
      this.pagination.page = page;
      this.fetchMatches();
    },
    goToMatchDetail(matchId) {
      this.$router.push(`/match/${matchId}`);
    }
  }
}
</script>

<style scoped>
.match-list-container {
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

.match-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
}

.match-card {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.match-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
}

.match-card-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
}

.team {
  font-size: 18px;
  font-weight: bold;
}

.red-team {
  text-align: left;
  flex: 1;
}

.blue-team {
  text-align: right;
  flex: 1;
}

.match-info {
  text-align: center;
  padding: 0 20px;
}

.match-date {
  font-size: 14px;
  color: #666;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 30px;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .match-list-container {
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
    gap: 10px;
  }
  
  .form-group {
    gap: 10px;
    flex-direction: column;
  }
  
  .match-list {
    grid-template-columns: repeat(auto-fill, minmax(100%, 1fr));
    gap: 15px;
  }
  
  .match-card-content {
    padding: 15px;
  }
  
  .team {
    font-size: 16px;
  }
  
  .match-date {
    font-size: 12px;
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
  
  .match-list {
    gap: 10px;
  }
  
  .match-card-content {
    padding: 10px;
    flex-direction: column;
    gap: 10px;
  }
  
  .team {
    font-size: 14px;
    text-align: center !important;
  }
  
  .match-info {
    padding: 0;
  }
}
</style>
