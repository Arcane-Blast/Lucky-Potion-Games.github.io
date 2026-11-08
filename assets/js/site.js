/* Arcane Blast — small progressive enhancements. The page works without this file. */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* sticky nav gets a background once the page scrolls */
  var nav = document.querySelector('.nav');
  if (nav) {
    var onScroll = function () { nav.classList.toggle('is-stuck', window.scrollY > 8); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* footer year */
  var year = document.querySelector('[data-year]');
  if (year) year.textContent = String(new Date().getFullYear());

  /* hero: turn the icon list into slowly drifting columns (rows on phones) */
  var wall = document.querySelector('.icon-wall');
  if (wall && !reduceMotion) {
    var items = Array.prototype.map.call(wall.querySelectorAll('li'), function (li) {
      return li.querySelector('img');
    }).filter(Boolean);
    if (items.length) {
      var buildWall = function () {
        var phone = window.matchMedia('(max-width: 980px)').matches;
        var lanes = phone ? 2 : 4;
        var perLane = Math.max(phone ? 7 : 5, Math.ceil(items.length / lanes) + 1);
        var frag = document.createDocumentFragment();
        var n = 0;
        for (var c = 0; c < lanes; c++) {
          var col = document.createElement('div');
          col.className = 'wall-col';
          col.style.setProperty('--speed', (phone ? 70 : 54) + c * 9 + 's');
          col.style.setProperty('--dir', c % 2 ? 'reverse' : 'normal');
          var lane = [];
          for (var k = 0; k < perLane; k++) lane.push(items[(n++) % items.length]);
          // two copies so the drift loops without a seam
          lane.concat(lane).forEach(function (img) {
            var clone = img.cloneNode(false);
            clone.removeAttribute('loading');
            col.appendChild(clone);
          });
          frag.appendChild(col);
        }
        wall.textContent = '';
        wall.appendChild(frag);
        wall.classList.add('is-live');
      };
      buildWall();
      var lastPhone = window.matchMedia('(max-width: 980px)').matches;
      window.addEventListener('resize', function () {
        var phone = window.matchMedia('(max-width: 980px)').matches;
        if (phone !== lastPhone) { lastPhone = phone; buildWall(); }
      });
    }
  }

  /* platform filter */
  var filters = document.querySelectorAll('.filters button');
  var cards = document.querySelectorAll('.game');
  Array.prototype.forEach.call(filters, function (btn) {
    btn.addEventListener('click', function () {
      var which = btn.getAttribute('data-filter');
      Array.prototype.forEach.call(filters, function (b) {
        b.setAttribute('aria-pressed', String(b === btn));
      });
      Array.prototype.forEach.call(cards, function (card) {
        var platforms = (card.getAttribute('data-platforms') || '').split(' ');
        card.hidden = which !== 'all' && platforms.indexOf(which) === -1;
      });
    });
  });

  /* screenshots dialog */
  var dialog = document.getElementById('shots');
  if (dialog && typeof dialog.showModal === 'function') {
    var strip = dialog.querySelector('.shots-strip');
    var heading = dialog.querySelector('#shots-title');
    var opener = null;

    document.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-shots]');
      if (!btn) return;
      var shots = [];
      try { shots = JSON.parse(btn.getAttribute('data-shots')); } catch (err) { return; }
      if (!shots.length) return;
      opener = btn;
      var title = btn.getAttribute('data-title') || '';
      heading.textContent = title;
      strip.textContent = '';
      shots.forEach(function (src, i) {
        var img = document.createElement('img');
        img.src = src;
        img.alt = title + ', screenshot ' + (i + 1) + ' of ' + shots.length;
        img.decoding = 'async';
        strip.appendChild(img);
      });
      strip.scrollLeft = 0;
      dialog.showModal();
      updateSteps();
      document.documentElement.style.overflow = 'hidden';
    });

    var stepButtons = dialog.querySelectorAll('[data-step]');
    var updateSteps = function () {
      var max = strip.scrollWidth - strip.clientWidth;
      stepButtons[0].disabled = strip.scrollLeft <= 4;
      stepButtons[1].disabled = strip.scrollLeft >= max - 4;
    };
    var step = function (dir) {
      var first = strip.querySelector('img');
      var by = first ? first.getBoundingClientRect().width + 14 : strip.clientWidth * 0.8;
      strip.scrollBy({ left: dir * by, behavior: reduceMotion ? 'auto' : 'smooth' });
    };
    Array.prototype.forEach.call(stepButtons, function (b) {
      b.addEventListener('click', function () { step(Number(b.getAttribute('data-step'))); });
    });
    strip.addEventListener('scroll', updateSteps, { passive: true });
    strip.addEventListener('load', updateSteps, true);
    dialog.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') { step(1); e.preventDefault(); }
      if (e.key === 'ArrowLeft') { step(-1); e.preventDefault(); }
    });

    var close = function () { if (dialog.open) dialog.close(); };
    dialog.addEventListener('close', function () {
      document.documentElement.style.overflow = '';
      if (opener) opener.focus({ preventScroll: true });
    });
    dialog.querySelector('[data-close]').addEventListener('click', close);
    // a tap outside the panel (on the backdrop) closes it
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog) close();
    });
  } else if (dialog) {
    dialog.remove();
  }

  /* gentle reveal on scroll */
  var revealables = document.querySelectorAll('.game, .skills li, .studio-text, .contact-inner, .section-head');
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var el = entry.target;
          el.classList.add('is-in');
          io.unobserve(el);
          // the stagger delay must not slow down hover effects later
          setTimeout(function () { el.style.transitionDelay = ''; }, 1000);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    Array.prototype.forEach.call(revealables, function (el, i) {
      el.classList.add('reveal');
      el.style.transitionDelay = (el.classList.contains('game') ? (i % 3) * 70 : 0) + 'ms';
      io.observe(el);
    });
  }
})();
