<template>
  <section class="panel not-found-page">
    <span class="eyebrow">页面未找到 · 404</span>
    <h1>暂时找不到这个页面。</h1>
    <p class="muted">可以从选手档案或比赛记录继续查找。</p>
    <div class="not-found-links">
      <RouterLink to="/player" class="button">浏览选手档案</RouterLink>
      <RouterLink to="/match" class="button secondary">查看比赛记录</RouterLink>
      <RouterLink to="/" class="text-link">返回数据总览 →</RouterLink>
    </div>
  </section>
</template>
<style scoped>
.not-found-page {
  border-top: 3px solid #102e50;
  padding: 40px 28px;
}
.not-found-page h1 {
  margin: 12px 0;
}
.not-found-links {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}
</style>
