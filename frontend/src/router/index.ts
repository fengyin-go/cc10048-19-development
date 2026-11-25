import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import GovernanceView from '@/views/GovernanceView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/query_governance', name: 'query-governance', component: GovernanceView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
