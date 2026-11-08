(() => {
  const script = document.currentScript;
  const measurementId = script.dataset.googleAnalyticsId.trim();
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
  let enabled = false;
  let tagLoaded = false;

  if (measurementId && !validId) {
    console.error('Nieprawidłowy identyfikator Google Analytics: wymagany format G-...');
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
    if (!validId) return;
    window[`ga-disable-${measurementId}`] = !allow;
    if (!allow) {
      if (tagLoaded) window.gtag('consent', 'update', denied);
      clearAnalyticsCookies();
      return;
    }
    if (!tagLoaded) {
      window.dataLayer = window.dataLayer || [];
      window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
      window.gtag('consent', 'default', denied);
      window.gtag('consent', 'update', { ...denied, analytics_storage: 'granted' });
      window.gtag('js', new Date());
      const tag = document.createElement('script');
      tag.async = true;
      tag.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
      tag.addEventListener('error', () => console.error('Nie udało się załadować Google Analytics.'));
      document.head.appendChild(tag);
      tagLoaded = true;
    } else {
      window.gtag('consent', 'update', { ...denied, analytics_storage: 'granted' });
    }
    window.gtag('config', measurementId, {
      page_location: location.origin + location.pathname,
      allow_google_signals: false,
      allow_ad_personalization_signals: false
    });
  }

  function readConsent() {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      let record;
      try {
        record = JSON.parse(raw);
      } catch (parseError) {
        console.warn('Nieprawidłowy zapis ustawień cookie.', parseError);
        return null;
      }
      if (!record || typeof record !== 'object') return null;
      const time = Date.parse(record.decidedAt);
      const age = Date.now() - time;
      if (record.version !== 1 || typeof record.analytics !== 'boolean' ||
          !Number.isFinite(time) || age < 0 || age > maxAge) return null;
      return record.analytics;
    } catch (storageError) {
      console.error('Nie można odczytać ustawień cookie.', storageError);
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
        version: 1, analytics: allow, decidedAt: new Date().toISOString()
      }));
    } catch (storageError) {
      setAnalytics(false);
      console.error('Nie można zapisać ustawień cookie.', storageError);
      try {
        localStorage.removeItem(storageKey);
      } catch (removeError) {
        console.error('Nie można usunąć poprzednich ustawień cookie.', removeError);
      }
      error.hidden = false;
      return;
    }
    error.hidden = true;
    if (allow) setAnalytics(true);
    banner.hidden = true;
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
  });
})();
