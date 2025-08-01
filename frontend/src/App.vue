<template>
  <div id="app" class="app-container">
    <el-container>
      <el-header class="header">
        <div class="header-content">
          <h1 class="logo">LOL职业赛事数据平台</h1>
          <el-menu
            :default-active="activeIndex"
            class="custom-menu"
            mode="horizontal"
            @select="handleSelect"
            router
          >
            <el-menu-item index="/">首页</el-menu-item>
            <el-menu-item index="/player">选手</el-menu-item>
            <el-menu-item index="/match">比赛</el-menu-item>
            <el-menu-item index="/team">战队</el-menu-item>
            <el-menu-item index="/hero">英雄</el-menu-item>
          </el-menu>
        </div>
      </el-header>

      <el-main class="main">
        <router-view/>
      </el-main>

      <el-footer class="footer">
        <p>© 2025 LOL职业赛事数据平台 - 英雄联盟电竞数据分析</p>
      </el-footer>
    </el-container>
  </div>
</template>

<script>
export default {
  data() {
    return {
      activeIndex: this.$route.path,
    };
  },
  watch: {
    $route(to) {
      this.activeIndex = to.path;
    },
  },
  methods: {
    handleSelect(index) {
      if (this.$route.path !== index) {
        this.$router.push(index).catch(err => {
          if (err.name !== 'NavigationDuplicated' && 
              !err.message.includes('Avoided redundant navigation')) {
            console.error(err);
          }
        });
      }
    },
  },
};
</script>

<style scoped>
/* 背景蓝紫 */
.app-container {
  background: linear-gradient(to bottom, #f0f4ff, #e6eeff); /* 更淡雅的蓝紫色背景 */
  min-height: 100vh;
  color: #333; /* 更深的文字颜色以提高可读性 */
}

/* 头部样式 */
.header {
  background: rgba(255, 255, 255, 0.8); /* 更淡的头部背景 */
  padding: 10px 20px;
  backdrop-filter: blur(10px); /* 添加毛玻璃效果 */
  border-bottom: 1px solid #e0e6ed;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.logo {
  font-size: 24px;
  color: #2c3e50; /* 深灰色logo */
  font-weight: bold;
  margin: 0;
  font-family: 'Segoe UI', sans-serif;
}

/* 自定义菜单样式 */
.custom-menu {
  background: transparent;
  border-bottom: none;
}

.custom-menu .el-menu-item {
  color: #5a6a85; /* 柔和的菜单文字颜色 */
  font-weight: 500;
  transition: all 0.3s ease;
  position: relative;
}

.custom-menu .el-menu-item:hover {
  color: #409eff; /* 淡蓝色hover效果 */
  transform: translateY(-2px);
}

.custom-menu .el-menu-item.is-active {
  color: #409eff;
  font-weight: bold;
  border-bottom: 2px solid #409eff;
}

/* 主体区域 */
.main {
  padding: 20px;
  background-color: rgba(255, 255, 255, 0.7); /* 更淡的背景色 */
  min-height: 600px;
  border-radius: 10px;
  margin: 20px;
  box-shadow: 0 0 20px rgba(0, 0, 50, 0.1); /* 更淡的阴影 */
}

/* 页脚 */
.footer {
  text-align: center;
  padding: 15px;
  font-size: 14px;
  color: #7a8b9c; /* 柔和的页脚文字颜色 */
  background: rgba(255, 255, 255, 0.5); /* 淡化页脚背景 */
}
</style>
