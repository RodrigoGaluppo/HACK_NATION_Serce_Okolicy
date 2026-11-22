(() => {
  const translated = document.querySelectorAll('[data-en]');
  translated.forEach(el => { el.dataset.pl = el.innerHTML; });
  function setLanguage(lang) {
    lang = lang === 'en' ? 'en' : 'pl';
    document.documentElement.lang = lang;
    translated.forEach(el => { el.innerHTML = lang === 'en' ? el.dataset.en : el.dataset.pl; });
    document.querySelectorAll('[data-lang]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.lang === lang)));
    document.title = lang === 'en' ? 'Serce Okolicy — Find an AED. Support your neighbourhood.' : 'Serce Okolicy — Znajdź AED. Zadbaj o okolicę.';
    document.querySelector('.skip').textContent = lang === 'en' ? 'Skip to content' : 'Przejdź do treści';
    try { localStorage.setItem('promo-language', lang); } catch (_) {}
  }
  document.querySelectorAll('[data-lang]').forEach(button => button.addEventListener('click', () => setLanguage(button.dataset.lang)));
  let saved; try { saved = localStorage.getItem('promo-language'); } catch (_) {}
  setLanguage(saved || 'pl');
  const slider = document.querySelector('#map-reveal');
  const comparison = document.querySelector('.map-comparison');
  slider.addEventListener('input', () => comparison.style.setProperty('--reveal', slider.value + '%'));
})();
