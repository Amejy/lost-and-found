const root = document.documentElement;

const applyTheme = (theme) => {
  root.setAttribute("data-theme", theme);
  localStorage.setItem("lf-theme", theme);
};

const toggleTheme = () => {
  const currentTheme = root.getAttribute("data-theme") || "light";
  applyTheme(currentTheme === "dark" ? "light" : "dark");
};

const initializeThemeToggle = () => {
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", toggleTheme);
  });
};

const animateCounter = (element) => {
  const target = Number(element.dataset.counter || "0");
  if (Number.isNaN(target)) {
    return;
  }

  const duration = 900;
  const start = performance.now();

  const step = (now) => {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    element.textContent = Math.round(target * eased).toLocaleString();

    if (progress < 1) {
      window.requestAnimationFrame(step);
    }
  };

  window.requestAnimationFrame(step);
};

const initializeCounters = () => {
  const counters = document.querySelectorAll("[data-counter]");
  if (!counters.length) {
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          return;
        }
        animateCounter(entry.target);
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.35 }
  );

  counters.forEach((counter) => observer.observe(counter));
};

const resolveSparklineColor = (name) => {
  const styles = getComputedStyle(root);
  const palette = {
    primary: styles.getPropertyValue("--primary").trim(),
    accent: styles.getPropertyValue("--accent").trim(),
    warning: styles.getPropertyValue("--warning").trim(),
  };

  return palette[name] || palette.primary;
};

const initializeSparklines = () => {
  document.querySelectorAll("[data-sparkline]").forEach((element) => {
    const values = (element.dataset.sparkline || "")
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => !Number.isNaN(value));

    if (!values.length) {
      return;
    }

    const width = 240;
    const height = 76;
    const max = Math.max(...values, 1);
    const min = Math.min(...values);
    const range = Math.max(max - min, 1);
    const stroke = resolveSparklineColor(element.dataset.sparklineColor);
    const linePoints = values.map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / range) * (height - 12) - 6;
      return `${x},${y}`;
    });
    const areaPoints = [`0,${height}`, ...linePoints, `${width},${height}`].join(" ");

    element.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
        <polygon fill="${stroke}" fill-opacity="0.10" points="${areaPoints}"></polygon>
        <polyline fill="none" stroke="${stroke}" stroke-opacity="0.14" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" points="${linePoints.join(" ")}"></polyline>
        <polyline fill="none" stroke="${stroke}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" points="${linePoints.join(" ")}"></polyline>
      </svg>
    `;
  });
};

const initializeClaimPicker = () => {
  document.querySelectorAll("[data-claim-picker]").forEach((picker) => {
    const cards = picker.querySelectorAll("[data-claim-choice]");
    cards.forEach((card) => {
      card.addEventListener("click", () => {
        const targetSelector = card.dataset.claimSelect;
        const target = targetSelector ? document.querySelector(targetSelector) : null;
        if (!target) {
          return;
        }

        target.value = card.dataset.claimChoice || "0";
        cards.forEach((item) => item.classList.remove("is-selected"));
        card.classList.add("is-selected");
      });
    });
  });
};

const initializeSidebar = () => {
  const body = document.body;
  const backdrop = document.querySelector("[data-sidebar-backdrop]");
  const openButtons = document.querySelectorAll("[data-sidebar-toggle]");
  const closeButtons = document.querySelectorAll("[data-sidebar-close]");

  const closeSidebar = () => body.classList.remove("sidebar-open");
  const openSidebar = () => body.classList.add("sidebar-open");

  openButtons.forEach((button) => button.addEventListener("click", openSidebar));
  closeButtons.forEach((button) => button.addEventListener("click", closeSidebar));
  backdrop?.addEventListener("click", closeSidebar);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSidebar();
    }
  });
};

const dismissFlash = (element) => {
  element.classList.add("flash-leave");
  window.setTimeout(() => element.remove(), 220);
};

const initializeFlashes = () => {
  document.querySelectorAll("[data-autodismiss='true']").forEach((element) => {
    window.setTimeout(() => dismissFlash(element), 5000);
  });

  document.querySelectorAll("[data-flash-close]").forEach((button) => {
    button.addEventListener("click", () => {
      const flash = button.closest(".flash-message");
      if (flash) {
        dismissFlash(flash);
      }
    });
  });
};

const setLoadingState = (form, submitter) => {
  if (!submitter || submitter.dataset.loadingApplied === "true") {
    return;
  }

  submitter.dataset.loadingApplied = "true";
  submitter.classList.add("is-loading");
  submitter.disabled = true;

  if (submitter.tagName === "BUTTON") {
    submitter.dataset.originalHtml = submitter.innerHTML;
    submitter.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Working...</span>';
  }

  form.classList.add("is-submitting");
};

const initializeForms = () => {
  const confirmModalElement = document.getElementById("confirmActionModal");
  const confirmButton = document.getElementById("confirmActionButton");
  const confirmTitle = document.getElementById("confirmActionTitle");
  const confirmMessage = document.getElementById("confirmActionMessage");
  const confirmModal = confirmModalElement ? new bootstrap.Modal(confirmModalElement) : null;

  let pendingForm = null;
  let pendingSubmitter = null;

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("button, input[type='submit']");
    if (trigger?.form) {
      trigger.form._lastSubmitter = trigger;
      const decisionInput = trigger.form.querySelector("input[name='decision']");
      if (decisionInput && trigger.dataset.decision) {
        decisionInput.value = trigger.dataset.decision;
      }
    }
  });

  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const submitter = event.submitter || form._lastSubmitter || form.querySelector("[type='submit']");
      const confirmSource = (submitter && submitter.dataset.confirmMessage) ? submitter : form;
      const confirmText = confirmSource?.dataset.confirmMessage;

      if (confirmText && form.dataset.confirmed !== "true" && confirmModal) {
        event.preventDefault();
        pendingForm = form;
        pendingSubmitter = submitter;
        confirmTitle.textContent = confirmSource.dataset.confirmTitle || "Confirm action";
        confirmMessage.textContent = confirmText;
        confirmButton.textContent = confirmSource.dataset.confirmButton || "Continue";
        confirmModal.show();
        return;
      }

      form.dataset.confirmed = "false";

      if ((form.method || "get").toLowerCase() !== "get" || form.dataset.loadingForm === "true") {
        setLoadingState(form, submitter);
      }
    });
  });

  confirmButton?.addEventListener("click", () => {
    if (!pendingForm) {
      return;
    }

    pendingForm.dataset.confirmed = "true";
    confirmModal?.hide();

    const decisionInput = pendingForm.querySelector("input[name='decision']");
    if (decisionInput && pendingSubmitter?.dataset.decision) {
      decisionInput.value = pendingSubmitter.dataset.decision;
    }

    if (typeof pendingForm.requestSubmit === "function") {
      pendingForm.requestSubmit(pendingSubmitter || undefined);
    } else {
      pendingForm.submit();
    }
  });

  confirmModalElement?.addEventListener("hidden.bs.modal", () => {
    pendingForm = null;
    pendingSubmitter = null;
  });
};

document.addEventListener("DOMContentLoaded", () => {
  initializeThemeToggle();
  initializeSidebar();
  initializeFlashes();
  initializeForms();
  initializeCounters();
  initializeSparklines();
  initializeClaimPicker();

  if (window.lucide) {
    window.lucide.createIcons();
  }

  window.requestAnimationFrame(() => {
    document.body.classList.remove("page-loading");
    document.body.classList.add("page-ready");
  });
});
