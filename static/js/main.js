/**
 * Anti-Matrix — Main Application Controller (Vanilla JS)
 * Handles Scroll Reveal, FAQ Accordions, Careers Accordions, and Contact Form AJAX.
 */
document.addEventListener('DOMContentLoaded', () => {
  // ── 1. Scroll Reveal Intersection Observer ─────────────────────────────
  const revealElements = document.querySelectorAll('.reveal');
  if (revealElements.length > 0 && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1 }
    );

    revealElements.forEach((el) => observer.observe(el));
  } else {
    // Fallback if IntersectionObserver is not supported
    revealElements.forEach((el) => el.classList.add('revealed'));
  }

  // ── 2. Pricing Page FAQ Accordion ──────────────────────────────────────
  const faqButtons = document.querySelectorAll('.faq-toggle-btn');
  faqButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const isExpanded = btn.getAttribute('aria-expanded') === 'true';
      const answerPane = btn.nextElementSibling;
      const icon = btn.querySelector('.faq-icon');

      // Close other open FAQ items if needed or toggle current
      faqButtons.forEach((otherBtn) => {
        if (otherBtn !== btn) {
          otherBtn.setAttribute('aria-expanded', 'false');
          const otherPane = otherBtn.nextElementSibling;
          const otherIcon = otherBtn.querySelector('.faq-icon');
          const otherContainer = otherBtn.closest('.faq-item-container');
          if (otherPane) otherPane.style.display = 'none';
          if (otherIcon) otherIcon.style.transform = 'none';
          if (otherContainer) {
            otherContainer.style.borderColor = 'var(--color-border)';
            otherContainer.style.background = 'rgba(255,255,255,0.02)';
          }
        }
      });

      const container = btn.closest('.faq-item-container');
      if (isExpanded) {
        btn.setAttribute('aria-expanded', 'false');
        if (answerPane) answerPane.style.display = 'none';
        if (icon) icon.style.transform = 'none';
        if (container) {
          container.style.borderColor = 'var(--color-border)';
          container.style.background = 'rgba(255,255,255,0.02)';
        }
      } else {
        btn.setAttribute('aria-expanded', 'true');
        if (answerPane) answerPane.style.display = 'block';
        if (icon) icon.style.transform = 'rotate(45deg)';
        if (container) {
          container.style.borderColor = 'rgba(22,163,74,0.3)';
          container.style.background = 'rgba(22,163,74,0.04)';
        }
      }
    });
  });

  // ── 3. Careers Page Job Listing Accordion ──────────────────────────────
  const jobCards = document.querySelectorAll('.job-card-interactive');
  jobCards.forEach((card) => {
    card.addEventListener('click', () => {
      const targetId = card.getAttribute('data-target');
      const detailsPane = document.getElementById(targetId);
      const chevron = card.querySelector('.job-chevron');
      const btnText = card.querySelector('.job-btn-text');

      if (detailsPane) {
        const isOpen = detailsPane.style.display === 'block';

        // Collapse all other job details
        document.querySelectorAll('.job-details-pane').forEach((pane) => {
          if (pane !== detailsPane) {
            pane.style.display = 'none';
            const parentCard = document.querySelector(`[data-target="${pane.id}"]`);
            if (parentCard) {
              parentCard.style.borderColor = '';
              const c = parentCard.querySelector('.job-chevron');
              const t = parentCard.querySelector('.job-btn-text');
              if (c) c.style.transform = 'none';
              if (t) t.textContent = 'View Role';
            }
          }
        });

        if (isOpen) {
          detailsPane.style.display = 'none';
          card.style.borderColor = '';
          if (chevron) chevron.style.transform = 'none';
          if (btnText) btnText.textContent = 'View Role';
        } else {
          detailsPane.style.display = 'block';
          card.style.borderColor = 'rgba(22,163,74,0.35)';
          if (chevron) chevron.style.transform = 'rotate(90deg)';
          if (btnText) btnText.textContent = 'Collapse';
        }
      }
    });
  });

  // ── 4. Contact Form Handler (AJAX + Validation) ─────────────────────────
  const contactForm = document.getElementById('contact-form');
  const contactSuccessCard = document.getElementById('contact-success-card');

  if (contactForm) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    const nameInput = document.getElementById('contact-name');
    const emailInput = document.getElementById('contact-email');
    const phoneInput = document.getElementById('contact-phone');
    const subjectSelect = document.getElementById('contact-subject');
    const messageInput = document.getElementById('contact-message');
    const submitBtn = document.getElementById('contact-submit-btn');

    const validateForm = () => {
      const errors = {};
      const name = nameInput.value.trim();
      const email = emailInput.value.trim();
      const subject = subjectSelect.value;
      const message = messageInput.value.trim();

      if (!name) errors.name = 'Name is required';
      if (!email) {
        errors.email = 'Email is required';
      } else if (!/^\S+@\S+\.\S+$/.test(email)) {
        errors.email = 'Enter a valid email address';
      }
      if (!subject) errors.subject = 'Please select a subject';
      if (!message) {
        errors.message = 'Message is required';
      } else if (message.length < 20) {
        errors.message = 'Message must be at least 20 characters';
      }

      return errors;
    };

    const renderErrors = (errors) => {
      ['name', 'email', 'subject', 'message'].forEach((field) => {
        const input = document.getElementById(`contact-${field}`);
        const errSpan = document.getElementById(`${field}-err`);
        if (errors[field]) {
          if (input) input.classList.add('error');
          if (errSpan) {
            errSpan.textContent = errors[field];
            errSpan.style.display = 'block';
          }
        } else {
          if (input) input.classList.remove('error');
          if (errSpan) {
            errSpan.textContent = '';
            errSpan.style.display = 'none';
          }
        }
      });
    };

    // Live validation clearing on input
    [nameInput, emailInput, phoneInput, subjectSelect, messageInput].forEach((input) => {
      if (input) {
        input.addEventListener('input', () => {
          input.classList.remove('error');
          const field = input.id.replace('contact-', '');
          const errSpan = document.getElementById(`${field}-err`);
          if (errSpan) {
            errSpan.textContent = '';
            errSpan.style.display = 'none';
          }
        });
      }
    });

    contactForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const errors = validateForm();
      renderErrors(errors);

      if (Object.keys(errors).length > 0) return;

      // Loading state
      submitBtn.disabled = true;
      const originalBtnHtml = submitBtn.innerHTML;
      submitBtn.innerHTML = '<span>Sending…</span>';

      try {
        const payload = {
          name: nameInput.value.trim(),
          email: emailInput.value.trim(),
          phone: phoneInput.value.trim(),
          subject: subjectSelect.value,
          message: messageInput.value.trim()
        };

        const res = await fetch('/contact', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
          },
          body: JSON.stringify(payload)
        });

        const data = await res.json();

        if (res.ok && data.status === 'success') {
          contactForm.style.display = 'none';
          if (contactSuccessCard) contactSuccessCard.style.display = 'block';
        } else if (data.errors) {
          renderErrors(data.errors);
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalBtnHtml;
        } else {
          alert(data.message || 'An error occurred. Please try again.');
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalBtnHtml;
        }
      } catch (err) {
        // Fallback: standard form submit if fetch fails
        contactForm.submit();
      }
    });
  }

  // ── 4. Premium Cursor-Reactive Magnetic & 3D Button Interaction ─────────────
  function initMagneticButtons() {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (window.matchMedia && window.matchMedia('(hover: none)').matches) return;

    const selector = '.btn-primary, .cr-btn-apply, .btn-hero-primary';
    const buttons = document.querySelectorAll(selector);

    buttons.forEach((btn) => {
      if (btn.dataset.magneticInit) return;
      btn.dataset.magneticInit = 'true';

      let rect = null;
      let isHovered = false;
      let currentX = 0;
      let currentY = 0;
      let targetX = 0;
      let targetY = 0;
      let currentRotX = 0;
      let currentRotY = 0;
      let targetRotX = 0;
      let targetRotY = 0;
      let rafId = null;

      const render = () => {
        if (!isHovered) {
          // Smooth spring damping return to origin
          currentX += (0 - currentX) * 0.16;
          currentY += (0 - currentY) * 0.16;
          currentRotX += (0 - currentRotX) * 0.16;
          currentRotY += (0 - currentRotY) * 0.16;

          if (Math.abs(currentX) < 0.05 && Math.abs(currentY) < 0.05) {
            btn.style.transform = '';
            rafId = null;
            return;
          }
        } else {
          // Responsive fluid magnetic chase
          currentX += (targetX - currentX) * 0.22;
          currentY += (targetY - currentY) * 0.22;
          currentRotX += (targetRotX - currentRotX) * 0.22;
          currentRotY += (targetRotY - currentRotY) * 0.22;
        }

        btn.style.transform = `translate3d(${currentX.toFixed(2)}px, ${currentY.toFixed(2)}px, 0) rotateX(${currentRotX.toFixed(2)}deg) rotateY(${currentRotY.toFixed(2)}deg)`;
        rafId = requestAnimationFrame(render);
      };

      btn.addEventListener('mouseenter', () => {
        rect = btn.getBoundingClientRect();
        isHovered = true;
        if (!rafId) {
          rafId = requestAnimationFrame(render);
        }
      });

      btn.addEventListener('mousemove', (e) => {
        if (!rect) rect = btn.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        const deltaX = mouseX - rect.width / 2;
        const deltaY = mouseY - rect.height / 2;

        // Subtle, elegant magnetic pull (max ~6.5px) & 3D tilt (max ~4.5deg)
        targetX = Math.max(-6.5, Math.min(6.5, deltaX * 0.14));
        targetY = Math.max(-6.5, Math.min(6.5, deltaY * 0.14));
        targetRotX = Math.max(-4.5, Math.min(4.5, -deltaY * 0.09));
        targetRotY = Math.max(-4.5, Math.min(4.5, deltaX * 0.09));

        if (!rafId) {
          rafId = requestAnimationFrame(render);
        }
      });

      btn.addEventListener('mouseleave', () => {
        isHovered = false;
        targetX = 0;
        targetY = 0;
        targetRotX = 0;
        targetRotY = 0;
        rect = null;
      });
    });
  }

  initMagneticButtons();
});
