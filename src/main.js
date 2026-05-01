import { createApp, ref, computed, onMounted, watch } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { filterRows, getFilterOptions, loadChannelData, normalizeChannel, summarizeRows } from './data.js';

const DEFAULT_CHANNEL = 'stable';
const SOURCE_HASH = '#sources';

createApp({
  setup() {
    const view = ref(location.hash.startsWith(SOURCE_HASH) ? 'sources' : 'apps');
    const query = ref('');
    const source = ref('');
    const app = ref('');
    const channel = ref(DEFAULT_CHANNEL);

    const activeData = ref(null);
    const isLoading = ref(true);
    const errorMsg = ref('');
    
    const isModalOpen = ref(false);
    const modalPackage = ref('');

    const hashQuery = location.hash.includes('?') ? location.hash.substring(location.hash.indexOf('?')) : '';
    const params = new URLSearchParams(location.search || hashQuery);
    query.value = params.get('q') || '';
    source.value = params.get('source') || '';
    app.value = params.get('app') || '';
    channel.value = normalizeChannel(params.get('channel') || DEFAULT_CHANNEL);

    // Sync state to URL on change
    watch([view, query, source, app, channel], () => {
      const params = new URLSearchParams();
      if (query.value) params.set('q', query.value);
      if (source.value) params.set('source', source.value);
      if (app.value) params.set('app', app.value);
      if (channel.value !== DEFAULT_CHANNEL) params.set('channel', channel.value);
      
      const q = params.toString();
      const hash = view.value === 'sources' ? SOURCE_HASH : '';
      history.replaceState(null, '', `${location.pathname}${hash}${q ? `?${q}` : ''}`);
    });

    const loadData = async () => {
      isLoading.value = true;
      errorMsg.value = '';
      try {
        activeData.value = await loadChannelData(channel.value);
        const options = getFilterOptions(activeData.value);
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

    // Auto-open
    watch([filteredRows, view], () => {
      if (view.value === 'apps' && (query.value.trim() || source.value || app.value) && !isModalOpen.value) {
        const rows = filteredRows.value;
        const pkgs = new Set(rows.map(r => r.packageName).filter(Boolean));
        if (pkgs.size === 1) {
          openModal([...pkgs][0]);
        }
      }
    }, { immediate: true });

    const filterOptions = computed(() => {
      if (!activeData.value) return { sourceOptions: [], appOptions: [] };
      return getFilterOptions(activeData.value);
    });

    const stats = computed(() => summarizeRows(filteredRows.value));

    // Grouping for Apps View
    const appsGroups = computed(() => {
      if (view.value !== 'apps') return [];
      const map = new Map();
      for (const row of filteredRows.value) {
        if (!row.packageName) continue;
        if (!map.has(row.packageName)) map.set(row.packageName, []);
        map.get(row.packageName).push(row);
      }
      return Array.from(map.entries()).map(([pkg, patches]) => ({
        packageName: pkg,
        name: patches[0].appName,
        patches: new Set(patches.map(p => p.patchId)).size,
        sources: new Set(patches.map(p => p.sourceKey)).size,
        options: patches.filter(p => p.optionCount).length,
      })).sort((a, b) => a.name.localeCompare(b.name) || a.packageName.localeCompare(b.packageName));
    });

    // Grouping for Sources View
    const sourcesGroups = computed(() => {
      if (view.value !== 'sources') return [];
      const map = new Map();
      for (const row of filteredRows.value) {
        if (!map.has(row.sourceKey)) map.set(row.sourceKey, []);
        map.get(row.sourceKey).push(row);
      }
      return Array.from(map.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, rows]) => {
          const sorted = [...rows].sort((a, b) => {
             if (Boolean(a.packageName) !== Boolean(b.packageName)) return a.packageName ? -1 : 1;
             return a.appName.localeCompare(b.appName) || a.patchName.localeCompare(b.patchName);
          });
          return { key, rows: sorted, source: activeData.value.sourceMap[key] };
        });
    });

    const openModal = (pkg) => {
      modalPackage.value = pkg;
      isModalOpen.value = true;
      document.body.classList.add('modal-open');
    };
    
    const closeModal = () => {
      isModalOpen.value = false;
      document.body.classList.remove('modal-open');
    };

    window.addEventListener('hashchange', () => {
      view.value = location.hash.startsWith(SOURCE_HASH) ? 'sources' : 'apps';
    });
    
    window.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeModal();
    });

    // Data for App Modal
    const modalData = computed(() => {
       if (!isModalOpen.value || !activeData.value) return null;
       const patches = filteredRows.value.filter(r => r.packageName === modalPackage.value);
       if (!patches.length) return null;
       
       const map = new Map();
       for (const row of patches) {
         if (!map.has(row.sourceKey)) map.set(row.sourceKey, []);
         map.get(row.sourceKey).push(row);
       }
       const groups = Array.from(map.entries())
         .sort(([a], [b]) => a.localeCompare(b))
         .map(([key, rows]) => {
           const sorted = [...rows].sort((a, b) => a.patchName.localeCompare(b.patchName));
           return { key, rows: sorted, source: activeData.value.sourceMap[key] };
         });
         
       return {
         appName: patches[0].appName,
         packageName: patches[0].packageName,
         stats: { sources: groups.length, patches: new Set(patches.map(p=>p.patchId)).size },
         groups
       };
    });

    const formatDate = (val) => {
      const d = val ? new Date(val) : null;
      return d && !isNaN(d.getTime()) ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
    };
    const countBy = (items, keyFn) => new Set(items.map(keyFn).filter(Boolean)).size;
    const playUrl = pkg => `https://play.google.com/store/apps/details?id=${encodeURIComponent(pkg)}`;
    const releaseUrl = s => s.repo && s.version ? `https://github.com/${s.repo}/releases/tag/${encodeURIComponent(s.version)}` : '';
    const morpheUrl = repo => `https://morphe.software/add-source?github=${encodeURI(repo)}`;

    const resetFilters = () => {
      query.value = '';
      source.value = '';
      app.value = '';
    };

    return {
      view, query, source, app, channel,
      isLoading, errorMsg, stats, filterOptions,
      appsGroups, sourcesGroups,
      isModalOpen, modalData, openModal, closeModal,
      formatDate, countBy, playUrl, releaseUrl, morpheUrl,
      resetFilters
    };
  }
}).mount('#app');
