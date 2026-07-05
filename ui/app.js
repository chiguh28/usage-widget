/**
 * usage-widget dumb renderer.
 *
 * All aggregation/business logic lives in Python (backend/aggregate.py).
 * This file only:
 *   - calls window.pywebview.api.* (bridge, always async/Promise-based)
 *   - maps the returned view-model (BreakdownVM / ComparisonVM) fields onto
 *     Chart.js datasets and plain DOM/table text
 *   - toggles which tab/banner is visible
 *
 * No token/percentage arithmetic happens here -- if you find yourself
 * summing or dividing values in this file, that logic belongs in
 * backend/aggregate.py instead.
 */
(function () {
  "use strict";

  var JP_STRINGS = {
    nodeMissing: "Node.js が見つかりません。Node.js をインストールしてください。",
    timeout: "ccusage の実行がタイムアウトしました。もう一度お試しください。",
    empty: "この期間のデータはありません。",
    copyConfirm: "コピーしました"
  };

  var state = {
    activeTab: "breakdown", // "breakdown" | "comparison"
    breakdownPeriod: "7d",
    comparisonPeriod: "7d",
    dimension: "model",
    agent: "all",
    lastBreakdownVm: null,
    lastComparisonVm: null
  };

  var charts = {
    breakdown: null,
    comparison: null
  };

  var els = {};

  function cacheEls() {
    els.tabButtons = Array.prototype.slice.call(document.querySelectorAll(".tab-button"));
    els.tabPanels = {
      breakdown: document.getElementById("tab-breakdown"),
      comparison: document.getElementById("tab-comparison")
    };
    els.bannerError = document.getElementById("banner-error");
    els.bannerErrorText = document.getElementById("banner-error-text");
    els.bannerRetry = document.getElementById("banner-retry");
    els.bannerEmpty = document.getElementById("banner-empty");

    els.dimensionSelect = document.getElementById("dimension-select");
    els.breakdownGrandTotal = document.getElementById("breakdown-grand-total");
    els.breakdownTableBody = document.getElementById("breakdown-table-body");
    els.breakdownCanvas = document.getElementById("breakdown-pie");
    els.comparisonCanvas = document.getElementById("comparison-bar");

    els.periodRadiosBreakdown = Array.prototype.slice.call(
      document.querySelectorAll('input[name="period-breakdown"]')
    );
    els.periodRadiosComparison = Array.prototype.slice.call(
      document.querySelectorAll('input[name="period-comparison"]')
    );

    els.copyJsonBtn = document.getElementById("copy-json-btn");
    els.copyMarkdownBtn = document.getElementById("copy-markdown-btn");
    els.copyConfirm = document.getElementById("copy-confirm");
  }

  // -- banners -------------------------------------------------------------

  function hideBanners() {
    els.bannerError.classList.remove("show");
    els.bannerEmpty.classList.remove("show");
    els.bannerRetry.classList.add("hidden");
  }

  function showErrorBanner(message, opts) {
    hideBanners();
    els.bannerErrorText.textContent = message;
    els.bannerError.classList.add("show");
    if (opts && opts.retry) {
      els.bannerRetry.classList.remove("hidden");
      els.bannerRetry.onclick = opts.retry;
    } else {
      els.bannerRetry.classList.add("hidden");
    }
  }

  function showEmptyBanner() {
    hideBanners();
    els.bannerEmpty.classList.add("show");
  }

  /**
   * Maps a bridge error response ({error, message}) to the JP banner
   * behavior specified in design doc section 6. Returns true if `payload`
   * was an error and a banner was shown (caller should stop rendering).
   */
  function handleErrorIfAny(payload, retryFn) {
    if (!payload || typeof payload !== "object" || !payload.error) {
      return false;
    }
    switch (payload.error) {
      case "node_missing":
        showErrorBanner(JP_STRINGS.nodeMissing);
        break;
      case "ccusage_timeout":
        showErrorBanner(JP_STRINGS.timeout, { retry: retryFn });
        break;
      case "ccusage_failed":
      case "ccusage_parse":
      default:
        showErrorBanner(payload.message || "エラーが発生しました。");
        break;
    }
    return true;
  }

  // -- tabs ------------------------------------------------------------------

  function setActiveTab(tab) {
    state.activeTab = tab;
    els.tabButtons.forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    Object.keys(els.tabPanels).forEach(function (key) {
      els.tabPanels[key].classList.toggle("active", key === tab);
    });
    hideBanners();
    if (tab === "breakdown") {
      refreshBreakdown();
    } else {
      refreshComparison();
    }
  }

  // -- breakdown tab -----------------------------------------------------

  function renderBreakdown(vm) {
    state.lastBreakdownVm = vm;

    if (!vm.grand_total_tokens || vm.grand_total_tokens === 0) {
      showEmptyBanner();
    } else {
      hideBanners();
    }

    els.breakdownGrandTotal.textContent =
      "合計トークン数: " +
      vm.grand_total_tokens.toLocaleString("ja-JP") +
      " / 合計コスト: $" +
      Number(vm.grand_total_cost).toFixed(2);

    renderBreakdownTable(vm.table);
    renderBreakdownChart(vm.slices);
  }

  function renderBreakdownTable(rows) {
    els.breakdownTableBody.innerHTML = "";
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      [
        row.label,
        row.input,
        row.output,
        row.cache_creation,
        row.cache_read,
        row.reasoning,
        row.total,
        Number(row.cost_usd).toFixed(2)
      ].forEach(function (value, idx) {
        var td = document.createElement("td");
        td.textContent = idx === 0 ? value : Number(value).toLocaleString("ja-JP");
        tr.appendChild(td);
      });
      els.breakdownTableBody.appendChild(tr);
    });
  }

  var PALETTE = [
    "#4f7cff",
    "#d97757",
    "#2fbf71",
    "#e0b400",
    "#9b59b6",
    "#e74c3c",
    "#1abc9c",
    "#7f8c8d"
  ];

  function renderBreakdownChart(slices) {
    var labels = slices.map(function (s) {
      return s.label;
    });
    var values = slices.map(function (s) {
      return s.value;
    });
    var colors = slices.map(function (_, i) {
      return PALETTE[i % PALETTE.length];
    });

    if (charts.breakdown) {
      charts.breakdown.data.labels = labels;
      charts.breakdown.data.datasets[0].data = values;
      charts.breakdown.data.datasets[0].backgroundColor = colors;
      charts.breakdown.update();
      return;
    }

    charts.breakdown = new Chart(els.breakdownCanvas, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [
          {
            data: values,
            backgroundColor: colors
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var slice = slices[ctx.dataIndex];
                return slice.label + ": " + slice.value.toLocaleString("ja-JP") + " (" + slice.pct + "%)";
              }
            }
          }
        }
      }
    });
  }

  function refreshBreakdown() {
    hideBanners();
    window.pywebview.api
      .get_breakdown(state.breakdownPeriod, state.dimension, state.agent)
      .then(function (vm) {
        if (handleErrorIfAny(vm, refreshBreakdown)) {
          return;
        }
        renderBreakdown(vm);
      })
      .catch(function (err) {
        showErrorBanner("予期しないエラーが発生しました: " + err);
      });
  }

  // -- comparison tab ------------------------------------------------------

  function renderComparison(vm) {
    state.lastComparisonVm = vm;

    var totalTokens = (vm.totals && (vm.totals.claude + vm.totals.codex)) || 0;
    if (!vm.models || vm.models.length === 0 || totalTokens === 0) {
      showEmptyBanner();
    } else {
      hideBanners();
    }

    renderComparisonChart(vm);
  }

  function renderComparisonChart(vm) {
    var labels = vm.models || [];
    var claudeData = (vm.series && vm.series.claude) || [];
    var codexData = (vm.series && vm.series.codex) || [];

    if (charts.comparison) {
      charts.comparison.data.labels = labels;
      charts.comparison.data.datasets[0].data = claudeData;
      charts.comparison.data.datasets[1].data = codexData;
      charts.comparison.update();
      return;
    }

    charts.comparison = new Chart(els.comparisonCanvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Claude Code",
            data: claudeData,
            backgroundColor: "#d97757"
          },
          {
            label: "Codex",
            data: codexData,
            backgroundColor: "#4f7cff"
          }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } }
        },
        scales: {
          x: { beginAtZero: true }
        }
      }
    });
  }

  function refreshComparison() {
    hideBanners();
    window.pywebview.api
      .get_comparison(state.comparisonPeriod)
      .then(function (vm) {
        if (handleErrorIfAny(vm, refreshComparison)) {
          return;
        }
        renderComparison(vm);
      })
      .catch(function (err) {
        showErrorBanner("予期しないエラーが発生しました: " + err);
      });
  }

  // -- copy buttons ----------------------------------------------------------

  function flashCopyConfirm() {
    els.copyConfirm.textContent = JP_STRINGS.copyConfirm;
    els.copyConfirm.classList.add("show");
    setTimeout(function () {
      els.copyConfirm.classList.remove("show");
    }, 1800);
  }

  function bindCopyButtons() {
    els.copyJsonBtn.addEventListener("click", function () {
      window.pywebview.api
        .copy_json(state.breakdownPeriod, state.dimension, state.agent)
        .then(function (res) {
          if (handleErrorIfAny(res)) {
            return;
          }
          flashCopyConfirm();
        });
    });

    els.copyMarkdownBtn.addEventListener("click", function () {
      window.pywebview.api.copy_markdown(state.breakdownPeriod).then(function (res) {
        if (handleErrorIfAny(res)) {
          return;
        }
        flashCopyConfirm();
      });
    });
  }

  // -- wiring ------------------------------------------------------------

  function bindTabs() {
    els.tabButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setActiveTab(btn.dataset.tab);
      });
    });
  }

  function bindBreakdownControls() {
    els.periodRadiosBreakdown.forEach(function (radio) {
      radio.addEventListener("change", function () {
        if (radio.checked) {
          state.breakdownPeriod = radio.value;
          refreshBreakdown();
        }
      });
    });

    els.dimensionSelect.addEventListener("change", function () {
      state.dimension = els.dimensionSelect.value;
      refreshBreakdown();
    });
  }

  function bindComparisonControls() {
    els.periodRadiosComparison.forEach(function (radio) {
      radio.addEventListener("change", function () {
        if (radio.checked) {
          state.comparisonPeriod = radio.value;
          refreshComparison();
        }
      });
    });
  }

  /**
   * Called by app/poller.py (via window.evaluate_js) with a fresh VM for
   * whichever tab is currently active. `vm` shape matches either
   * BreakdownVM or ComparisonVM depending on state.activeTab; the poller
   * (T-108) is responsible for requesting the VM that matches the active
   * tab/period/dimension the user currently has selected.
   */
  window.onUsageRefresh = function (vm) {
    if (handleErrorIfAny(vm, state.activeTab === "breakdown" ? refreshBreakdown : refreshComparison)) {
      return;
    }
    if (state.activeTab === "breakdown") {
      renderBreakdown(vm);
    } else {
      renderComparison(vm);
    }
  };

  function init() {
    cacheEls();
    bindTabs();
    bindBreakdownControls();
    bindComparisonControls();
    bindCopyButtons();
    refreshBreakdown();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
