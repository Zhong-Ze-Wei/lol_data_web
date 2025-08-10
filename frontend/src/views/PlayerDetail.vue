<template>
  <div class="player-detail-container" v-loading="loading">
    <el-page-header @back="goBack"></el-page-header>

    <!-- 选手说明 -->
    <div class="profile-card" v-if="!loading && playerData">
      <div class="profile-header">选手信息</div>
      <div class="profile-content">
        <div class="profile-left">
          <h1 class="player-name">{{ playerData.name }} <el-tag size="small" type="info">{{ getPositionName(playerData.main_position) }}</el-tag></h1>
          <p class="player-bio">
            {{ playerData.name }}是一位职业{{ getPositionName(playerData.main_position) }}选手，职业生涯共参加{{ playerData.stats.totalMatches }}场比赛，胜率{{ playerData.stats.winRate }}%。<br />
            场均KDA为{{ playerData.stats.avgKDA }}，场均经济{{ playerData.stats.avgMoney }}，场均输出{{ playerData.stats.avgAtkM }}，场均承伤{{ playerData.stats.avgDefM }}。<br />
            共使用过{{ playerData.stats.heroPool || 0 }}个不同英雄。
          </p>
        </div>
        <el-avatar :size="120" :src="playerData.pic" fit="cover" class="player-avatar"></el-avatar>
      </div>

      <!-- 图表容器 -->
      <div class="charts-container">
        <div ref="kdaChart" class="chart kda-chart"></div>
        <div ref="winRateChart" class="chart pie-chart"></div>
      </div>
    </div>

    <!-- 比赛记录表 -->
    <div class="stat-section" v-if="!loading && players.length > 0">
      <el-table :data="players" style="width: 100%" stripe>
        <el-table-column prop="date" label="比赛日期" width="120"></el-table-column>
        <el-table-column prop="hero" label="英雄"></el-table-column>
        <el-table-column label="KDA">
          <template slot-scope="scope">
            <div :ref="'miniKDA' + scope.$index" style="width: 100px; height: 40px;"></div>
          </template>
        </el-table-column>
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
      </el-table>
    </div>

    <el-empty v-else-if="!loading" description="没有找到该选手参与的比赛"></el-empty>
  </div>
</template>

<script>
import * as echarts from 'echarts';

export default {
  name: 'PlayerDetail',
  data() {
    return {
      playerName: '',
      playerData: null,
      players: [],
      loading: true,
      kdaChart: null,
      winRateChart: null
    };
  },
  mounted() {
    this.playerName = this.$route.params.name;
    this.fetchPlayerData();
  },
  methods: {
    getPositionName(position) {
      const positionMapping = {
        'a': '上单',
        'b': '打野',
        'c': '中单',
        'd': 'ADC',
        'e': '辅助'
      };
      return positionMapping[position] || position;
    },
    async fetchPlayerData() {
      this.loading = true;
      try {
        const response = await fetch(`/player/api/${this.playerName}`);
        const data = await response.json();
        if (data.error) {
          this.$message.error(data.error);
          return;
        }
        this.playerData = data;
        this.players = data.players || [];
        this.$nextTick(() => {
          setTimeout(() => this.initCharts(), 50);
        });
      } catch (error) {
        this.$message.error('获取选手数据失败');
        console.error(error);
      } finally {
        this.loading = false;
      }
    },
    groupByQuarter() {
      const grouped = {};
      this.players.forEach(p => {
        const d = new Date(p.date);
        const year = d.getFullYear();
        const quarter = Math.floor(d.getMonth() / 3) + 1;
        const key = `${year} Q${quarter}`;
        const kda = ((p.kills || 0) + (p.assists || 0)) / Math.max(1, p.deaths || 0);
        if (!grouped[key]) {
          grouped[key] = { totalKDA: 0, count: 0 };
        }
        grouped[key].totalKDA += kda;
        grouped[key].count += 1;
      });
      const labels = Object.keys(grouped).sort();
      const values = labels.map(k => +(grouped[k].totalKDA / grouped[k].count).toFixed(2));
      return { labels, values };
    },
    initCharts() {
      const { labels, values } = this.groupByQuarter();
      const minVal = Math.min(...values);
      const maxVal = Math.max(...values);

      this.kdaChart = echarts.init(this.$refs.kdaChart);
      this.kdaChart.setOption({
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: labels },
        yAxis: { type: 'value' },
        visualMap: {
          show: false,
          min: minVal,
          max: maxVal,
          inRange: {
            color: ['#1e90ff', '#ff4500']
          }
        },
        series: [{
          data: values,
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 12,
          lineStyle: { width: 4 },
          itemStyle: { color: '#409EFF' }
        }]
      });

      const totalMatches = this.playerData.stats.totalMatches || 0;
      const winRate = this.playerData.stats.winRate || 0;
      const winCount = Math.round(totalMatches * (winRate / 100));
      const loseCount = totalMatches - winCount;
      this.winRateChart = echarts.init(this.$refs.winRateChart);
      this.winRateChart.setOption({
        tooltip: { trigger: 'item' },
        series: [{
          type: 'pie',
          radius: '70%',
          data: [
            { value: winCount, name: '胜利', itemStyle: { color: '#67C23A' } },
            { value: loseCount, name: '失败', itemStyle: { color: '#F56C6C' } }
          ],
          label: { show: true, formatter: '{b}: {c} ({d}%)' }
        }]
      });
    },
    goBack() {
      this.$router.go(-1);
    }
  },
  beforeDestroy() {
    if (this.kdaChart) this.kdaChart.dispose();
    if (this.winRateChart) this.winRateChart.dispose();
  }
};
</script>

<style scoped>
.player-detail-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.profile-card {
  margin-top: 25px;
  background: linear-gradient(120deg, #ffffff, #f8f9ff);
  border-radius: 15px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.profile-header {
  background: linear-gradient(90deg, #4361ee, #3a0ca3);
  color: #fff;
  padding: 12px 20px;
  font-weight: bold;
  font-size: 16px;
}

.profile-content {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 25px;
}

.profile-left {
  max-width: 75%;
}

.player-name {
  font-size: 28px;
  font-weight: bold;
  margin-bottom: 10px;
}

.player-bio {
  margin-top: 12px;
  line-height: 1.6;
  color: #555;
  white-space: pre-line;
}

.player-avatar {
  border: 3px solid #409EFF;
  margin-left: 20px;
  align-self: flex-start;
  flex-shrink: 0;
}

/* 图表容器：水平排列，宽度100% */
.charts-container {
  display: flex;
  width: 100%;
  padding: 20px 25px;
  gap: 30px;
  box-sizing: border-box;
  justify-content: space-between;
}

/* 折线图占70%宽 */
.chart.kda-chart {
  flex: 0 0 65%;
  height: 260px;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  background: #fff;
}

/* 饼图占30%宽，居中 */
.chart.pie-chart {
  flex: 0 0 30%;
  height: 260px;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  background: #fff;
}

/* 比赛记录表格 */
.stat-section {
  background: #fff;
  padding: 25px;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  margin-top: 20px;
}

/* 响应式调整 */
@media (max-width: 960px) {
  .profile-content {
    flex-direction: column;
  }
  .profile-left {
    max-width: 100%;
  }
  .player-avatar {
    margin-left: 0;
    margin-top: 15px;
    align-self: center;
  }
  .charts-container {
    flex-direction: column;
    padding: 0 15px 15px;
  }
  .chart.kda-chart, .chart.pie-chart {
    flex: none;
    width: 100%;
    height: 220px;
    margin-bottom: 15px;
  }
}
</style>
