<template>
  <div class="match-list-container">
    <h1>所有比赛</h1>

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
      
      // 滚动到列表顶部而不是页面顶部
      const listContainer = document.querySelector('.match-list');
      if (listContainer) {
        listContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
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

.filter-form {
  background: #f5f7fa;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 30px;
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
</style>
