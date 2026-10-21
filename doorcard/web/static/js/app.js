(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  function startLoading() {
    const bar = document.getElementById("loading-bar");
    if (bar) {
      bar.classList.add("is-loading");
    }
  }

  function setupSidebar() {
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("menu-toggle");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (!sidebar || !toggle || !backdrop) {
      return;
    }

    function setOpen(open) {
      sidebar.classList.toggle("is-open", open);
      backdrop.classList.toggle("is-visible", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
      document.body.style.overflow = open ? "hidden" : "";
    }

    toggle.addEventListener("click", function () {
      setOpen(!sidebar.classList.contains("is-open"));
    });

    backdrop.addEventListener("click", function () {
      setOpen(false);
    });

    sidebar.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.innerWidth <= 1024) {
          setOpen(false);
        }
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && sidebar.classList.contains("is-open")) {
        setOpen(false);
        toggle.focus();
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 1024 && sidebar.classList.contains("is-open")) {
        setOpen(false);
      }
    });
  }

  function setupToasts() {
    document.querySelectorAll(".toast").forEach(function (toast) {
      const close = toast.querySelector(".toast-close");
      if (close) {
        close.addEventListener("click", function () {
          toast.remove();
        });
      }
      window.setTimeout(function () {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-6px)";
        window.setTimeout(function () {
          toast.remove();
        }, 250);
      }, 8000);
    });
  }

  function setupPasswordToggles() {
    document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
      button.addEventListener("click", function () {
        const input = document.getElementById(button.dataset.target);
        if (!input) {
          return;
        }
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        button.setAttribute("aria-label", show ? "Hide password" : "Show password");
        const eyeShow = button.querySelector("[data-eye-show]");
        const eyeHide = button.querySelector("[data-eye-hide]");
        if (eyeShow) {
          eyeShow.hidden = show;
        }
        if (eyeHide) {
          eyeHide.hidden = !show;
        }
      });
    });
  }

  function setupConfirmations() {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirm)) {
          event.preventDefault();
        }
      });
    });
  }

  function setupForms() {
    document.querySelectorAll("form[data-loading-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented || !form.checkValidity()) {
          return;
        }
        const button = form.querySelector('button[type="submit"]');
        if (button) {
          button.classList.add("is-submitting");
          button.setAttribute("aria-busy", "true");
          window.setTimeout(function () {
            button.disabled = true;
          }, 0);
        }
        startLoading();
      });
    });
  }

  function setupLinks() {
    document.querySelectorAll("a[href]").forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (event.defaultPrevented || event.button !== 0) {
          return;
        }
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return;
        }
        const href = link.getAttribute("href");
        if (!href || href.startsWith("#") || link.target === "_blank" || link.hasAttribute("download")) {
          return;
        }
        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin || url.pathname === window.location.pathname) {
          return;
        }
        startLoading();
      });
    });
  }

  ready(function () {
    setupSidebar();
    setupToasts();
    setupPasswordToggles();
    setupConfirmations();
    setupForms();
    setupLinks();
  });
})();
