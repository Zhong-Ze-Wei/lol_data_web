import Vue from 'vue'
import VueRouter from 'vue-router'
import PlayerList from '../views/PlayerList.vue'
import PlayerDetail from '../views/PlayerDetail.vue'
import MatchList from '../views/MatchList.vue'

Vue.use(VueRouter)

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue')
  },
  {
    path: '/player',
    name: 'PlayerList',
    component: PlayerList
  },
  {
    path: '/player/:name',
    name: 'PlayerDetail',
    component: PlayerDetail,
    props: true
  },
  {
    path: '/match',
    name: 'MatchList',
    component: MatchList
  },
  {
    path: '/match/:match_id',
    name: 'MatchDetail',
    component: () => import('../views/MatchDetail.vue')
  },
  {
    path: '/team',
    name: 'TeamList',
    component: () => import('../views/TeamList.vue')
  },
  {
    path: '/team/:team_name',
    name: 'TeamDetail',
    component: () => import('../views/TeamDetail.vue'),
    props: true
  },
  // 启用英雄相关的路由
  {
    path: '/hero',
    name: 'HeroList',
    component: () => import('../views/HeroList.vue')
  },
  {
    path: '/hero/:hero_name',
    name: 'HeroDetail',
    component: () => import('../views/HeroDetail.vue'),
    props: true
  }
]

const router = new VueRouter({
  mode: 'history',
  base: process.env.BASE_URL,
  routes
})

export default router