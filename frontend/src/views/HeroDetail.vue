<template>
  <div class="hero-detail-container" v-loading="loading">
    <el-page-header @back="goBack" content="英雄详情"></el-page-header>

    <div v-if="!loading && hero">
      <div class="hero-header">
        <h2 class="hero-title">{{ hero.hero_name }}</h2>
        <p class="hero-position">
          <el-tag :type="getPositionTagType(hero.position)">
            {{ positionMapping[hero.position] }}
          </el-tag>
        </p>
      </div>

      <el-row :gutter="20" class="hero-info-container">
        <el-col :span="24" :md="12">
          <el-card class="hero-stats-card">
            <div slot="header" class="stats-header">
              <h3>基础信息</h3>
            </div>
            
            <div class="hero-basic-info">
              <el-row>
                <el-col :span="24" :md="12">
                  <p><strong>英雄名称:</strong> {{ hero.hero_name }}</p>
                </el-col>
                <el-col :span="24" :md="12">
                  <p><strong>位置:</strong> {{ positionMapping[hero.position] }}</p>
                </el-col>
              </el-row>
              
              <el-row>
                <el-col :span="24" :md="12">
                  <p><strong>出场次数:</strong> {{ hero.matches_count }}</p>
                </el-col>
                <el-col :span="24" :md="12">
                  <p><strong>胜率:</strong> 
                    <el-tag :type="getWinRateTagType(hero.win_rate)">
                      {{ hero.win_rate }}%
                    </el-tag>
                  </p>
                </el-col>
              </el-row>
            </div>
          </el-card>
        </el-col>

        <el-col :span="24" :md="12">
          <el-card class="hero-image-card">
            <div slot="header" class="image-header">
              <h3>英雄头像</h3>
            </div>
            
            <div class="hero-image-container">
              <el-image
                :src="hero.pic || noPhotoImage"
                class="hero-img"
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

      <el-row :gutter="20" class="hero-stats-container">
        <el-col :span="24">
          <el-card class="hero-detailed-stats">
            <div slot="header" class="detailed-stats-header">
              <h3>详细数据统计</h3>
            </div>
            
            <el-row :gutter="20" class="stats-grid">
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均KDA</div>
                  <div class="stat-value">{{ hero.avg_kda }}</div>
                </div>
              </el-col>
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均击杀</div>
                  <div class="stat-value">{{ hero.avg_kills }}</div>
                </div>
              </el-col>
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均死亡</div>
                  <div class="stat-value">{{ hero.avg_deaths }}</div>
                </div>
              </el-col>
            </el-row>
            
            <el-row :gutter="20" class="stats-grid">
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均助攻</div>
                  <div class="stat-value">{{ hero.avg_assists }}</div>
                </div>
              </el-col>
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均参团率</div>
                  <div class="stat-value">{{ hero.avg_participation }}%</div>
                </div>
              </el-col>
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均经济</div>
                  <div class="stat-value">{{ hero.avg_gold }}</div>
                </div>
              </el-col>
            </el-row>
            
            <el-row :gutter="20" class="stats-grid">
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均伤害</div>
                  <div class="stat-value">{{ hero.avg_damage }}</div>
                </div>
              </el-col>
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均承受伤害</div>
                  <div class="stat-value">{{ hero.avg_damage_taken }}</div>
                </div>
              </el-col>
              <el-col :span="24" :sm="12" :md="8">
                <div class="stat-item">
                  <div class="stat-label">平均补刀</div>
                  <div class="stat-value">{{ hero.avg_cs }}</div>
                </div>
              </el-col>
            </el-row>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <el-empty v-else-if="!loading" description="没有找到英雄数据"></el-empty>
  </div>
</template>

<script>
import noPhotoImage from '@/assets/no_photo.png';

export default {
  name: 'HeroDetail',
  data() {
    return {
      noPhotoImage,
      heroName: '',
      hero: null,
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
    this.heroName = this.$route.params.hero_name;
    this.fetchHeroDetail();
  },
  methods: {
    async fetchHeroDetail() {
      this.loading = true;
      try {
        const response = await fetch(`/hero/api/${encodeURIComponent(this.heroName)}`);
        const data = await response.json();

        if (data.error) {
          this.$message.error(data.error);
          return;
        }

        this.hero = data;
      } catch (error) {
        this.$message.error('获取英雄数据失败');
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
    getWinRateTagType(winRate) {
      const rate = parseFloat(winRate);
      if (rate >= 55) return 'success';
      if (rate >= 50) return 'warning';
      return 'danger';
    }
  }
}
</script>

<style scoped>
.hero-detail-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.hero-header {
  text-align: center;
  margin-bottom: 30px;
  padding: 20px;
  background: linear-gradient(120deg, #f3e5f5, #e1bee7);
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.hero-title {
  margin: 10px 0;
  font-size: 28px;
  color: #4a148c;
  font-weight: bold;
}

.hero-position {
  margin: 5px 0;
}

.hero-info-container {
  margin-bottom: 20px;
}

.hero-stats-card, .hero-image-card {
  margin-bottom: 20px;
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.stats-header h3, .image-header h3, .detailed-stats-header h3 {
  margin: 0;
  text-align: center;
  color: #7b1fa2;
}

.hero-basic-info {
  padding: 20px;
}

.hero-basic-info p {
  font-size: 16px;
  margin: 10px 0;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.hero-basic-info p:last-child {
  border-bottom: none;
}

.hero-basic-info strong {
  color: #7b1fa2;
}

.hero-image-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
}

.hero-img {
  width: 200px;
  height: 200px;
  border-radius: 8px;
  border: 3px solid #7b1fa2;
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
  border-radius: 8px;
}

.hero-detailed-stats {
  margin-bottom: 20px;
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.detailed-stats-header {
  background: linear-gradient(90deg, #7b1fa2, #9c27b0);
  color: white;
  border-radius: 8px 8px 0 0;
  padding: 15px 20px;
}

.stats-grid {
  margin-bottom: 20px;
}

.stats-grid:last-child {
  margin-bottom: 0;
}

.stat-item {
  text-align: center;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 8px;
  transition: all 0.3s;
  margin-bottom: 10px;
}

.stat-item:hover {
  transform: translateY(-3px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
  background: #ffffff;
}

.stat-label {
  font-size: 14px;
  color: #666;
  margin-bottom: 5px;
}

.stat-value {
  font-size: 20px;
  font-weight: bold;
  color: #7b1fa2;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .hero-detail-container {
    padding: 10px;
  }
  
  .hero-header {
    padding: 15px;
    margin-bottom: 20px;
  }
  
  .hero-title {
    font-size: 24px;
  }
  
  .hero-basic-info {
    padding: 15px;
  }
  
  .hero-basic-info p {
    font-size: 14px;
  }
  
  .hero-img {
    width: 150px;
    height: 150px;
  }
  
  .image-slot {
    width: 150px;
    height: 150px;
    font-size: 36px;
  }
  
  .stat-item {
    padding: 10px;
  }
  
  .stat-label {
    font-size: 12px;
  }
  
  .stat-value {
    font-size: 18px;
  }
}

@media (max-width: 480px) {
  .hero-title {
    font-size: 20px;
  }
  
  .hero-basic-info {
    padding: 10px;
  }
  
  .hero-basic-info p {
    font-size: 13px;
  }
  
  .hero-img {
    width: 120px;
    height: 120px;
  }
  
  .image-slot {
    width: 120px;
    height: 120px;
    font-size: 28px;
  }
  
  .stat-item {
    padding: 8px;
  }
  
  .stat-label {
    font-size: 11px;
  }
  
  .stat-value {
    font-size: 16px;
  }
}
</style>