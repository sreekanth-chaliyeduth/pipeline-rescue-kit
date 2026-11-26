/* Pipeline Rescue Kit: evidence-driven static site.
   All measurements come from data.json. No analytics, no external requests. */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  function h(tag, props) {
    var node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (key) {
        if (key === "class") node.className = props[key];
        else if (key === "text") node.textContent = props[key];
        else if (key === "html") node.innerHTML = props[key];
        else node.setAttribute(key, props[key]);
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child == null) continue;
      if (Array.isArray(child)) child.forEach(function (c) { if (c) node.appendChild(c); });
      else if (typeof child === "string") node.appendChild(document.createTextNode(child));
      else node.appendChild(child);
    }
    return node;
  }

  function svg(tag, attrs, text) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text != null) node.textContent = text;
    return node;
  }

  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Evidence links resolve from the reviewed main commit through the public
     v1.0.0 tag. The local tree is checked against the same paths before
     publication. */
  var EVIDENCE_BASE = "https://github.com/sreekanth-chaliyeduth/pipeline-rescue-kit/blob/v1.0.0/";

  function safeRepoPath(path) {
    if (!path || /^[a-z]+:/i.test(path) || path.indexOf("..") !== -1) return null;
    if (!/^(evidence|harness)\//.test(path)) return null;
    return path;
  }

  function repoHref(path) {
    var safe = safeRepoPath(path);
    return safe ? EVIDENCE_BASE + safe : null;
  }

  function repoLink(path, text) {
    var href = repoHref(path);
    if (!href) return document.createTextNode(text || path);
    return h("a", { class: "evidence-link", href: href, text: text || path });
  }

  function repoNodes(text) {
    var out = [], last = 0;
    var re = /(?:evidence|harness)\/[A-Za-z0-9_./-]*[A-Za-z0-9_/-]/g, match;
    while ((match = re.exec(text)) !== null) {
      if (match.index > last) out.push(document.createTextNode(text.slice(last, match.index)));
      out.push(repoLink(match[0]));
      last = match.index + match[0].length;
    }
    if (last < text.length) out.push(document.createTextNode(text.slice(last)));
    return out;
  }

  /* Run fn once when el scrolls into view. Reduced motion or no observer: run now. */
  function onVisible(el, fn) {
    if (!el) return;
    if (REDUCED || !("IntersectionObserver" in window)) { fn(); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { io.disconnect(); fn(); }
      });
    }, { threshold: 0.3 });
    io.observe(el);
  }

  /* Restart a CSS transition: remove the class, let the browser paint, add it again. */
  function replay(el, cls) {
    el.classList.remove(cls);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { el.classList.add(cls); });
    });
  }

  function fmtMs(ms) {
    return (ms / 1000).toFixed(1) + " s";
  }

  function countWord(n) {
    var words = ["Zero", "One", "Two", "Three", "Four", "Five",
      "Six", "Seven", "Eight", "Nine", "Ten"];
    return words[n] || String(n);
  }

  function runName(run) {
    var variant = VARIANT_NAME[run.variant] || run.variant;
    var parts = String(run.label).split("-");
    return variant + " " + parts[parts.length - 1];
  }

  function short(sha) {
    return typeof sha === "string" ? sha.slice(0, 12) : sha;
  }

  function badge(state) {
    var text = String(state || "UNKNOWN");
    var cls = "status-badge status-info";
    if (text === "PASS" || text === "SUCCESS" || text === "PASSED" || text === "PUBLISHED") cls = "status-badge status-pass";
    if (text === "FAIL" || text === "FAILURE" || text === "BLOCK" || text === "FAILED") cls = "status-badge status-fail";
    if (text === "NOT_BUILT" || text === "NOT EVALUATED") cls = "status-badge status-info";
    return h("span", { class: cls, text: text });
  }

  /* Plain-language presentation copy. Evidence records are not changed; these maps only
     decide how the page words them. */
  var VARIANT_NAME = { baseline: "Original", rescued: "New", control: "New + packaging" };

  var PROBLEM_COPY = {
    "repeated-reactor": ["Every part was built twice",
      "The build compiled and packaged every part with the tests switched off, then started over to run the tests."],
    "second-test-pass": ["Tests ran in a second, separate pass",
      "Running the tests separately repeats the setup work for every part. It adds time without adding any check."],
    "report-only-pmd": ["Code-quality warnings could never stop a merge",
      "The code-quality checker ran, but only wrote a report. Nothing failed when new warnings appeared."],
    "report-only-jacoco": ["Test coverage could fall without anything failing",
      "Coverage was recorded, but no minimum was set, so less-tested code could still be merged."],
    "false-docker-success": ["Docker steps printed success without running",
      "The steps that build and publish container images were commented out, but their success messages still printed."],
    "unsafe-docker-login": ["The registry password was typed on the command line",
      "A password passed this way can appear in logs. I removed this step from my copy rather than run it."],
    "no-timeout-and-cache": ["No time limit and no download cache",
      "A stuck build could run without limit, and every build downloaded its dependencies again. I added a time limit for my runs; I did not add a cache."]
  };
  var PROBLEMS_SHOWN = 4;

  var REVIEW_COPY = {
    "packaging-control": ["Speed claim",
      "I reported my new build as much faster than the original.",
      "The two builds did different amounts of work: the original packaged every part, mine packaged only the parts whose tests passed. The number overstated the gain.",
      "I re-ran my build with the packaging work restored. The gap shrank and the runs overlapped, so I withdrew the claim."],
    "selector-safeguards": ["Building too little",
      "The first version of the selection script chose parts from file paths alone.",
      "A change it did not recognise, or a change to a shared build file, could have been built too narrowly, so a broken change might look fine.",
      "Anything unknown, and any change to the top-level build files, now triggers a full build. Five test cases and a separate test suite check this."],
    "reference-contamination": ["What new warnings are compared against",
      "The check compared each change with the warnings in its own earlier builds.",
      "If a bad change was ever built, its warnings would become the normal level, and later bad changes would pass.",
      "A separate clean build of the main code, fixed to a known commit, now provides the comparison point."],
    "immutable-library-releases": ["Library versions that could not be rebuilt",
      "The shared library's versions lived in a temporary copy of the repository.",
      "Someone starting from a fresh copy could not get the exact version my results were recorded with.",
      "Versions are now permanent tags in the project itself, and setup checks that they exist instead of creating them."],
    "git-forensics-attribution": ["Measuring the wrong code",
      "Jenkins worked out the changed lines and new warnings from the shared library's code, not the application's.",
      "The checks could pass or block for reasons unrelated to the change being reviewed.",
      "The library is left out of change tracking, and the checks are told which code is the application. The warning test change now fails on that check alone."]
  };

  var FIGURE_COPY = {
    "multibranch-branches": "Jenkins's list of the test branches. The screenshot shows failed builds #12 and #14; the interactive demonstration uses #11 and #13, and their recorded outcomes match. Red means the check blocked the change, as intended; green means it passed.",
    "coverage-overview": "Untested change: Jenkins's coverage page. The whole application stays above its 90% limit.",
    "coverage-modified-lines": "The same build: none of the lines this change added are tested, so the second check blocks it.",
    "pmd-new-issue": "Code-quality warning change: Jenkins lists exactly one warning that is new compared with the main code.",
    "selector-decision": "The script's own output for a one-service change: the file that changed and the parts it chose."
  };

  var SUPERSEDED_LIMITS = [
    "No M4 incremental scope reduction is included.",
    "M5, quality gates and the shared library are not started."
  ];

  var CORRECTED_LIMITS = {
    "The ts-common scenario selects 42 dependent module entries; the aggregator root is not in that reactor.":
      "Correction: this line is wrong. The recorded 42-part list starts with the top-level project (ts-service-cluster). See evidence/M4/scenarios.json and evidence/M4/raw/scenarios/ts-common.log."
  };

  var GATE_REASON = {
    "modified lines": "the changed lines are not tested enough",
    "pmd": "the change adds a code-quality warning",
    "project": "the whole application fell below its coverage limit"
  };

  function sourceLine(source) {
    return h("p", { class: "evidence small" }, "Evidence: ", repoLink(source));
  }

  function renderProblems(problems) {
    var root = document.getElementById("problems");
    var more = document.getElementById("problems-more");
    problems.forEach(function (p, index) {
      var copy = PROBLEM_COPY[p.id] || [p.id.replace(/-/g, " "), p.explanation];
      var card = h("article", { class: "problem" },
        h("h3", { text: copy[0] }),
        h("p", { text: copy[1] }),
        h("div", { class: "quote", text: p.text }),
        h("p", { class: "where" }, "Build file line " + p.source_line + " · ", repoNodes(p.evidence_reference))
      );
      (index < PROBLEMS_SHOWN || !more ? root : more).appendChild(card);
    });
  }

  /* Fill every <span data-n="key"> from data.json. The HTML holds the same values as a
     fallback, so the page still reads correctly if a value is missing. */
  function bindNumbers(data) {
    var fr = data.full_reactor;
    var sel = data.selective_builds;
    var med = fr.medians;
    var main = data.quality_gates.petclinic.pr.filter(function (e) { return e.scenario === "main"; })[0];
    var packaged = fr.control_comparison.packaging &&
      fr.control_comparison.packaging.rescued_verify_counts;
    var values = {
      full: sel.full_reactor.reactor_entries,
      sel: sel.service_change.reactor_entries,
      selTests: sel.service_change.tests,
      selTime: (sel.service_change.median_ms / 1000).toFixed(1),
      tests: fr.conditions.tests,
      failing: fr.conditions.failed_or_errored,
      failingUpstream: fr.conditions.upstream_failed_or_errored,
      packagedNew: packaged ? packaged.SUCCESS : null,
      firstClaim: ((med.baseline.median_ms - med.rescued.median_ms) / med.baseline.median_ms * 100).toFixed(1),
      controlPct: Number(fr.control_comparison.median_difference_pct_of_baseline).toFixed(1),
      runsWord: countWord(fr.runs.length).toLowerCase(),
      mainWarnings: main && main.pmd ? main.pmd.total : null
    };
    document.querySelectorAll("[data-n]").forEach(function (el) {
      var v = values[el.getAttribute("data-n")];
      if (v != null && v !== "") el.textContent = String(v);
    });
  }

  function gateMetric(label, state, value, noLines) {
    var text = noLines ? "no lines" : (value || "n/a");
    var pct = value && /%$/.test(value) ? parseFloat(value) : null;
    var ok = state === "SUCCESS";
    var block = h("div", { class: "gate-metric" },
      h("div", { class: "value-row" },
        h("span", { class: "value " + (ok ? "value-pass" : "value-fail"), text: text }),
        h("strong", { class: "gate-state " + (ok ? "gate-pass-text" : "gate-fail-text"),
          text: ok ? "PASS" : "FAIL" })),
      h("span", { class: "label", text: label }),
      h("div", { class: "gate-bar " + (ok ? "pass" : "fail") }));
    if (pct != null) {
      var width = pct <= 0 ? 0 : Math.max(2, Math.min(100, pct));
      block.lastChild.appendChild(h("span", { style: "width:" + width + "%" }));
    }
    return block;
  }

  function gateCard(kicker, title, entry, note) {
    var project = entry.project || {};
    var modified = entry.modified_lines || {};
    var card = h("div", { class: "gate-card" },
      h("p", { class: "gate-kicker", text: kicker }),
      h("h3", { text: title }),
      h("div", { class: "big-values" },
        gateMetric("whole app tested · needs 90%", project.gate, project.value, false),
        gateMetric("change tested · needs 80%", modified.gate, modified.value, modified.no_modified_lines)));
    if (entry.pmd) {
      card.appendChild(h("div", { class: "gate-verdict" },
        h("span", { class: "status-badge " + (entry.pmd.gate === "SUCCESS" ? "status-pass" : "status-fail"),
          text: entry.pmd.new + " new code-quality " + (entry.pmd.new === 1 ? "warning" : "warnings") }),
        h("span", { class: "small", text: entry.pmd.total + " in total" })));
    }
    card.appendChild(h("div", { class: "gate-verdict" },
      badge(entry.decision),
      h("span", { class: "small", text: "Jenkins build #" + entry.build })));
    if (note) card.appendChild(h("p", { class: "small", text: note }));
    return card;
  }

  function renderGateHighlights(data) {
    var root = document.getElementById("gate-highlights");
    if (!root) return;
    var pr = data.quality_gates.petclinic.pr;
    var small = pr.filter(function (e) { return e.scenario === "small-untested-change-1"; })[0];
    var pmd = pr.filter(function (e) { return e.scenario === "pmd-violation-1"; })[0];
    var cards = 0;
    if (small) {
      root.appendChild(gateCard("Blocked by check 2", "Untested change", small, ""));
      cards += 1;
    }
    if (pmd) {
      var pmdNew = pmd.pmd.new;
      root.appendChild(gateCard("Blocked by check 3", "Code-quality warning", pmd, ""));
      cards += 1;
    }
    root.classList.add("motion");
    onVisible(root, function () { root.classList.add("play"); });
  }

  function renderBenchmark(fr) {
    var runs = fr.runs;
    var counts = { baseline: 0, rescued: 0, control: 0 };
    runs.forEach(function (run) { counts[run.variant] = (counts[run.variant] || 0) + 1; });
    var chart = document.getElementById("benchmark-chart");
    var summary = document.getElementById("benchmark-summary");
    var cmp = fr.control_comparison;
    if (summary) {
      summary.textContent = "Original and New + packaging overlap between " +
        fmtMs(cmp.overlap_range_ms[0]) + " and " + fmtMs(cmp.overlap_range_ms[1]) + ".";
    }
    var variants = [["baseline", VARIANT_NAME.baseline], ["rescued", VARIANT_NAME.rescued], ["control", VARIANT_NAME.control]];
    var maxMs = Math.max.apply(null, runs.map(function (r) { return r.jenkins_duration_ms; }));
    var maxS = Math.ceil(maxMs / 1000 / 100) * 100;
    var currentFilter = "all";

    function applyFilter(el) {
      el.querySelectorAll("g[data-variant]").forEach(function (g) {
        g.style.display = (currentFilter === "all" || g.getAttribute("data-variant") === currentFilter) ? "" : "none";
      });
    }

    function draw() {
      chart.innerHTML = "";
      var width = Math.max(280, chart.clientWidth);
      var compact = width < 560;
      var W = width, H = compact ? 330 : 390;
      var L = compact ? 104 : 136, R = compact ? 10 : 24, T = compact ? 22 : 30, B = compact ? 44 : 54;
      var plotW = W - L - R;
      var rowGap = compact ? 82 : 96;
      var fs = compact ? 9 : 11;
      var el = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
        "aria-labelledby": "bench-title bench-desc" });
      el.appendChild(svg("title", { id: "bench-title" },
        countWord(runs.length) + " full builds of Train-Ticket"));
      el.appendChild(svg("desc", { id: "bench-desc" },
        countWord(runs.length) + " builds: " + countWord(counts.baseline).toLowerCase() + " original, " +
        countWord(counts.rescued).toLowerCase() + " new and " +
        countWord(counts.control).toLowerCase() + " new with packaging restored. " +
        "Dots show each build's time; dashed lines show the middle value."));
      var axis = svg("g", { class: "axis" });
      axis.appendChild(svg("line", { x1: L, y1: H - B + 4, x2: W - R, y2: H - B + 4 }));
      var tickStep = compact ? 200 : 100;
      for (var tick = 0; tick <= maxS; tick += tickStep) {
        var x = L + (tick / maxS) * plotW;
        axis.appendChild(svg("line", { x1: x, y1: H - B + 4, x2: x, y2: H - B + 9 }));
        axis.appendChild(svg("text", { x: x, y: H - B + 22, "text-anchor": "middle", "font-size": fs }, tick + "s"));
      }
      el.appendChild(axis);
      variants.forEach(function (pair, index) {
        var key = pair[0], label = pair[1];
        var group = runs.filter(function (r) { return r.variant === key; });
        var median = fr.medians[key];
        var y = T + 26 + index * rowGap;
        var g = svg("g", { "data-variant": key });
        g.appendChild(svg("text", { x: 4, y: y + 3, "font-size": fs + 1, "font-weight": "600" }, label));
        g.appendChild(svg("text", { x: 4, y: y + 16, "font-size": fs }, fmtMs(median.median_ms)));
        var rangeX1 = L + (median.min_ms / 1000 / maxS) * plotW;
        var rangeX2 = L + (median.max_ms / 1000 / maxS) * plotW;
        g.appendChild(svg("line", { x1: rangeX1, y1: y, x2: rangeX2, y2: y, stroke: "#c9c1b4", "stroke-width": 2 }));
        var medX = L + (median.median_ms / 1000 / maxS) * plotW;
        g.appendChild(svg("line", { x1: medX, y1: y - 18, x2: medX, y2: y + 18, stroke: "#a4471f", "stroke-width": 2, "stroke-dasharray": "4 3" }));
        group.forEach(function (run, runIndex) {
          var dotX = L + (run.jenkins_duration_ms / 1000 / maxS) * plotW;
          var jitter = group.length > 1 ? (runIndex - (group.length - 1) / 2) * (compact ? 11 : 12) : 0;
          var dotY = y + jitter;
          var dot = svg("g", { class: "run-dot", tabindex: "0", role: "button",
            "aria-label": runName(run) + ", " + fmtMs(run.jenkins_duration_ms) +
              ", build " + run.build });
          dot.appendChild(svg("circle", { cx: dotX, cy: dotY, r: 7,
            fill: "#2c5f5b", stroke: "#f7f4ee", "stroke-width": 2 }));
          dot.addEventListener("click", function () { selectRun(run, fr); });
          dot.addEventListener("keydown", function (event) {
            if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectRun(run, fr); }
          });
          g.appendChild(dot);
        });
        el.appendChild(g);
      });
      applyFilter(el);
      chart.appendChild(el);
    }
    draw();
    var resizeTimer = null;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(draw, 150);
    });

    var chips = document.querySelectorAll(".chart-toolbar .chip");
    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        chips.forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
        chip.setAttribute("aria-pressed", "true");
        currentFilter = chip.getAttribute("data-variant");
        applyFilter(chart);
      });
    });

    var picker = document.getElementById("benchmark-runs");
    if (picker) {
      picker.innerHTML = "";
      runs.forEach(function (run) {
        var button = h("button", { type: "button", class: "run-pick",
          "aria-pressed": "false", "data-run": run.label });
        button.appendChild(h("span", { class: "run-pick-name", text: runName(run) }));
        button.appendChild(h("span", { class: "run-pick-meta",
          text: "Build #" + run.build + " · " + fmtMs(run.jenkins_duration_ms) }));
        button.addEventListener("click", function () { selectRun(run, fr); });
        picker.appendChild(button);
      });
    }

    var table = document.getElementById("benchmark-table");
    var wrap = h("div", { class: "table-wrap" });
    var tbl = h("table");
    tbl.appendChild(h("thead", null, h("tr", null,
      h("th", { text: "Build type" }), h("th", { text: "Run" }), h("th", { text: "Build" }),
      h("th", { text: "Result" }), h("th", { text: "Time in Jenkins" }),
      h("th", { text: "Time on the machine" }), h("th", { text: "Source" }))));
    var body = h("tbody");
    runs.forEach(function (run) {
      body.appendChild(h("tr", null,
        h("td", { text: VARIANT_NAME[run.variant] || run.variant }), h("td", { text: run.label }),
        h("td", { text: "#" + run.build }), h("td", null, badge(run.result)),
        h("td", { text: fmtMs(run.jenkins_duration_ms) }),
        h("td", { text: run.host_wall_clock_s + " s" }),
        h("td", null, repoLink(run.source))));
    });
    tbl.appendChild(body);
    wrap.appendChild(tbl);
    table.appendChild(wrap);
  }

  function selectRun(run, fr) {
    var picker = document.getElementById("benchmark-runs");
    if (picker) {
      picker.querySelectorAll("button").forEach(function (button) {
        button.setAttribute("aria-pressed",
          button.getAttribute("data-run") === run.label ? "true" : "false");
      });
    }
    var panel = document.getElementById("benchmark-detail");
    panel.innerHTML = "";
    panel.appendChild(h("h4", { text: runName(run) + " · build #" + run.build }));
    var dl = h("dl", { class: "detail-grid" },
      h("div", null, h("dt", { text: "Time in Jenkins" }), h("dd", { text: fmtMs(run.jenkins_duration_ms) })),
      h("div", null, h("dt", { text: "Time on the machine" }), h("dd", { text: run.host_wall_clock_s + " s" })),
      h("div", null, h("dt", { text: "Jenkins result" }), h("dd", null, badge(run.result))),
      h("div", null, h("dt", { text: "Jenkins job" }), h("dd", { text: run.job })),
      h("div", null, h("dt", { text: "Record type" }), h("dd", { text: run.classification })),
      h("div", null, h("dt", { text: "Build command (New + packaging)" }), h("dd", { text: fr.conditions.maven_command }))
    );
    panel.appendChild(dl);
    if (run.result === "FAILURE" || run.result === "UNSTABLE") {
      panel.appendChild(h("p", { class: "note-line", text: "A red result here comes from Train-Ticket's own failing tests, not from the build steps being measured." }));
    }
    panel.appendChild(sourceLine(run.source));
  }

  function renderReactor(count, label, total) {
    var root = document.getElementById("reactor-illustration");
    var full = total || 43;
    root.innerHTML = "";
    root.setAttribute("aria-label", "Parts of Train-Ticket: " + label);
    for (var i = 0; i < full; i++) {
      var cell = h("span", { class: i < count ? (count === full ? "full" : "on") : "" });
      if (i < count && !REDUCED) cell.style.transitionDelay = (i * 18) + "ms";
      root.appendChild(cell);
    }
    var panel = root.closest(".reactor-panel");
    if (panel && panel.classList.contains("play")) replay(panel, "play");
    var counter = document.getElementById("reactor-count");
    if (counter) counter.textContent = String(count);
    var of = document.getElementById("reactor-of");
    if (of) of.textContent = "of " + full;
    var caption = document.getElementById("reactor-label");
    if (caption) caption.textContent = label;
  }

  function renderModules(modules) {
    var root = document.getElementById("selected-modules");
    if (!root) return;
    root.innerHTML = "";
    if (!modules.length) {
      root.appendChild(h("span", { class: "module-pill muted", text: "nothing to build" }));
      return;
    }
    var labels = modules.map(function (name) { return name.replace(/ [0-9.]+$/, ""); });
    labels.forEach(function (name) {
      root.appendChild(h("span", { class: "module-pill", text: name }));
    });
    if (labels.filter(function (name) { return name === "ts-consign-price-service"; }).length > 1) {
      root.appendChild(h("p", { class: "small", text: "Two parts show as ts-consign-price-service because Train-Ticket's own build files give ts-consign-service the same display name. They are different parts." }));
    }
  }

  var CASE_NAME = {
    "one-service": "One service",
    "ts-common": "Shared library",
    "root-pom": "Top-level build file",
    "non-maven-directory": "Non-code folder",
    "documentation-only": "Docs only"
  };
  var CASE_COPY = {
    "one-service": function (e, total) {
      return "A file in one service (ts-order-service) changed. The script builds it plus the parts it needs: the shared library and the top-level project definition.";
    },
    "ts-common": function (e, total) {
      return "The shared library (ts-common) changed. Almost every service uses it, so everything that depends on it is rebuilt.";
    },
    "root-pom": function (e, total) {
      return "The top-level build file (pom.xml) changed. That can affect every part, so the script does not guess: all " + total + " are built.";
    },
    "non-maven-directory": function () {
      return "A file outside the Java build changed (the image folder). No part of the build is affected, so nothing is rebuilt.";
    },
    "documentation-only": function () {
      return "Only documentation changed. No part of the build is affected, so nothing is rebuilt.";
    }
  };

  function renderSelective(sel) {
    var list = document.getElementById("selector-cases");
    var detail = document.getElementById("selector-detail");
    var total = sel.full_reactor.reactor_entries;
    var summary = document.getElementById("selector-summary");
    var title = document.getElementById("selective-title");
    function show(entry) {
      document.querySelectorAll("#selector-cases button, #selector-chips button").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-name") === entry.name ? "true" : "false");
      });
      detail.innerHTML = "";
      detail.appendChild(h("h4", { text: entry.name + " · " + entry.changed_path }));
      detail.appendChild(h("dl", { class: "detail-grid" },
        h("div", null, h("dt", { text: "Decision" }), h("dd", null, badge(entry.mode === "modules" ? "SOME PARTS" : entry.mode === "full" ? "ALL PARTS" : "NOTHING"))),
        h("div", null, h("dt", { text: "Maven scope" }), h("dd", { text: entry.modules_flag || "n/a" })),
        h("div", null, h("dt", { text: "Upstream -am" }), h("dd", { text: entry.upstream ? "yes" : "no" })),
        h("div", null, h("dt", { text: "Downstream -amd" }), h("dd", { text: entry.downstream ? "yes" : "no" })),
        h("div", null, h("dt", { text: "Parts built" }), h("dd", { text: String(entry.reactor_count) })),
        h("div", null, h("dt", { text: "Maven exit" }), h("dd", { text: String(entry.exit_code) }))
      ));
      detail.appendChild(h("p", { class: "note-line", text: "Reason: " + entry.reason }));
      if (entry.selected_modules.length) {
        detail.appendChild(h("p", { class: "small", text: "Modules: " + entry.selected_modules.join(", ") }));
      }
      detail.appendChild(sourceLine(entry.source));
      renderReactor(entry.reactor_count,
        entry.mode === "full" ? "All " + total + " parts built"
          : entry.mode === "none" ? "No parts built"
            : entry.reactor_count + " of " + total + " parts built", total);
      renderModules(entry.mode === "full" ? [] : entry.selected_modules);
      if (summary) {
        var explain = CASE_COPY[entry.name];
        summary.textContent = explain ? explain(entry, total)
          : "Changed file: " + entry.changed_path + ".";
      }
    }
    sel.selector_cases.forEach(function (entry) {
      var b = h("button", { class: "case-button", type: "button", "aria-pressed": "false",
        "data-name": entry.name },
        CASE_NAME[entry.name] || entry.name,
        h("span", { text: entry.reactor_count + " of " + total + " parts" }));
      b.addEventListener("click", function () { show(entry); });
      list.appendChild(b);
    });
    var chips = document.getElementById("selector-chips");
    var chipNames = CASE_NAME;
    if (chips) {
      sel.selector_cases.forEach(function (entry) {
        var c = h("button", { class: "chip", type: "button", "aria-pressed": "false",
          "data-name": entry.name, text: chipNames[entry.name] || entry.name });
        c.addEventListener("click", function () { show(entry); });
        chips.appendChild(c);
      });
    }
    var reactorPanel = document.querySelector(".reactor-panel");
    if (reactorPanel) {
      reactorPanel.classList.add("motion");
      onVisible(reactorPanel, function () { reactorPanel.classList.add("play"); });
    }
    show(sel.selector_cases[0]);
    var policy = document.getElementById("selector-policy");
    if (policy) policy.textContent = "When unsure, it builds all " + total + " parts: after a top-level build file change, an unknown build file, or any script error.";
    var method = document.getElementById("selector-method");
    if (method) method.textContent = "Maven itself adds the parts each chosen part needs and the parts that depend on it.";
  }

  var EXPECTED = {
    main: "pass; this is the reference build every change is compared against",
    small: "blocked by check 2, because the new lines are not tested",
    pmd: "blocked by check 3 only, because it adds one code-quality warning",
    fixed: "pass every check",
    docs: "pass, with no code lines to measure"
  };

  function scenarioKind(name) {
    if (name === "main") return "main";
    if (name.indexOf("small") === 0) return "small";
    if (name.indexOf("pmd") === 0) return "pmd";
    if (name === "fixed") return "fixed";
    return "docs";
  }

  function scenarioLabel(name) {
    var map = {
      main: "Main code (reference)",
      "small-untested-change-1": "Untested change · run 1",
      "small-untested-change-2": "Untested change · run 2",
      "pmd-violation-1": "Code-quality warning · run 1",
      "pmd-violation-2": "Code-quality warning · run 2",
      fixed: "Fixed change",
      "docs-only": "Docs-only change"
    };
    return map[name] || name;
  }

  function byNameFrom(list, name) {
    return list.filter(function (e) { return e.scenario === name; })[0];
  }

  /* Hero: one recorded pull request at a time, its three gates, then the decision. */
  function renderStrip(pr) {
    var root = document.getElementById("pr-strip");
    if (!root) return;
    var picks = [
      ["small-untested-change-1", "Untested change", "Adds new code with no test for it."],
      ["pmd-violation-1", "Code-quality warning", "Adds tested code that contains one code-quality problem."],
      ["fixed", "Fixed change", "The untested change with its test added, plus a second small class with its own test."]
    ];
    var purpose = {};
    picks.forEach(function (p) { purpose[p[0]] = p[2]; });
    var mainEntry = byNameFrom(pr, "main");
    var byName = {};
    pr.forEach(function (e) { byName[e.scenario] = e; });
    picks = picks.filter(function (p) { return byName[p[0]]; });
    if (!picks.length) return;
    var chips = h("div", { class: "chip-row", role: "group", "aria-label": "Test change" });
    var body = h("div", { class: "strip-body motion", "aria-live": "polite" });
    var caption = h("figcaption");
    root.appendChild(h("p", { class: "strip-kicker", text: "Recorded merge decisions" }));
    root.appendChild(chips);
    root.appendChild(body);
    root.appendChild(caption);

    function step(i, label, value, state, extra, rule) {
      var ok = state === "SUCCESS" || state === "PASS";
      var labelNode = h("span", { class: "strip-label", text: label });
      if (rule) labelNode.appendChild(h("span", { class: "strip-rule", text: rule }));
      var li = h("li", { class: "strip-step " + (ok ? "ok" : "bad"), style: "--i:" + i },
        h("span", { class: "strip-dot", "aria-hidden": "true" }),
        labelNode,
        h("span", { class: "strip-value", text: value }),
        badge(state === "SUCCESS" ? "PASS" : state === "FAILURE" ? "FAIL" : state));
      if (extra) li.appendChild(h("span", { class: "strip-reason", text: extra }));
      return li;
    }

    function draw(name) {
      var e = byName[name];
      chips.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-name") === name ? "true" : "false");
      });
      var ml = e.modified_lines || {};
      var gates = e.failing_gates || [];
      body.innerHTML = "";
      var already = mainEntry && mainEntry.pmd ? mainEntry.pmd.total : null;
      body.appendChild(h("p", { class: "strip-purpose", text: purpose[name] || "" }));
      body.appendChild(h("ol", { class: "strip-steps" },
        step(0, "Whole application tested", e.project.value, e.project.gate, null, "needs 90%"),
        step(1, "This change tested", ml.no_modified_lines ? "no code lines" : ml.value, ml.gate, null, "share of changed lines · needs 80%"),
        step(2, "New code-quality warnings", String(e.pmd.new), e.pmd.gate, null, "allowed: 0" + (already != null ? " · " + already + " already on main" : "")),
        step(3, "Decision", "", e.decision,
          gates.length ? "Blocked: " + gates.map(function (g) { return GATE_REASON[g] || g; }).join(", and ") + "."
            : "Passed every check.")));
      caption.innerHTML = "";
      caption.appendChild(h("strong", { text: "Recorded: build #" + e.build + ". " }));
      caption.appendChild(document.createTextNode("Branch " + e.job.replace(/^petclinic-pr\//, "") +
        (e.reference_build ? ", compared against main build #" + e.reference_build : "") +
        ". Exported from Jenkins to "));
      caption.appendChild(repoLink(e.source));
      caption.appendChild(document.createTextNode("."));
      if (body.classList.contains("play")) replay(body, "play");
    }

    picks.forEach(function (p) {
      var b = h("button", { class: "chip", type: "button", "data-name": p[0],
        "aria-pressed": "false", text: p[1] });
      b.addEventListener("click", function () { draw(p[0]); });
      chips.appendChild(b);
    });
    draw(picks[0][0]);
    onVisible(body, function () { body.classList.add("play"); });
  }

  function renderPR(pr, trainKit, exportMeta) {
    var list = document.getElementById("pr-scenarios");
    var detail = document.getElementById("pr-detail");
    function show(entry) {
      var kind = scenarioKind(entry.scenario);
      list.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-name") === entry.scenario ? "true" : "false");
      });
      detail.innerHTML = "";
      detail.appendChild(h("h4", null,
        scenarioLabel(entry.scenario) + " · " + entry.job + " #" + entry.build + " ",
        badge(entry.result)));
      var expected = EXPECTED[kind];
      var expectedFailure = kind === "small" || kind === "pmd";
      detail.appendChild(h("p", { class: "note-line" },
        "Expected: " + expected + ". " +
        (expectedFailure
          ? "Jenkins shows this build as failed. That is the intended result: the check blocked the change for the right reason."
          : "")));
      detail.appendChild(h("dl", { class: "detail-grid" },
        h("div", null, h("dt", { text: "Decision" }), h("dd", null, badge(entry.decision))),
        h("div", null, h("dt", { text: "Commit" }), h("dd", { text: short(entry.revision) })),
        h("div", null, h("dt", { text: "Library version" }), h("dd", { text: entry.library })),
        h("div", null, h("dt", { text: "Compared against" }), h("dd", { text: entry.reference_build ? "main build #" + entry.reference_build : "nothing (this is the reference)" })),
        h("div", null, h("dt", { text: "Failed checks" }), h("dd", { text: entry.failing_gates.length ? entry.failing_gates.map(function (g) { return GATE_REASON[g] || g; }).join("; ") : "none" }))
      ));
      var project = entry.project || {};
      var modified = entry.modified_lines || {};
      function coverageRow(label, state, value, threshold) {
        var pct = value && /%$/.test(value) ? parseFloat(value) : null;
        var bar = h("div", { class: "bar " + (state === "SUCCESS" ? "pass" : state === "FAILURE" ? "fail" : "") });
        if (pct != null) bar.appendChild(h("span", { style: "width:" + Math.max(2, Math.min(100, pct)) + "%" }));
        return h("div", { class: "coverage-row" },
          h("div", { class: "label" },
            h("span", { text: label + (threshold ? " · needs " + threshold + "%" : "") }),
            h("span", null, badge(state), " ", value || "no value")),
          bar);
      }
      detail.appendChild(coverageRow("Whole application tested", project.gate, project.value, 90));
      detail.appendChild(coverageRow("This change tested", modified.gate,
        modified.no_modified_lines ? "no code lines changed" : modified.value, 80));
      detail.appendChild(h("p", { class: "note-line" },
        "Code-quality warnings (PMD): " + (entry.pmd.total == null ? "not read" : entry.pmd.new + " new, " + entry.pmd.total + " in total") +
        " (" + entry.pmd.gate + ")."));
      if (kind === "main") {
        detail.appendChild(h("p", { class: "note-line", text: "On the main code the checks record values but do not block; this build is what the test changes are compared against." }));
      } else if (kind === "docs") {
        detail.appendChild(h("p", { class: "note-line", text: "No code lines changed, so there is no percentage to measure. The check records that and passes, rather than inventing a number." }));
      }
      detail.appendChild(sourceLine(entry.source));
    }
    pr.forEach(function (entry) {
      var kind = scenarioKind(entry.scenario);
      var b = h("button", { class: "scenario-button", type: "button", "aria-pressed": "false",
        "data-name": entry.scenario },
        scenarioLabel(entry.scenario),
        h("span", null, (entry.decision === "BLOCK" ? "Blocked" : "Passed") + " · build #" + entry.build));
      b.addEventListener("click", function () { show(entry); });
      list.appendChild(b);
    });
    var preferred = pr.filter(function (e) { return e.scenario === "small-untested-change-1"; })[0] || pr[0];
    show(preferred);

    var tt = trainKit.filter(function (r) { return r.stage === "M5"; });
    var wrap = h("div", { class: "table-wrap" });
    var tbl = h("table");
    tbl.appendChild(h("thead", null, h("tr", null,
      h("th", { text: "Test" }), h("th", { text: "Build" }), h("th", { text: "Result" }),
      h("th", { text: "Whole project tested" }), h("th", { text: "Warnings" }), h("th", { text: "Decision" }))));
    var body = h("tbody");
    tt.forEach(function (row) {
      body.appendChild(h("tr", null,
        h("td", { text: row.scenario }), h("td", { text: "#" + row.build }),
        h("td", null, badge(row.result)),
        h("td", { text: row.coverage_state + " " + row.coverage_value }),
        h("td", { text: row.static_state + " " + row.static_value }),
        h("td", null, badge(row.decision))));
    });
    tbl.appendChild(body);
    wrap.appendChild(tbl);
    document.getElementById("tt-gates").appendChild(wrap);
  }

  function renderReviews(reviews) {
    var root = document.getElementById("reviews");
    reviews.forEach(function (r, index) {
      var copy = REVIEW_COPY[r.id] || [r.id.replace(/-/g, " "), r.finding, "", r.correction];
      var card = h("article", { class: "review" },
        h("span", { class: "review-number", text: String(index + 1).padStart(2, "0") }),
        h("h3", { text: copy[0] }));
      [["Was", copy[1]], ["Mattered", copy[2]], ["Changed", copy[3]]].forEach(function (row) {
        if (!row[1]) return;
        card.appendChild(h("p", { class: "review-row" },
          h("span", { class: "label", text: row[0] }), row[1]));
      });
      card.appendChild(h("details", { class: "extra" },
        h("summary", { text: "Show the original record" }),
        h("p", { class: "label", text: "Finding, as recorded" }),
        h("p", { text: r.finding }),
        h("p", { class: "label", text: "Correction, as recorded" }),
        h("p", { text: r.correction }),
        h("p", { class: "label", text: "Evidence" }),
        h("p", { class: "evidence" }, r.regression_evidence.reduce(function (acc, ref, i) {
          if (i) acc.push(h("br"));
          acc.push(repoLink(ref));
          return acc;
        }, []))));
      root.appendChild(card);
    });
  }

  function renderImplementation(repro) {
    var root = document.getElementById("releases");
    var wrap = h("div", { class: "table-wrap" });
    var tbl = h("table");
    tbl.appendChild(h("thead", null, h("tr", null,
      h("th", { text: "Version tag" }), h("th", { text: "Commit" }),
      h("th", { text: "Code fingerprint" }), h("th", { text: "Fixed" }))));
    var body = h("tbody");
    repro.library_releases.forEach(function (release) {
      body.appendChild(h("tr", null,
        h("td", null, h("code", { text: release.tag })),
        h("td", { text: short(release.commit) }),
        h("td", { text: short(release.vars_tree) }),
        h("td", { text: release.immutable ? "yes" : "no" })));
    });
    tbl.appendChild(body);
    wrap.appendChild(tbl);
    root.appendChild(wrap);
    root.appendChild(h("p", { class: "small", text: "Setup checks these tags exist and never creates, moves or deletes them, so a version always means the same code." }));
  }

  function renderMethod(data) {
    var repro = data.reproducibility;
    var conditions = data.full_reactor.conditions;
    var list = document.getElementById("conditions-list");
    [
      ["Train-Ticket commit", short(conditions.pinned_commit)],
      ["Parts in the project", conditions.reactor_entries],
      ["Tests", conditions.tests],
      ["Tests failing in my baseline builds", conditions.failed_or_errored],
      ["Parallel build threads", conditions.threads],
      ["Download cache", conditions.cache],
      ["One-service change", data.selective_builds.service_change.reactor_entries + " parts, " +
        data.selective_builds.service_change.tests + " tests"]
    ].forEach(function (item) {
      list.appendChild(h("dt", { text: item[0] }));
      list.appendChild(h("dd", { text: String(item[1]) }));
    });

    var caveat = document.getElementById("benchmark-caveat");
    if (caveat) {
      caveat.textContent = data.full_reactor.control_comparison.correction + " " +
        data.full_reactor.conditions.workload_note;
    }

    var verification = document.getElementById("verification-list");
    repro.verification.forEach(function (v) {
      verification.appendChild(h("p", { class: "note-line" },
        v.name + ": " + v.passed + " passed, " + v.failed + " failed (" + v.checks + " checks)"));
    });
    var env = repro.environment;
    verification.appendChild(h("p", { class: "small" },
      "Jenkins " + env.jenkins_version + " · controller " + env.controller_image +
      " · agent " + env.agent_image + " · loopback port " + env.host_port +
      " · fresh clone " + repro.fresh_clone.timestamp));

    var limits = document.getElementById("limitations");
    var seen = {};
    [repro.limitations, data.full_reactor.limitations, data.selective_builds.limitations]
      .forEach(function (group) {
        group.forEach(function (item) {
          if (seen[item.text] || SUPERSEDED_LIMITS.indexOf(item.text) !== -1) return;
          seen[item.text] = true;
          var li = h("li", null, item.text + " ",
            h("span", { class: "small" }, "(", repoLink(item.source), ")"));
          var correction = CORRECTED_LIMITS[item.text];
          if (correction) {
            li.appendChild(h("p", { class: "limit-correction" }, repoNodes(correction)));
          }
          limits.appendChild(li);
        });
      });

    var prov = document.getElementById("provenance");
    prov.appendChild(h("p", { class: "small", text: "Generator inputs: " + data.provenance.sources.length + " evidence JSON files." }));
    var wrap = h("div", { class: "table-wrap" });
    var tbl = h("table");
    tbl.appendChild(h("thead", null, h("tr", null, h("th", { text: "Evidence JSON" }))));
    var body = h("tbody");
    data.provenance.sources.forEach(function (path) {
      body.appendChild(h("tr", null, h("td", null, h("code", null, repoLink(path)))));
    });
    tbl.appendChild(body);
    wrap.appendChild(tbl);
    prov.appendChild(wrap);
  }

  function renderFigures(images) {
    var containers = {
      "figure-pr-branches": "multibranch-branches",
      "figure-selector": "selector-decision",
      "figure-pr-overview": "coverage-overview",
      "figure-pr-coverage": "coverage-modified-lines",
      "figure-pr-pmd": "pmd-new-issue"
    };
    var byId = {};
    images.forEach(function (image) { byId[image.id] = image; });

    Object.keys(containers).forEach(function (containerId) {
      var figure = document.getElementById(containerId);
      if (!figure) return;
      var image = byId[containers[containerId]];
      figure.innerHTML = "";
      if (!image) {
        figure.appendChild(h("div", { class: "fallback", text: "Screenshot metadata is not available in this data build." }));
        figure.classList.add("asset-missing");
        return;
      }
      var link = h("a", { class: "full", href: image.widths["1600"], text: "Open full resolution" });
      var img = h("img", {
        src: image.widths["800"],
        srcset: image.widths["800"] + " 800w, " + image.widths["1600"] + " 1600w",
        sizes: "(max-width: 700px) 100vw, (max-width: 1100px) 50vw, 520px",
        loading: "lazy",
        decoding: "async",
        alt: image.alt,
        width: image.width || 800,
        height: image.height || 450
      });
      img.addEventListener("error", function () { figure.classList.add("asset-missing"); });
      figure.appendChild(img);
      figure.appendChild(link);
      figure.appendChild(h("div", { class: "fallback", text: "Screenshot unavailable. The recorded values are in the build records on this page." }));
      var caption = h("figcaption");
      caption.appendChild(h("strong", { text: "Recorded: build #" + image.build + ". " }));
      caption.appendChild(document.createTextNode(FIGURE_COPY[image.id] || image.caption));
      figure.appendChild(caption);
    });
  }

  function showError(error) {
    var main = document.getElementById("main");
    if (!main) return;
    main.insertBefore(h("p", { class: "callout error", text: "The evidence data could not be loaded: " + error.message }), main.firstChild);
  }

  function init() {
    fetch("data.json", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        bindNumbers(data);
        renderStrip(data.quality_gates.petclinic.pr);
        renderGateHighlights(data);
        renderProblems(data.problems);
        renderBenchmark(data.full_reactor);
        renderSelective(data.selective_builds);
        renderPR(data.quality_gates.petclinic.pr, data.quality_gates.train_ticket,
          data.quality_gates.petclinic.pr_export);
        renderReviews(data.reviews);
        renderImplementation(data.reproducibility);
        renderMethod(data);
        renderFigures((data.images && data.images.entries) || []);
      })
      .catch(showError);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
