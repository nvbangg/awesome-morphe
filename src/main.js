// Copyright (c) 2026 nvbangg (github.com/nvbangg)

import { createApp, ref, computed, onMounted, watch, reactive } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { filterRows, getFilterOptions, loadChannelData, normalizeChannel, summarizeRows } from './data.js';

const DEFAULT_CHANNEL = 'stable';

createApp({
  setup() {
    const query = ref('');
    const source = ref('');
    const app = ref('');
    const channel = ref(DEFAULT_CHANNEL);

    const activeData = ref(null);
    const isLoading = ref(true);
    const errorMsg = ref('');

    const params = new URLSearchParams(location.search);
    query.value = params.get('q') || '';
    source.value = params.get('source') || '';
    app.value = params.get('app') || '';
    channel.value = normalizeChannel(params.get('channel') || DEFAULT_CHANNEL);

    // Sync state to URL on change
    watch([query, source, app, channel], () => {
      const params = new URLSearchParams();
      if (query.value) params.set('q', query.value);
      if (source.value) params.set('source', source.value);
      if (app.value) params.set('app', app.value);
      if (channel.value !== DEFAULT_CHANNEL) params.set('channel', channel.value);
      
      const q = params.toString();
      history.replaceState(null, '', `${location.pathname}${q ? `?${q}` : ''}`);
    });

    const loadData = async () => {
      isLoading.value = true;
      errorMsg.value = '';
      try {
        activeData.value = await loadChannelData(channel.value);
        const options = getFilterOptions(activeData.value.rows);
        if (!options.sourceOptions.some(o => o.value === source.value)) source.value = '';
        if (!options.appOptions.some(o => o.value === app.value)) app.value = '';
      } catch (err) {
        errorMsg.value = err.message || err;
      } finally {
        isLoading.value = false;
      }
    };

    onMounted(loadData);
    watch(channel, loadData);

    const filteredRows = computed(() => {
      if (!activeData.value) return [];
      return filterRows(activeData.value, { query: query.value, source: source.value, app: app.value });
    });


    const filterOptions = computed(() => {
      if (!activeData.value) return { sourceOptions: [], appOptions: [] };
      
      const rowsForSource = filterRows(activeData.value, { query: query.value, source: '', app: app.value });
      const sourceOptions = getFilterOptions(rowsForSource).sourceOptions;
      
      const rowsForApp = filterRows(activeData.value, { query: query.value, source: source.value, app: '' });
      const appOptions = getFilterOptions(rowsForApp).appOptions;
      
      return { sourceOptions, appOptions };
    });

    const stats = computed(() => summarizeRows(filteredRows.value));

    // Grouping for View
    const sourcesGroups = computed(() => {
      const map = new Map();
      for (const row of filteredRows.value) {
        if (!map.has(row.sourceKey)) map.set(row.sourceKey, []);
        map.get(row.sourceKey).push(row);
      }
      return Array.from(map.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, rows]) => {
          const patchMap = new Map();
          for (const row of rows) {
             if (!patchMap.has(row.patchId)) {
                patchMap.set(row.patchId, {
                   id: row.patchId,
                   patchName: row.patchName,
                   description: row.description,
                   enabled: row.enabled,
                   options: row.options || [],
                   apps: []
                });
             }
             if (row.packageName || row.appName) {
               patchMap.get(row.patchId).apps.push({
                  id: row.id,
                  appName: row.appName,
                  packageName: row.packageName,
                  versions: row.versions
               });
             }
          }
          const patches = Array.from(patchMap.values()).sort((a, b) => a.patchName.localeCompare(b.patchName));
          return {
            key,
            source: activeData.value.sourceMap[key],
            rows,
            patches 
          };
        });
    });

    const expandedVersions = reactive(new Set());
    const toggleVersions = (id) => {
      expandedVersions.has(id) ? expandedVersions.delete(id) : expandedVersions.add(id);
    };

    const expandedOptions = reactive(new Set());
    const toggleOptions = (id) => {
      expandedOptions.has(id) ? expandedOptions.delete(id) : expandedOptions.add(id);
    };

    const filterByApp = (pkg) => {
      app.value = pkg;
    };

    const formatDate = (val) => {
      const d = val ? new Date(val) : null;
      return d && !isNaN(d.getTime()) ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
    };
    const countBy = (items, keyFn) => new Set(items.map(keyFn).filter(Boolean)).size;
    const playUrl = pkg => `https://play.google.com/store/apps/details?id=${encodeURIComponent(pkg)}`;
    const releaseUrl = s => s.repo && s.tag ? `https://github.com/${s.repo}/releases/tag/${encodeURIComponent(s.tag)}` : '';
    const morpheUrl = repo => `https://morphe.software/add-source?github=${encodeURI(repo)}`;

    const resetFilters = () => {
      query.value = '';
      source.value = '';
      app.value = '';
    };

    return {
      query, source, app, channel,
      isLoading, errorMsg, stats, filterOptions,
      sourcesGroups,
      expandedVersions, toggleVersions,
      expandedOptions, toggleOptions,
      filterByApp,
      formatDate, countBy, playUrl, releaseUrl, morpheUrl,
      resetFilters
    };
  }
}).mount('#app');
