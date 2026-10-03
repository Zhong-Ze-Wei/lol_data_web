import { createRouter, createWebHistory } from "vue-router";

const directory = () => import("../views/DirectoryView.vue");
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: () => import("../views/Home.vue"),
      meta: { title: "数据总览" },
    },
    {
      path: "/analytics",
      name: "analytics",
      component: () => import("../views/AnalyticsView.vue"),
      meta: { title: "比较分析" },
    },
    {
      path: "/player",
      name: "players",
      component: directory,
      props: { kind: "player" },
      meta: { title: "选手档案" },
    },
    {
      path: "/player/:name",
      name: "player",
      component: () => import("../views/PlayerDetail.vue"),
      meta: { title: "选手详情" },
    },
    {
      path: "/match",
      name: "matches",
      component: directory,
      props: { kind: "match" },
      meta: { title: "比赛记录" },
    },
    {
      path: "/match/:match_id",
      name: "match",
      component: () => import("../views/MatchDetail.vue"),
      meta: { title: "比赛详情" },
    },
    {
      path: "/team",
      name: "teams",
      component: directory,
      props: { kind: "team" },
      meta: { title: "战队档案" },
    },
    {
      path: "/team/:team_name",
      name: "team",
      component: () => import("../views/TeamDetail.vue"),
      meta: { title: "战队详情" },
    },
    {
      path: "/hero",
      name: "heroes",
      component: directory,
      props: { kind: "hero" },
      meta: { title: "英雄数据" },
    },
    {
      path: "/hero/:hero_name",
      name: "hero",
      component: () => import("../views/HeroDetail.vue"),
      meta: { title: "英雄详情" },
    },
    {
      path: "/:pathMatch(.*)*",
      component: () => import("../views/NotFound.vue"),
      meta: { title: "页面未找到" },
    },
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition;
    return to.path === from.path ? undefined : { top: 0 };
  },
});
router.afterEach((to) => {
  document.title = `${to.meta.title} · LOL DATA`;
});
export default router;
