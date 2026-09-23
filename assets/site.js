(() => {
  'use strict';

  // Header scroll state
  const header = document.querySelector('.site-header');
  if (header) {
    const updateHeader = () => {
      header.classList.toggle('is-scrolled', window.scrollY > 20);
    };
    updateHeader();
    window.addEventListener('scroll', updateHeader, { passive: true });
  }

  // Mobile navigation
  const menuToggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.nav-primary');
  if (menuToggle && nav) {
    menuToggle.addEventListener('click', () => {
      const isOpen = nav.classList.toggle('is-open');
      menuToggle.setAttribute('aria-expanded', String(isOpen));
      menuToggle.setAttribute('aria-label', isOpen ? 'Close menu' : 'Open menu');
      document.body.style.overflow = isOpen ? 'hidden' : '';
    });

    nav.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        nav.classList.remove('is-open');
        menuToggle.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
      });
    });
  }

  // Contact form fallback for no-JS / server round-trip
  const contactForm = document.getElementById('contact-form');
  if (contactForm) {
    const params = new URLSearchParams(window.location.search);
    const statusEl = contactForm.querySelector('[data-np-status]');

    const showStatus = (message, type) => {
      if (!statusEl) return;
      statusEl.textContent = message;
      statusEl.className = 'np-status';
      if (type) statusEl.classList.add(type);
    };

    const fieldErrors = params.get('np_fields');
    if (params.get('np_form') === 'ok') {
      showStatus(contactForm.dataset.npOk || 'Thanks — your message was sent.', 'is-success');
    } else if (params.get('np_form') === 'closed') {
      showStatus(contactForm.dataset.npClosed || 'This form is no longer accepting submissions.', 'is-closed');
    } else if (params.get('np_form') === 'error') {
      showStatus(contactForm.dataset.npError || 'Sorry, we couldn\'t send your message. Please try again.', 'is-error');

      if (fieldErrors) {
        fieldErrors.split(',').forEach(pair => {
          const [key, reason] = pair.split('.');
          const input = contactForm.querySelector(`[name="${key}"]`);
          if (!input) return;
          const message = reason === 'required'
            ? (contactForm.dataset.npRequired || 'This field is required.')
            : (contactForm.dataset.npInvalid || 'Please check this value.');

          let error = input.parentElement.querySelector('.field-error');
          if (!error) {
            error = document.createElement('span');
            error.className = 'field-error';
            input.parentElement.appendChild(error);
          }
          error.textContent = message;
          input.setAttribute('aria-invalid', 'true');
        });
      }
    }
  }
})();
