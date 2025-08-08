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
        <transition name="fade" mode="out-in">
          <div class="router-view-container">
            <router-view/>
          </div>
        </transition>
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

<style>
/* 全局样式，确保页面不滚动 */
html, body {
  margin: 0;
  padding: 0;
  height: 100%;
  overflow: hidden;
}
</style>

<style scoped>
/* 背景蓝紫 */
.app-container {
  background: linear-gradient(to bottom, #f0f4ff, #e6eeff); /* 更淡雅的蓝紫色背景 */
  height: 100vh;
  color: #333; /* 更深的文字颜色以提高可读性 */
  display: flex;
  flex-direction: column;
  overflow: hidden; /* 防止容器滚动 */
}

/* 容器样式 */
.el-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding-top: 60px; /* 直接用 header 高度 */
  padding-bottom: 50px;
}


/* 路由视图容器 */
.router-view-container {
  height: 100%;
  overflow-y: auto; /* 允许内容滚动 */
}

/* 头部 - 英雄联盟主题风格 */
.header {
  background: 
    linear-gradient(rgba(10, 20, 40, 0.85), rgba(10, 20, 40, 0.9)),
    url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><path d="M20,20 L80,20 L80,80 L20,80 Z" fill="none" stroke="rgba(200,155,60,0.1)" stroke-width="2"/><path d="M30,30 L70,30 L70,70 L30,70 Z" fill="none" stroke="rgba(200,155,60,0.1)" stroke-width="1"/></svg>');
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 80px;
  z-index: 1000;
  border-bottom: 1px solid rgba(200, 155, 60, 0.3);
  box-shadow: 0 2px 15px rgba(0, 0, 0, 0.5);
}

/* 主体区域 - 在固定头部下方滚动 */
.main {
  padding: 20px;
  background-color: rgba(255, 255, 255, 0.7);
  flex: 1;
  border-radius: 10px;
  margin: 0 20px 20px 20px; /* 去掉顶部80px */
  box-shadow: 0 0 20px rgba(0, 0, 50, 0.1);
  overflow-y: auto;
  position: relative;
  z-index: 1;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .top-banner {
    height: 15px;
  }

  .header {
    padding: 0 15px;
    top: 15px;
    height: 50px;
  }

  .logo {
    font-size: 20px;
  }

  .el-container {
    padding-top: 65px; /* banner + header高度 */
  }

  .main {
    margin: 10px;
    padding: 10px;
  }
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  height: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 30px;
}

.logo {
  font-size: 32px;
  font-weight: bold;
  margin: 0;
  font-family: 'BeaufortforLOL', 'Segoe UI', sans-serif;
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 20px;
  color: #C89B3C; /* 英雄联盟金色 */
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
  position: relative;
}

.logo::after {
  content: '';
  position: absolute;
  bottom: 15px;
  left: 20px;
  right: 20px;
  height: 2px;
  background: linear-gradient(to right, rgba(200, 155, 60, 0.8), transparent);
}

/* 英雄联盟主题菜单样式 */
.custom-menu {
  background: transparent;
  border-bottom: none;
  height: 100%;
}

.custom-menu .el-menu-item {
  color: rgba(255, 255, 255, 0.8);
  font-weight: 600;
  transition: all 0.3s ease;
  position: relative;
  font-family: 'BeaufortforLOL', 'Segoe UI', sans-serif;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-size: 14px;
  margin: 0 5px;
  height: 100%;
  display: flex;
  align-items: center;
}

.custom-menu .el-menu-item:hover {
  color: #C89B3C;
  background: rgba(200, 155, 60, 0.1);
  transform: translateY(-2px);
}

.custom-menu .el-menu-item.is-active {
  color: #C89B3C;
  font-weight: bold;
  background: rgba(200, 155, 60, 0.05);
}

.custom-menu .el-menu-item.is-active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 15px;
  right: 15px;
  height: 3px;
  background: #C89B3C;
  animation: navUnderline 0.3s ease-out;
}

@keyframes navUnderline {
  from {
    transform: scaleX(0);
  }
  to {
    transform: scaleX(1);
  }
}



/* 页脚 - 固定在底部 */
.footer {
  text-align: center;
  padding: 15px;
  font-size: 14px;
  color: #7a8b9c; /* 柔和的页脚文字颜色 */
  background: rgba(255, 255, 255, 0.5); /* 淡化页脚背景 */
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
}

/* 页面过渡效果 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* 移动端适配 */
@media screen and (max-width: 768px) {
  .header-content {
    flex-direction: column;
    align-items: flex-start;
  }

  .logo {
    font-size: 20px;
    margin-bottom: 10px;
  }

  .custom-menu {
    width: 100%;
    overflow-x: auto;
  }

  .custom-menu .el-menu-item {
    font-size: 14px;
    padding: 0 10px;
  }

  .main {
    padding: 15px;
    margin: 10px;
    border-radius: 5px;
  }

  .footer {
    padding: 10px;
    font-size: 12px;
  }

  .footer p {
    margin: 0;
  }
}

@media screen and (max-width: 480px) {
  .header {
    padding: 10px;
  }

  .logo {
    font-size: 18px;
  }

  .main {
    padding: 10px;
    margin: 5px;
  }

  .custom-menu .el-menu-item {
    font-size: 12px;
    padding: 0 8px;
  }
}
</style>