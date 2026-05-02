// Copyright (c) 2026 nvbangg (github.com/nvbangg)


const CHANNELS = new Set(['stable', 'latest']);
const DEFAULT_CHANNEL = 'stable';
const jsonCache = new Map();
const dataCache = new Map();
const simplify = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');

async function json(url) {
  const key = url.toString();
  if (!jsonCache.has(key)) {
    jsonCache.set(key, fetch(url, { cache: 'no-cache' }).then(response => {
      if (!response.ok) throw new Error(`Failed to load ${url.pathname}: ${response.status}`);
      return response.json();
    }));
  }
  return jsonCache.get(key);
}

export function normalizeChannel(channel) {
  return CHANNELS.has(channel) ? channel : DEFAULT_CHANNEL;
}

function appName(packageName, names) {
  if (!packageName) return 'Unspecified';
  if (names[packageName]) return names[packageName];

  const skip = new Set(['com', 'org', 'net', 'android', 'app', 'apps', 'client', 'mobile', 'player', 'thirdpartyclient']);
  const parts = packageName.split('.').filter(part => part.length > 1 && !skip.has(part));
  const last = parts.at(-1) || packageName.split('.').at(-1) || packageName;
  return last.replace(/[-_]/g, ' ').replace(/\b[a-z]/g, char => char.toUpperCase());
}

function versions(value) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function packages(patch) {
  const value = patch.compatiblePackages;
  if (!value || (Array.isArray(value) && !value.length) || (!Array.isArray(value) && !Object.keys(value).length)) {
    return [{ packageName: '', versions: [] }];
  }

  if (!Array.isArray(value)) {
    return Object.entries(value).map(([packageName, list]) => ({ packageName, versions: versions(list) }));
  }

  const rows = value.flatMap(item => {
    if (typeof item === 'string') return [{ packageName: item, versions: [] }];
    if (!item || typeof item !== 'object') return [];

    const packageName = item.packageName || item.name;
    const targetVersions = item.targets?.map(target => target.version).filter(Boolean);
    return packageName ? [{ packageName, versions: versions(item.versions || targetVersions) }] : [];
  });

  return rows.length ? rows : [{ packageName: '', versions: [] }];
}

async function loadSource(key, meta, channel, names) {
  const list = await json(new URL(`../patch-bundles/${key}-patch-bundles/${key}-${channel}-patches-list.json`, import.meta.url));
  const source = {
    key,
    repo: meta.repo || '',
    version: list.version || meta.tag || '',
    tag: meta.tag || '',
    createdAt: meta.created_at || '',
  };

  const rows = (list.patches || []).flatMap((patch, patchIndex) => {
    const patchId = `${key}:${patchIndex}`;
    return packages(patch).map((target, targetIndex) => {
      const packageName = target.packageName || '';
      const name = appName(packageName, names);

      return {
        id: `${patchId}:${targetIndex}`,
        patchId,
        sourceKey: key,
        repo: source.repo,
        sourceVersion: source.version,
        sourceCreatedAt: source.createdAt,
        patchName: patch.name || 'Unnamed patch',
        description: patch.description || '',
        packageName,
        appName: name,
        versions: target.versions,
        enabled: patch.use ?? patch.default ?? true,
        options: Array.isArray(patch.options) ? patch.options : [],
        searchText: [
          key,
          source.repo,
          patch.name,
          patch.description,
          packageName,
          name,
          ...(Array.isArray(patch.options) ? patch.options : []).flatMap(opt => [opt.title, opt.key, opt.description])
        ].filter(Boolean).join(' ').toLowerCase(),
      };
    });
  });

  return { source, rows };
}

export async function loadChannelData(channelInput) {
  const channel = normalizeChannel(channelInput);
  if (dataCache.has(channel)) return dataCache.get(channel);

  const promise = Promise.all([
    json(new URL('./app-names.json', import.meta.url)),
    json(new URL(`./sources-${channel}.json`, import.meta.url)),
  ]).then(async ([names, sources]) => {
    const loaded = await Promise.all(
      Object.entries(sources)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, meta]) => loadSource(key, meta, channel, names)),
    );
    const sourceList = loaded.map(item => item.source);

    return {
      channel,
      sources: sourceList,
      rows: loaded.flatMap(item => item.rows),
      sourceMap: Object.fromEntries(sourceList.map(source => [source.key, source])),
    };
  });

  dataCache.set(channel, promise);
  return promise;
}

export function filterRows(data, filters) {
  const words = filters.query.split(/\s+/).map(simplify).filter(Boolean);
  return data.rows.filter(row => {
    if (filters.source && row.sourceKey !== filters.source) return false;
    if (filters.app) {
      if (filters.app === 'universal') {
        if (row.packageName) return false;
      } else if (row.packageName !== filters.app) {
        return false;
      }
    }
    if (words.length === 0) return true;
    const searchTarget = simplify(row.searchText);
    return words.every(word => searchTarget.includes(word));
  });
}

export function getFilterOptions(rows) {
  const appMap = new Map();
  const sourceSet = new Set();
  let hasUniversal = false;

  for (const row of rows) {
    sourceSet.add(row.sourceKey);
    if (row.packageName) {
      if (!appMap.has(row.packageName)) appMap.set(row.packageName, row.appName);
    } else {
      hasUniversal = true;
    }
  }

  const appOptions = [...appMap].map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label) || a.value.localeCompare(b.value));

  if (hasUniversal) {
    appOptions.unshift({ value: 'universal', label: 'Universal' });
  }

  return {
    sourceOptions: Array.from(sourceSet).sort((a, b) => a.localeCompare(b)).map(value => ({ value, label: value })),
    appOptions,
  };
}

export function summarizeRows(rows) {
  return {
    sources: new Set(rows.map(row => row.sourceKey)).size,
    patches: new Set(rows.map(row => row.patchId)).size,
    apps: new Set(rows.filter(row => row.packageName).map(row => row.packageName)).size,
  };
}
