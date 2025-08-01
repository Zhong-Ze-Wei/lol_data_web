:frontend/src/views/PlayerDetail.vue
<template>
  <div class="player-detail-container" v-loading="loading">
    <el-page-header @back="goBack" :content="playerName + ' 的比赛记录'"></el-page-header>

    <div v-if="!loading && players.length > 0">
      <el-table :data="players" style="width: 100%" stripe>
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

.el-page-header {
  margin-bottom: 20px;
}
</style>
