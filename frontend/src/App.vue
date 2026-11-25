<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">多维指标分析与实验评估平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向业务指标口径管理、多维分析查询、AB实验评估、分群圈选和数据服务发布的分析应用平台</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "指标口径", path: "/metric_def" }, { label: "多维查询", path: "/dim_query" }, { label: "实验管理", path: "/experiment" }, { label: "显著性检验", path: "/significance" }, { label: "人群圈选", path: "/cohort" }, { label: "数据服务", path: "/data_service" }, { label: "异常检测", path: "/anomaly_detect" }, { label: "分析图表", path: "/analysis_chart" }, { label: "预聚合任务", path: "/aggregate_job" }, { label: "下钻分析", path: "/drill_down" }, { label: "数据导出", path: "/data_export" }, { label: "数据时效", path: "/data_freshness" }, { label: "查询缓存", path: "/query_cache" }, { label: "分群对比", path: "/segment_compare" }, { label: "指标校准", path: "/metric_calibrate" }, { label: "查询日志", path: "/query_log" }, { label: "慢查治理", path: "/query_governance" }, { label: "数据采样", path: "/data_sample" }, { label: "报告调度", path: "/report_schedule" }]
</script>
