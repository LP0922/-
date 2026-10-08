import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('../layouts/AdminLayout.vue'),
    redirect: '/monitor',
    children: [
      {
        path: 'monitor',
        name: 'DeviceMonitor',
        meta: { title: '设备监控', icon: 'Monitor' },
        component: () => import('../views/DeviceMonitor.vue'),
      },
      {
        path: 'dispense',
        name: 'DispenseControl',
        meta: { title: '加粉控制', icon: 'SetUp' },
        component: () => import('../views/DispenseControl.vue'),
      },
      {
        path: 'batch',
        name: 'BatchTest',
        meta: { title: '批量测试', icon: 'List' },
        component: () => import('../views/BatchTest.vue'),
      },
      {
        path: 'records',
        name: 'TestRecords',
        meta: { title: '试验记录', icon: 'Document' },
        component: () => import('../views/TestRecords.vue'),
      },
      {
        path: 'powders', name: 'PowderManagement',
        meta: { title: '粉末管理', icon: 'Collection' },
        component: () => import('../views/PowderManagement.vue'),
      },
      {
        path: 'experiments', name: 'GridExperiment',
        meta: { title: '网格实验', icon: 'DataAnalysis' },
        component: () => import('../views/GridExperiment.vue'),
      },    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router

