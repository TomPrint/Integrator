(() => {
  const script = document.currentScript;
  const measurementId = script.dataset.googleAnalyticsId.trim();
  const containerId = script.dataset.googleTagManagerId.trim();
  const isEnglish = script.dataset.language === 'en';
  const text = isEnglish ? {
    invalidId: 'Invalid Google Analytics ID: expected format G-...',
    invalidContainerId: 'Invalid Google Tag Manager ID: expected format GTM-...',
    loadFailed: 'Could not load Google Analytics.',
    containerLoadFailed: 'Could not load Google Tag Manager.',
    invalidConsent: 'Invalid cookie settings record.',
    readFailed: 'Could not read cookie settings.',
    saveFailed: 'Could not save cookie settings.',
    removeFailed: 'Could not remove previous cookie settings.'
  } : {
    invalidId: 'Nieprawidłowy identyfikator Google Analytics: wymagany format G-...',
    invalidContainerId: 'Nieprawidłowy identyfikator Google Tag Manager: wymagany format GTM-...',
    loadFailed: 'Nie udało się załadować Google Analytics.',
    containerLoadFailed: 'Nie udało się załadować Google Tag Manager.',
    invalidConsent: 'Nieprawidłowy zapis ustawień cookie.',
    readFailed: 'Nie można odczytać ustawień cookie.',
    saveFailed: 'Nie można zapisać ustawień cookie.',
    removeFailed: 'Nie można usunąć poprzednich ustawień cookie.'
  };
  const storageKey = 'mid-grator-cookie-consent';
  const maxAge = 365 * 24 * 60 * 60 * 1000;
  const banner = document.querySelector('[data-cookie-banner]');
  const preferences = document.querySelector('[data-cookie-preferences]');
  const analytics = document.querySelector('[data-cookie-analytics]');
  const error = document.querySelector('[data-cookie-error]');
  const manage = document.querySelector('[data-cookie-manage]');
  const save = document.querySelector('[data-cookie-save]');
  const open = document.querySelector('[data-cookie-open]');
  const validId = /^G-[A-Z0-9]+$/i.test(measurementId);
  const validContainerId = /^GTM-[A-Z0-9]+$/i.test(containerId);
  let enabled = false;
  let tagLoaded = false;
  let containerLoaded = false;

  if (measurementId && !validId) {
    console.error(text.invalidId);
  }
  if (containerId && !validContainerId) {
    console.error(text.invalidContainerId);
  }

  const denied = {
    analytics_storage: 'denied',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied'
  };

  function clearAnalyticsCookies() {
    const domains = location.hostname.split('.');
    for (const cookie of document.cookie.split(';')) {
      const name = cookie.split('=')[0].trim();
      if (!/^(_ga(?:_|$)|_gid$|_gat(?:_|$)|_gac_|_gcl_)/.test(name)) continue;
      const expired = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
      document.cookie = expired;
      for (let i = 0; i < domains.length - 1; i++) {
        document.cookie = `${expired}; domain=${domains.slice(i).join('.')}`;
      }
    }
  }

  function setAnalytics(allow) {
    enabled = allow;
    if (validId) window[`ga-disable-${measurementId}`] = !allow;
    if (!allow) {
      if (tagLoaded || containerLoaded) window.gtag('consent', 'update', denied);
      clearAnalyticsCookies();
      return;
    }
    if (!validId && !validContainerId) return;
    if (!tagLoaded && !containerLoaded) {
      window.dataLayer = window.dataLayer || [];
      window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
      window.gtag('consent', 'default', denied);
      window.gtag('consent', 'update', { ...denied, analytics_storage: 'granted' });
      window.gtag('js', new Date());
    }
    if (validContainerId && !containerLoaded) {
      window.dataLayer.push({ 'gtm.start': Date.now(), event: 'gtm.js' });
      const container = document.createElement('script');
      container.async = true;
      container.src = `https://www.googletagmanager.com/gtm.js?id=${encodeURIComponent(containerId)}`;
      container.addEventListener('error', () => console.error(text.containerLoadFailed));
      document.head.appendChild(container);
      containerLoaded = true;
    }
    if (validId && !tagLoaded) {
      const tag = document.createElement('script');
      tag.async = true;
      tag.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
      tag.addEventListener('error', () => console.error(text.loadFailed));
      document.head.appendChild(tag);
      tagLoaded = true;
    }
    if (validId) {
      window.gtag('config', measurementId, {
        page_location: location.origin + location.pathname,
        allow_google_signals: false,
        allow_ad_personalization_signals: false
      });
    }
  }

  function readConsent() {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      let record;
      try {
        record = JSON.parse(raw);
      } catch (parseError) {
        console.warn(text.invalidConsent, parseError);
        return null;
      }
      if (!record || typeof record !== 'object') return null;
      const time = Date.parse(record.decidedAt);
      const age = Date.now() - time;
      if (record.version !== 2 || typeof record.analytics !== 'boolean' ||
          !Number.isFinite(time) || age < 0 || age > maxAge) return null;
      return record.analytics;
    } catch (storageError) {
      console.error(text.readFailed, storageError);
      error.hidden = false;
      return null;
    }
  }

  function showPreferences() {
    analytics.checked = enabled;
    preferences.hidden = false;
    manage.hidden = true;
    save.hidden = false;
    banner.hidden = false;
  }

  function saveConsent(allow) {
    if (!allow) setAnalytics(false);
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        version: 2, analytics: allow, decidedAt: new Date().toISOString()
      }));
    } catch (storageError) {
      setAnalytics(false);
      console.error(text.saveFailed, storageError);
      try {
        localStorage.removeItem(storageKey);
        if (containerLoaded) location.reload();
      } catch (removeError) {
        console.error(text.removeFailed, removeError);
        if (containerLoaded) location.replace('about:blank');
      }
      error.hidden = false;
      return;
    }
    error.hidden = true;
    if (allow) setAnalytics(true);
    banner.hidden = true;
    if (!allow && containerLoaded) location.reload();
  }

  document.querySelector('[data-cookie-accept]').addEventListener('click', () => saveConsent(true));
  document.querySelector('[data-cookie-reject]').addEventListener('click', () => saveConsent(false));
  manage.addEventListener('click', showPreferences);
  save.addEventListener('click', () => saveConsent(analytics.checked));
  open.addEventListener('click', showPreferences);
  open.hidden = false;

  const stored = readConsent();
  setAnalytics(stored === true);
  banner.hidden = stored !== null;

  window.addEventListener('storage', (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    const choice = readConsent();
    setAnalytics(choice === true);
    analytics.checked = enabled;
    banner.hidden = choice !== null;
    if (choice !== true && containerLoaded) location.reload();
  });
})();
