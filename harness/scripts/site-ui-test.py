#!/usr/bin/env python3
"""Browser checks for the static site using Chrome DevTools Protocol.

Serves site/ over HTTP, exercises the decision strip, chart, selector and gate
controls, verifies motion order and reduced-motion equivalence, checks the
assets-removed fallback and a GitHub Pages style subpath, captures the
375/768/1280 px viewport evidence and records Chrome navigation metrics.
Set PRK_SITE_VIEWPORT_DIR to write the evidence to a new directory.
Lighthouse runs are recorded separately in the validation evidence folder.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITE = os.path.join(ROOT, "site")
_evidence = os.environ.get("PRK_SITE_VIEWPORT_DIR")
EVIDENCE = (os.path.join(ROOT, _evidence) if _evidence and not os.path.isabs(_evidence)
            else _evidence or os.path.join(ROOT, "evidence", "site", "viewports"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome  # noqa: E402

CHECKS = 0


def check(condition, label):
    global CHECKS
    if not condition:
        raise AssertionError(label)
    CHECKS += 1
    print("PASS " + label)


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(directory):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=directory))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]


def exceptions(chrome):
    return [e for e in chrome.events if e.get("method") == "Runtime.exceptionThrown"]


def wait_ready(c, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if c.evaluate("document.querySelectorAll('#pr-scenarios button').length") == 7:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise AssertionError("page did not finish rendering")


def count_word(n):
    words = ["Zero", "One", "Two", "Three", "Four", "Five",
             "Six", "Seven", "Eight", "Nine", "Ten"]
    return words[n] if 0 <= n < len(words) else str(n)


def load_figures(c):
    c.evaluate("""(async () => {
        const images = [...document.querySelectorAll('.figure img')];
        for (const img of images) {
            const top = img.getBoundingClientRect().top + window.scrollY - 200;
            window.scrollTo({top: Math.max(0, top), behavior: 'instant'});
            await new Promise(resolve => setTimeout(resolve, 250));
        }
        await Promise.all(images.map(img => {
            if (img.complete) return Promise.resolve();
            return new Promise(resolve => {
                img.addEventListener('load', resolve, {once: true});
                img.addEventListener('error', resolve, {once: true});
                if (img.complete) resolve();
                setTimeout(resolve, 3000);
            });
        }));
        const deadline = performance.now() + 5000;
        while (performance.now() < deadline &&
               !images.every(img => img.complete && img.naturalWidth > 0)) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        window.scrollTo(0, 0);
    })()""", await_promise=True)


def scroll_to(c, selector):
    c.evaluate(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block: 'center'}})")


def strip_state(c, name, data):
    by_name = {e["scenario"]: e for e in data["quality_gates"]["petclinic"]["pr"]}
    entry = by_name[name]
    selector = json.dumps('#pr-strip .chip[data-name="' + name + '"]')
    c.evaluate(f"document.querySelector({selector}).click()")
    state = json.loads(c.evaluate("""JSON.stringify((() => {
        const body = document.querySelector('.strip-body');
        return {
          purpose: (body.querySelector('.strip-purpose') || {}).textContent || '',
          steps: [...body.querySelectorAll('.strip-step')].map(step => ({
            label: [...step.querySelector('.strip-label').childNodes]
              .filter(node => node.nodeType === 3)
              .map(node => node.textContent).join('').trim(),
            value: step.querySelector('.strip-value').textContent,
            badge: step.querySelector('.status-badge').textContent,
            reason: (step.querySelector('.strip-reason') || {}).textContent || ''
          })),
          pressed: [...document.querySelectorAll('#pr-strip .chip')]
            .filter(chip => chip.getAttribute('aria-pressed') === 'true')
            .map(chip => chip.getAttribute('data-name')),
          caption: document.querySelector('#pr-strip figcaption').textContent
        };
    })())"""))
    return entry, state


def main():
    os.makedirs(EVIDENCE, exist_ok=True)
    httpd, port = serve(SITE)
    chrome = None
    reduced_chrome = None
    temp = None
    subpath_temp = None
    try:
        chrome = Chrome(port=9250, width=1280, height=900, scale=1)
        chrome.call("Log.enable")
        base = f"http://127.0.0.1:{port}/index.html"
        chrome.navigate(base, settle=1.5)
        wait_ready(chrome)
        with open(os.path.join(SITE, "data.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        runs = data["full_reactor"]["runs"]
        pr = data["quality_gates"]["petclinic"]["pr"]
        pr_count = len(pr)
        selected = data["selective_builds"]["service_change"]["reactor_entries"]
        full = data["selective_builds"]["full_reactor"]["reactor_entries"]
        reviews = data["reviews"]
        cases = data["selective_builds"]["selector_cases"]
        with open(os.path.join(ROOT, "examples", "Jenkinsfile.multibranch"),
                  encoding="utf-8", newline="") as fh:
            jenkinsfile_text = fh.read().replace("\r\n", "\n").replace("\r", "\n")
        manifest = json.load(open(os.path.join(ROOT, "release", "manifest.json"),
                                  encoding="utf-8"))
        manifest_paths = {entry["path"] for entry in manifest["files"]}
        evidence_base = ("https://github.com/sreekanth-chaliyeduth/"
                         "pipeline-rescue-kit/blob/v1.0.0/")

        links = json.loads(chrome.evaluate(
            "JSON.stringify([...document.querySelectorAll('#main a[href]')]"
            ".map(a => a.getAttribute('href')))"))
        repo_links = [href for href in links if href.startswith(evidence_base)]
        repo_paths = [href[len(evidence_base):] for href in repo_links]
        check(len(repo_links) >= 20,
              "the page renders repository evidence links")
        check(all(path in manifest_paths for path in repo_paths),
              "every repository evidence path is in release/manifest.json")
        check(all(os.path.isfile(os.path.join(ROOT, path)) for path in repo_paths),
              "every repository evidence path exists in the export")
        check(all(".." not in path for path in repo_paths),
              "repository evidence links contain no path traversal")
        check(not any(href.startswith("../") for href in links),
              "no obsolete local evidence base remains")
        tagged_missing = [path for path in repo_paths
                          if subprocess.run(
                              ["git", "-C", ROOT, "cat-file", "-e",
                               "v1.0.0:" + path],
                              capture_output=True).returncode != 0]
        check(not tagged_missing,
              "every repository evidence path exists in the v1.0.0 tag: "
              + ", ".join(tagged_missing[:8]))
        check(not any("pipeline-rescue-kit-private" in href
                      or "/Users/" in href for href in links),
              "no evidence link points at a private repository or filesystem")
        full_links = json.loads(chrome.evaluate(
            "JSON.stringify([...document.querySelectorAll('a.full')]"
            ".map(a => a.getAttribute('href')))"))
        check(len(full_links) == 5,
              "all five full-resolution screenshot links remain")
        check(all(re.fullmatch(r"assets/[a-z0-9-]+-1600\.webp", href)
                  for href in full_links),
              "full-resolution links still point at the 1600 px assets")
        check(chrome.evaluate("""(() => {
            const nodes = [...document.querySelectorAll(
              '#main .evidence, #main .limit-correction, #main #provenance')];
            return nodes.filter(el => el.textContent.includes('evidence/')
              && !el.querySelector('a[href*="evidence/"]')).length;
        })()""") == 0,
              "every rendered evidence reference is an anchor")

        author_links = json.loads(chrome.evaluate("""JSON.stringify(
            [...document.querySelectorAll('a.author-link')].map(a => ({
              href: a.getAttribute('href'),
              rel: a.getAttribute('rel'),
              label: a.getAttribute('aria-label'),
              text: a.textContent,
              tabIndex: a.tabIndex
            })))"""))
        check(len(author_links) == 2,
              "the masthead and footer author links are present")
        check(all(link["href"] == "https://www.linkedin.com/in/sreekanth-chaliyeduth/"
                  for link in author_links),
              "both author links use the exact LinkedIn URL")
        check(all(link["rel"] == "noopener" for link in author_links),
              "both author links use rel=noopener")
        check(all(link["label"] == "Sreekanth C on LinkedIn"
                  for link in author_links),
              "both author links expose the required accessible name")
        check(all(link["text"] == "Sreekanth C" for link in author_links),
              "both author links display only the author name")
        check(all(link["tabIndex"] == 0 for link in author_links),
              "both author links are keyboard focusable")
        chrome.evaluate("document.querySelector('a.author-link').focus()")
        check(chrome.evaluate(
            "document.activeElement.classList.contains('author-link')"),
            "the masthead author link receives keyboard focus")

        check(chrome.evaluate("document.title").startswith("Pipeline Rescue Kit"),
              "root page loads with the expected title")
        check(chrome.evaluate("document.querySelectorAll('main section').length") == 8,
              "all eight sections render")
        check(chrome.evaluate("document.querySelectorAll('h1').length") == 1,
              "exactly one h1")
        check(chrome.evaluate("document.getElementById('benchmark-title').textContent") ==
              "Build timings, and the claim I withdrew",
              "benchmark heading is the static editorial heading")
        check(chrome.evaluate("document.getElementById('selective-title').textContent") ==
              "Rebuilding only what a change touches",
              "selection heading is the static editorial heading")
        check(chrome.evaluate("document.getElementById('review-title').textContent") ==
              "Mistakes I found and fixed",
              "corrections heading is the static editorial heading")
        check(chrome.evaluate("document.getElementById('gates-title').textContent") ==
              "How the merge check decides",
              "gate heading is the static editorial heading")
        gate_cards = chrome.evaluate("document.querySelectorAll('#gate-highlights .gate-card').length")
        check(gate_cards == 2, "the gate comparison still renders two recorded blocks")
        summary = chrome.evaluate("document.getElementById('summary').innerText") or ""
        check("The problem" in summary, "opening summary contains The problem")
        check("What I built" in summary, "opening summary contains What I built")
        check("How I tested it" in summary, "opening summary contains How I tested it")
        check("What I found" in summary, "opening summary contains What I found")
        check(chrome.evaluate("document.querySelector('[data-n=\"sel\"]').textContent") == str(selected)
              and chrome.evaluate("document.querySelector('[data-n=\"full\"]').textContent") == str(full),
              "summary number hooks resolve to the recorded 3 and 43")
        check(chrome.evaluate("""[
              'dek-summary', 'train-ticket-meta', 'train-ticket-scope', 'hero-stats'
            ].every(id => document.getElementById(id) === null)"""),
              "the removed intro, meta, scope and hero-stat elements are absent")
        check(chrome.evaluate("document.querySelectorAll('main section h2').length") == 8,
              "every section has an h2")
        check(chrome.evaluate("document.querySelectorAll('#problems article, #problems-more article').length") == 7,
              "seven pipeline problems render across the disclosure")
        check(chrome.evaluate("document.querySelectorAll('#problems > article').length") == 4,
              "four problem findings are visible")
        check(chrome.evaluate("document.querySelectorAll('#problems-more article').length") == 3,
              "three further problem findings sit behind the disclosure")
        check(chrome.evaluate("document.querySelectorAll('.run-dot').length") == 9,
              "the benchmark chart shows nine runs")
        check(chrome.evaluate("document.querySelectorAll('#benchmark-table tbody tr').length") == 9,
              "the benchmark table lists nine runs")
        check(chrome.evaluate("document.querySelectorAll('#benchmark-runs button').length") == 9,
              "the run selector lists nine runs")
        main_text = chrome.evaluate("document.getElementById('main').innerText.toLowerCase()") or ""
        check(all(token not in main_text for token in
                  ("m3", "m4", "m5", "reactor entr", "fails closed")),
              "visible main copy contains no legacy milestone or jargon labels")
        check("—" not in (chrome.evaluate("document.body.innerText") or ""),
              "the rendered page contains no em dash")
        gate_text = chrome.evaluate("document.getElementById('gate-highlights').textContent") or ""
        check(all(value in gate_text for value in
                  ("92.33%", "0.00%", "94.08%", "100.00%", "1 new code-quality warning")),
              "the gate comparison shows both independent blocks")
        benchmark_text = chrome.evaluate("document.getElementById('benchmark').innerText") or ""
        check(all(token in benchmark_text for token in
                  ("220", "626", "221", "in my baseline builds")),
              "section 5 distinguishes baseline 220 from upstream 221")
        check("already fail at the pinned commit" not in benchmark_text,
              "section 5 no longer calls 220 the independent upstream count")
        benchmark_lead = chrome.evaluate("document.querySelector('#benchmark > p.lead').textContent") or ""
        check("same packaging work" not in benchmark_lead
              and "package every part, as the original does" in benchmark_lead,
              "section 5 describes the control as packaging every part")
        conditions_text = chrome.evaluate("document.getElementById('conditions-list').textContent") or ""
        check("Tests failing in my baseline builds" in conditions_text,
              "the conditions list labels the baseline failure count accurately")
        shared_card = chrome.evaluate("""(() => {
            const card = [...document.querySelectorAll('#projects .app-card')]
              .find(item => item.querySelector('h3').textContent === 'The shared check');
            return card ? card.innerText : '';
        })()""") or ""
        check("same fixed version" not in shared_card
              and "Both projects call the same library; each sets its own limits." in shared_card,
              "the shared-check card does not claim one verified fixed version")
        callout_text = re.sub(r"\s+", " ",
                              chrome.evaluate("document.querySelector('#projects .callout').innerText") or "")
        check("No figure is typed in by hand" not in callout_text
              and "Every measured figure is generated from those files" in callout_text,
              "section 1 distinguishes measured values from configured limits")
        limitation_text = chrome.evaluate("document.getElementById('limitations').textContent") or ""
        original_limitation = "The ts-common scenario selects 42 dependent module entries; the aggregator root is not in that reactor."
        check(original_limitation in limitation_text
              and "evidence/M4/results.json" in limitation_text,
              "the contradicted limitation remains with its recorded source")
        limitation_correction = chrome.evaluate("""(() => {
            const item = [...document.querySelectorAll('#limitations li')]
              .find(node => node.textContent.includes('aggregator root is not in that reactor'));
            const correction = item && item.querySelector('.limit-correction');
            return correction ? correction.textContent : '';
        })()""") or ""
        check("ts-service-cluster" in limitation_correction,
              "the contradicted limitation carries a visible correction")
        check("No M4 incremental scope reduction is included." not in limitation_text
              and "M5, quality gates and the shared library are not started." not in limitation_text,
              "the two superseded limitations remain hidden")
        rendered_jenkins = chrome.evaluate("""(() => {
            const disclosure = [...document.querySelectorAll('#implementation details.extra')]
              .find(item => item.querySelector('summary').textContent
                .includes('Show the build file used for the test changes'));
            const code = disclosure && disclosure.querySelector('pre.code code');
            return code ? code.textContent : '';
        })()""") or ""
        rendered_jenkins = rendered_jenkins.replace("\r\n", "\n").replace("\r", "\n")
        check(rendered_jenkins == jenkinsfile_text,
              "the build-file disclosure matches examples/Jenkinsfile.multibranch exactly")
        build_summary_text = chrome.evaluate("""(() => {
            const disclosure = [...document.querySelectorAll('#implementation details.extra')]
              .find(item => item.querySelector('summary').textContent
                .includes('Show the build file used for the test changes'));
            return disclosure ? disclosure.querySelector('summary').textContent : '';
        })()""") or ""
        check("Show the build file used for the test changes" in build_summary_text
              and "examples/Jenkinsfile.multibranch" in build_summary_text,
              "the build-file disclosure uses the approved summary")

        # One data load, no external requests, no prototype code.
        request_urls = [e["params"]["request"]["url"] for e in chrome.events
                        if e.get("method") == "Network.requestWillBeSent"]
        check(sum(url.endswith("/data.json") for url in request_urls) == 1,
              "data.json is loaded exactly once")
        check(all(url.startswith(f"http://127.0.0.1:{port}/") for url in request_urls),
              "the page makes no external network requests")
        source_text = "".join(open(os.path.join(SITE, name), encoding="utf-8").read().lower()
                              for name in ("index.html", "styles.css", "app.js"))
        check("isometric" not in source_text and "experience/" not in source_text
              and "assets/brands" not in source_text,
              "the site contains no isometric prototype code or brand assets")

        # Decision strip: structure and recorded values.
        check(chrome.evaluate("document.querySelectorAll('#pr-strip .chip').length") == 3,
              "the decision strip renders three recorded PR chips")
        check(chrome.evaluate("document.querySelectorAll('#pr-strip .strip-step').length") == 4,
              "the decision strip renders three gate steps and one decision step")
        check(chrome.evaluate("document.querySelector('.strip-head') === null"),
              "the removed strip head is absent")
        labels = ["Whole application tested", "This change tested",
                  "New code-quality warnings", "Decision"]
        picks = [("small-untested-change-1", "Untested change",
                  "Blocked: the changed lines are not tested enough."),
                 ("pmd-violation-1", "Code-quality warning",
                  "Blocked: the change adds a code-quality warning."),
                 ("fixed", "Fixed change", "Passed every check.")]
        for name, label, reason in picks:
            entry, state = strip_state(chrome, name, data)
            chip_selector = json.dumps('#pr-strip .chip[data-name="' + name + '"]')
            check(label in chrome.evaluate(
                f"document.querySelector({chip_selector}).textContent"),
                f"the {label} chip is present")
            check(state["pressed"] == [name],
                  f"only the {label} chip is pressed")
            check(entry["job"].replace("petclinic-pr/", "") in state["caption"]
                  and f"Recorded: build #{entry['build']}." in state["caption"]
                  and entry["source"] in state["caption"],
                  f"the {label} strip caption names the recorded build, branch and evidence")
            check([step["label"] for step in state["steps"]] == labels,
                  f"the {label} strip uses the four recorded steps")
            expected_values = [entry["project"]["value"],
                               "no code lines" if entry["modified_lines"].get("no_modified_lines")
                               else entry["modified_lines"]["value"],
                               str(entry["pmd"]["new"]), ""]
            check([step["value"] for step in state["steps"]] == expected_values,
                  f"the {label} strip values match data.json")
            expected_badges = [
                "PASS" if entry["project"]["gate"] == "SUCCESS" else "FAIL",
                "PASS" if entry["modified_lines"]["gate"] == "SUCCESS" else "FAIL",
                "PASS" if entry["pmd"]["gate"] == "SUCCESS" else "FAIL",
                entry["decision"]]
            check([step["badge"] for step in state["steps"]] == expected_badges,
                  f"the {label} strip badges match data.json")
            check(state["steps"][3]["reason"] == reason,
                  f"the {label} strip states the recorded reason")
            if name == "small-untested-change-1":
                check(state["steps"][3]["reason"].startswith("Blocked:"),
                      "the untested-change decision reason begins with Blocked:")
            if name == "fixed":
                check("second small class" in state["purpose"],
                      "the fixed-change strip explains the second small class")
            check(re.search(r"Recorded: build #\d+\.", state["caption"]) is not None,
                  f"the {label} strip keeps the recorded-build caption")

        # Motion order: each step starts after the previous one and all settle.
        samples = json.loads(chrome.evaluate("""(async () => {
            const chip = document.querySelector('#pr-strip .chip[data-name="pmd-violation-1"]');
            const body = document.querySelector('.strip-body');
            chip.click();
            const t0 = performance.now();
            const out = [];
            while (performance.now() - t0 < 3300) {
                out.push({t: performance.now() - t0,
                    play: body.classList.contains('play'),
                    op: [...body.querySelectorAll('.strip-step')]
                        .map(step => parseFloat(getComputedStyle(step).opacity))});
                await new Promise(resolve => setTimeout(resolve, 50));
            }
            return JSON.stringify(out);
        })()""", await_promise=True))
        onsets = []
        for index in range(4):
            onset = next((row["t"] for row in samples if row["op"][index] > 0.05), None)
            onsets.append(onset)
        check(all(value is not None for value in onsets),
              "all four decision steps become visible")
        check(onsets[0] < 300, "the first decision step starts immediately")
        check(onsets[1] - onsets[0] > 150 and onsets[2] - onsets[1] > 150
              and onsets[3] - onsets[2] > 150,
              "the decision steps start in recorded gate order")
        check(onsets[3] < 1600 and onsets[3] - onsets[0] < 1300,
              "the decision sequence completes within about 1.2 seconds")
        early = next((row for row in samples if 90 <= row["t"] <= 160), None)
        check(early is not None and early["op"][1:] == [0, 0, 0],
              "later decision steps remain hidden while the first step plays")
        late = [row for row in samples if row["t"] > 1900]
        check(len(late) >= 10 and all(all(op > 0.99 for op in row["op"]) for row in late),
              "the decision strip settles and does not loop")
        check(all(row["play"] for row in late),
              "the decision strip keeps its final played state")
        with open(os.path.join(EVIDENCE, "strip-motion.json"), "w", encoding="utf-8") as fh:
            json.dump({"scenario": "pmd-violation-1", "sample_ms": 50,
                       "onsets_ms": dict(zip(labels, [round(value, 1) for value in onsets])),
                       "settled_after_ms": 1900, "samples": samples}, fh, indent=2)
            fh.write("\n")

        # Rapid switching keeps the final selection and never leaves a blank strip.
        rapid = json.loads(chrome.evaluate("""(async () => {
            const chips = [...document.querySelectorAll('#pr-strip .chip')];
            const body = document.querySelector('.strip-body');
            for (let index = 0; index < 7; index += 1) {
                chips[index % 3].click();
                await new Promise(resolve => setTimeout(resolve, 15));
            }
            const expected = chips[6 % 3].getAttribute('data-name');
            await new Promise(resolve => setTimeout(resolve, 1500));
            const settled = {
                expected,
                pressed: [...chips].filter(chip => chip.getAttribute('aria-pressed') === 'true')
                    .map(chip => chip.getAttribute('data-name')),
                play: body.classList.contains('play'),
                op: [...body.querySelectorAll('.strip-step')]
                    .map(step => parseFloat(getComputedStyle(step).opacity)),
                text: body.innerText.replace(/\\n+/g, ' | ')
            };
            await new Promise(resolve => setTimeout(resolve, 700));
            settled.still = [...body.querySelectorAll('.strip-step')]
                .map(step => parseFloat(getComputedStyle(step).opacity));
            return JSON.stringify(settled);
        })()""", await_promise=True))
        check(rapid["pressed"] == [rapid["expected"]] and rapid["expected"] == "small-untested-change-1",
              "rapid chip switching keeps exactly the last selection")
        check(rapid["play"] and all(op > 0.99 for op in rapid["op"]),
              "rapid chip switching leaves the final strip visible")
        check(rapid["still"] == rapid["op"]
              and "Blocked: the changed lines are not tested enough." in rapid["text"],
              "rapid chip switching settles on the matching recorded decision")

        # Benchmark controls.
        chrome.evaluate("document.querySelector('[data-variant=\"control\"]').click()")
        check(chrome.evaluate("document.querySelectorAll('#benchmark-chart g[data-variant]')") is not None,
              "benchmark filter is interactive")
        visible = chrome.evaluate("""(() => {
            return [...document.querySelectorAll('#benchmark-chart g[data-variant]')]
              .filter(g => g.style.display !== 'none').length; })()""")
        check(visible == 1, "the control filter shows only the control group")

        chrome.evaluate("document.querySelector('.run-dot').dispatchEvent(new MouseEvent('click', {bubbles:true}))")
        check("build" in (chrome.evaluate("document.getElementById('benchmark-detail').innerText") or ""),
              "selecting a run fills the detail panel")
        chrome.evaluate("""(() => {
            const button = [...document.querySelectorAll('#benchmark-runs button')]
              .find(b => b.getAttribute('data-run') === 'control-2');
            button.click(); })()""")
        run_detail = chrome.evaluate("document.getElementById('benchmark-detail').innerText") or ""
        check("New + packaging 2" in run_detail and "build" in run_detail,
              "the run selector selects a specific build")
        check(chrome.evaluate("""[...document.querySelectorAll('#benchmark-runs button')]
              .filter(b => b.getAttribute('aria-pressed') === 'true').length""") == 1,
              "the run selector keeps one run selected")
        check(chrome.evaluate("document.querySelector('.run-dot').getAttribute('tabindex')") == "0",
              "chart points remain keyboard focusable")
        chrome.evaluate("document.querySelector('#benchmark-runs button').focus()")
        check(chrome.evaluate("document.activeElement.classList.contains('run-pick')"),
              "the run selector accepts keyboard focus")
        check(chrome.evaluate("""[...document.querySelectorAll('.run-pick')]
              .every(button => button.getAttribute('aria-label') === null)"""),
              "the run buttons use their visible text as the accessible name")
        check(chrome.evaluate("document.querySelectorAll('.proves h4').length") == 0,
              "the evidence section uses h3 headings, not h4")

        # Selector: chips above the reactor, five cases, two-column restored layout.
        check(chrome.evaluate("document.querySelectorAll('#selector-chips .chip').length") == 5,
              "five selector case chips render above the reactor grid")
        check(chrome.evaluate("document.querySelectorAll('#selector-cases button').length") == 5,
              "five selector cases render in the detail panel")
        check(chrome.evaluate("""(() => {
            const chips = document.getElementById('selector-chips');
            const grid = document.getElementById('reactor-illustration');
            return !!(chips.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING);
        })()"""), "the selector chips appear before the reactor grid")
        check(chrome.evaluate("document.getElementById('selector-policy').offsetParent !== null")
              and "When unsure, it builds all 43 parts"
              in (chrome.evaluate("document.getElementById('selector-policy').textContent") or ""),
              "the build-everything policy is shown inline")
        check(chrome.evaluate("document.querySelectorAll('#selective .selector-layout').length") == 1,
              "the selector detail uses the restored two-column layout container")
        chrome.evaluate("document.querySelector('#selective details.extra').open = true")
        columns = chrome.evaluate(
            "getComputedStyle(document.querySelector('.selector-layout')).gridTemplateColumns")
        check(len(columns.split()) == 2, "the selector detail is two columns at 1280px")
        check(chrome.evaluate("document.querySelectorAll('#reactor-illustration span').length") == full,
              "the reactor illustration has 43 entries")
        chip_text = chrome.evaluate("document.getElementById('selector-chips').innerText") or ""
        check(all(label in chip_text for label in
                  ("One service", "Shared library", "Top-level build file",
                   "Non-code folder", "Docs only")),
              "the selector chips use the five plain case labels")

        scroll_to(chrome, ".reactor-panel")
        deadline = time.time() + 5
        while time.time() < deadline and not chrome.evaluate(
                "document.querySelector('.reactor-panel').classList.contains('play')"):
            time.sleep(0.1)
        panel_state = chrome.evaluate("""JSON.stringify((() => {
            const panel = document.querySelector('.reactor-panel');
            const rect = panel.getBoundingClientRect();
            return {className: panel.className, top: rect.top, bottom: rect.bottom,
                    height: rect.height, viewport: innerHeight, scrollY: scrollY};
        })())""")
        check(chrome.evaluate("document.querySelector('.reactor-panel').classList.contains('play')"),
              "the reactor panel plays when it scrolls into view " + panel_state)
        chrome.evaluate("document.querySelector('#selector-chips .chip[data-name=\"ts-common\"]').click()")
        check(chrome.evaluate("document.getElementById('reactor-count').textContent") == "42"
              and chrome.evaluate("document.getElementById('reactor-of').textContent") == "of 43",
              "the shared-module case reports 42 of 43 reactor entries")
        check(chrome.evaluate("document.querySelectorAll('#reactor-illustration span.on').length") == 42,
              "the shared-module case highlights 42 reactor entries")
        module_labels = chrome.evaluate("""[...document.querySelectorAll('#selected-modules .module-pill')]
              .map(pill => pill.textContent)""") or []
        check(module_labels.count("ts-consign-price-service") == 2,
              "the shared-module case keeps the duplicated Maven display label")
        check("ts-gateway-service" not in module_labels,
              "the shared-module case excludes the non-dependent gateway")
        check(chrome.evaluate("document.querySelectorAll('#selected-modules .module-pill').length") == 42,
              "the shared-module case lists 42 reactor entries")
        duplicate_note = chrome.evaluate("""(() => {
            const note = document.querySelector('#selected-modules .small');
            return note ? note.textContent : '';
        })()""") or ""
        check(duplicate_note == "Two parts show as ts-consign-price-service because Train-Ticket's own build files give ts-consign-service the same display name. They are different parts.",
              "the shared-module case explains the duplicate Maven display name")
        chrome.evaluate("document.querySelector('#selector-chips .chip[data-name=\"ts-common\"]').click()")
        check(chrome.evaluate("document.querySelectorAll('#selected-modules .small').length") == 1,
              "repeating the shared-module selection does not accumulate duplicate notes")
        check(chrome.evaluate("document.querySelectorAll('#selector-cases button[aria-pressed=\"true\"]').length") == 1
              and chrome.evaluate("document.querySelector('#selector-cases button[aria-pressed=\"true\"]').getAttribute('data-name')") == "ts-common",
              "the selector list follows the shared-module chip")
        time.sleep(0.12)
        delays = chrome.evaluate("""[...document.querySelectorAll('#reactor-illustration span.on')]
              .slice(0, 3).map(span => getComputedStyle(span).transitionDelay)""")
        check(delays == ["0s", "0.018s", "0.036s"],
              "reactor cells use the recorded 18 ms stagger")

        chrome.evaluate("document.querySelector('#selector-chips .chip[data-name=\"root-pom\"]').click()")
        check(chrome.evaluate("document.getElementById('reactor-count').textContent") == "43"
              and chrome.evaluate("document.querySelectorAll('#reactor-illustration span.full').length") == 43,
              "the root-pom case falls back to all 43 reactor entries")
        check(chrome.evaluate("document.querySelectorAll('#selected-modules .module-pill:not(.muted)').length") == 0
              and "nothing to build"
              in (chrome.evaluate("document.getElementById('selected-modules').innerText") or ""),
              "the root-pom case hides the module pills")
        root_detail = chrome.evaluate("document.getElementById('selector-detail').textContent") or ""
        check("ALL PARTS" in root_detail
              and "full reactor" not in root_detail.split("Reason:")[0].lower(),
              "the root-pom decision uses ALL PARTS instead of full reactor")
        check("Modules:" in root_detail and "ts-gateway-service" in root_detail,
              "the root-pom detail lists all modules including the gateway")

        chrome.evaluate("document.querySelector('#selector-chips .chip[data-name=\"documentation-only\"]').click()")
        check(chrome.evaluate("document.getElementById('reactor-count').textContent") == "0"
              and chrome.evaluate("document.querySelectorAll('#reactor-illustration span.on').length") == 0,
              "the docs-only case selects no reactor entries")
        chrome.evaluate("document.querySelector('#selector-chips .chip[data-name=\"one-service\"]').click()")
        check(chrome.evaluate("document.getElementById('reactor-count').textContent") == "3",
              "the one-service case restores the three-entry selection")
        check(chrome.evaluate("document.querySelectorAll('#selected-modules .small').length") == 0,
              "the duplicate-name explanation is removed for the one-service case")

        # PR scenarios remain complete.
        check(chrome.evaluate("document.querySelectorAll('#pr-scenarios button').length") == 7,
              "seven PR scenarios render")
        chrome.evaluate("""(() => {
            const b = [...document.querySelectorAll('#pr-scenarios button')]
              .find(b => b.getAttribute('data-name') === 'pmd-violation-1');
            b.click(); })()""")
        detail = chrome.evaluate("document.getElementById('pr-detail').textContent") or ""
        check("1 new" in detail and "pmd" in detail.lower(),
              "the PMD scenario reports one new finding and a PMD block")
        chrome.evaluate("""(() => {
            const b = [...document.querySelectorAll('#pr-scenarios button')]
              .find(b => b.getAttribute('data-name') === 'docs-only');
            b.click(); })()""")
        detail = chrome.evaluate("document.getElementById('pr-detail').textContent") or ""
        check("no code lines" in detail.lower(),
              "the docs-only scenario reports no code lines to measure")
        chrome.evaluate("""(() => {
            const b = [...document.querySelectorAll('#pr-scenarios button')]
              .find(b => b.getAttribute('data-name') === 'small-untested-change-1');
            b.click(); })()""")
        detail = chrome.evaluate("document.getElementById('pr-detail').textContent") or ""
        check("this change tested" in detail.lower() and "92.33" in detail and "0.00" in detail,
              "the untested-change scenario shows both coverage values")

        # Gate bars fill before their badges, then stop. Reload so the new
        # section order cannot have already triggered the gate observer.
        chrome.navigate(base, settle=1.2)
        wait_ready(chrome)
        chrome.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        time.sleep(0.25)
        check(chrome.evaluate("!document.getElementById('gate-highlights').classList.contains('play')"),
              "the gate animation waits below the fold")
        check(chrome.evaluate("""[...document.querySelectorAll('#gate-highlights .gate-bar span')]
              .every(span => span.getBoundingClientRect().width === 0)"""),
              "gate bars start empty before scroll-in")
        check(chrome.evaluate("""[...document.querySelectorAll('#gate-highlights .gate-state, #gate-highlights .gate-verdict .status-badge')]
              .every(badge => parseFloat(getComputedStyle(badge).opacity) === 0)"""),
              "gate badges stay hidden before the bars fill")
        gate_samples = json.loads(chrome.evaluate("""(async () => {
            const root = document.getElementById('gate-highlights');
            const bar = root.querySelector('.gate-bar span');
            const track = bar.parentElement;
            const badges = [...root.querySelectorAll('.gate-state, .gate-verdict .status-badge')];
            window.scrollTo({top: Math.max(0,
                root.getBoundingClientRect().top + window.scrollY - 250), behavior: 'instant'});
            const t0 = performance.now();
            const out = [];
            while (performance.now() - t0 < 2500) {
                out.push({t: performance.now() - t0,
                    play: root.classList.contains('play'),
                    ratio: bar.getBoundingClientRect().width / track.getBoundingClientRect().width,
                    badge: Math.max(...badges.map(b => parseFloat(getComputedStyle(b).opacity)))});
                await new Promise(resolve => setTimeout(resolve, 50));
            }
            return JSON.stringify(out);
        })()""", await_promise=True))
        bar_onset = next((row["t"] for row in gate_samples if row["ratio"] > 0.05), None)
        badge_onset = next((row["t"] for row in gate_samples if row["badge"] > 0.05), None)
        check(bar_onset is not None and badge_onset is not None,
              "the gate bars and badges both become visible")
        check(badge_onset - bar_onset > 500,
              "gate badges appear after the coverage bars fill")
        check(abs(gate_samples[-1]["ratio"] - 0.9233) < 0.01,
              "the first gate bar reaches its recorded coverage value")
        check(all(row["badge"] > 0.99 for row in gate_samples if row["t"] > badge_onset + 500),
              "every gate badge settles visible")
        check(all(gate_samples[-1]["ratio"] == row["ratio"] for row in gate_samples if row["t"] > bar_onset + 1200),
              "the gate bars settle and do not loop")
        styles = chrome.evaluate("""JSON.stringify([...document.querySelectorAll('#gate-highlights .gate-bar span')]
              .map(span => span.style.width))""")
        check(json.loads(styles) == ["92.33%", "0%", "94.08%", "100%"],
              "the gate bars use the four recorded coverage values")
        check(chrome.evaluate("""[...document.querySelectorAll('#gate-highlights .gate-state, #gate-highlights .gate-verdict .status-badge')]
              .every(badge => parseFloat(getComputedStyle(badge).opacity) > 0.99)"""),
              "the gate badges show their final states")
        with open(os.path.join(EVIDENCE, "gate-motion.json"), "w", encoding="utf-8") as fh:
            json.dump({"sample_ms": 50,
                       "bar_onset_ms": round(bar_onset, 1),
                       "badge_onset_ms": round(badge_onset, 1),
                       "badge_delay_after_bar_ms": round(badge_onset - bar_onset, 1),
                       "bar_styles": json.loads(styles), "samples": gate_samples}, fh, indent=2)
            fh.write("\n")

        # Screenshot placement and figure integrity. The selector figure lives
        # inside the selector disclosure, so reopen it after the gate reload.
        chrome.evaluate("document.querySelector('#selective details.extra').open = true")
        figure_ids = chrome.evaluate("JSON.stringify([...document.querySelectorAll('.figure')].map(f => f.id))")
        check(json.loads(figure_ids) == ["figure-pr-branches", "figure-pr-overview",
                                         "figure-pr-coverage", "figure-pr-pmd", "figure-selector"],
              "the five recorded screenshots keep their intended order")
        check(chrome.evaluate("document.querySelector('#gates #figure-pr-branches') !== null"),
              "the multibranch screenshot is placed in the gate section")
        check(chrome.evaluate("document.querySelectorAll('#gates .figure-grid-4 .figure').length") == 4,
              "the gate section uses the four-figure 2x2 grid")
        check(chrome.evaluate("document.getElementById('figure-hero') === null"),
              "the removed hero screenshot is gone")
        check(chrome.evaluate("document.getElementById('pieces') === null")
              and "How the pieces connect" not in (chrome.evaluate("document.body.innerText") or ""),
              "the removed connection panel is absent")
        check(chrome.evaluate("document.querySelectorAll('#selective details.fail-closed').length") == 0
              and "Fail-closed policy" not in (chrome.evaluate("document.body.innerText") or ""),
              "the removed collapsed fail-closed panel is absent")
        check(chrome.evaluate("document.querySelectorAll('.figure img').length") == 5,
              "five recorded screenshots render")
        check(chrome.evaluate("""[...document.querySelectorAll('.figure img')]
              .every(img => img.getAttribute('srcset') && img.loading === 'lazy')"""),
              "every screenshot provides srcset and lazy loading")
        load_figures(chrome)
        check(chrome.evaluate("""[...document.querySelectorAll('.figure img')]
              .every(img => img.complete && img.naturalWidth > 0)"""),
              "every screenshot image loads")
        check(chrome.evaluate("""[...document.querySelectorAll('.figure a.full')]
              .every(a => /-1600\\.webp$/.test(a.getAttribute('href')))"""),
              "every full-resolution link points to the 1600px asset")
        check(chrome.evaluate("""[...document.querySelectorAll('.figure figcaption')]
              .every(c => /Recorded: build #\\d+\\./.test(c.textContent))"""),
              "every screenshot caption names the recorded build")
        branches_caption = chrome.evaluate(
            "document.querySelector('#figure-pr-branches figcaption').textContent") or ""
        check(all(token in branches_caption for token in ("#12", "#14", "#11", "#13")),
              "the multibranch caption explains the recorded and interactive builds")
        check(chrome.evaluate("""[...document.querySelectorAll('.figure img')]
              .every(img => img.getAttribute('alt') && img.getAttribute('width') && img.getAttribute('height'))"""),
              "every screenshot carries alt text and intrinsic dimensions")
        asset_status = json.loads(chrome.evaluate("""(async () => {
            const urls = new Set();
            for (const img of document.querySelectorAll('.figure img')) {
                urls.add(img.getAttribute('src'));
                urls.add(img.getAttribute('srcset').split(',')[0].trim().split(' ')[0]);
                urls.add(img.getAttribute('srcset').split(',')[1].trim().split(' ')[0]);
            }
            const out = [];
            for (const url of urls) {
                const response = await fetch(url);
                out.push([url, response.status]);
            }
            return JSON.stringify(out);
        })()""", await_promise=True))
        check(all(status == 200 for _, status in asset_status),
              "every screenshot asset link returns HTTP 200")
        check(len(asset_status) == 10, "both 800px and 1600px assets are reachable")
        check(len(exceptions(chrome)) == 0, "no uncaught JavaScript exceptions on the root page")
        check(chrome.evaluate("document.querySelectorAll('.callout.error').length") == 0,
              "no data loading error is shown")

        # Responsive checks and viewport evidence.
        views = [(375, 812), (768, 1024), (1280, 900)]
        for width, height in views:
            chrome.set_viewport(width, height, 1, mobile=width < 500)
            chrome.navigate(base, settle=1.2)
            wait_ready(chrome)
            load_figures(chrome)
            check(chrome.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"),
                  f"no horizontal page overflow at {width}px")
            check(chrome.evaluate("window.innerWidth") == width,
                  f"viewport is {width}px")
            check(chrome.evaluate("document.querySelectorAll('#pr-strip .chip').length") == 3
                  and chrome.evaluate("document.querySelectorAll('#pr-strip .strip-step').length") == 4,
                  f"the decision strip stays complete at {width}px")
            check(chrome.evaluate("""(() => {
                const strip = document.getElementById('pr-strip');
                return strip.scrollWidth <= strip.clientWidth + 1;
            })()"""), f"the decision strip has no horizontal clipping at {width}px")
            if width == 375:
                stat_size = chrome.evaluate(
                    "parseFloat(getComputedStyle(document.querySelector('#summary p')).fontSize)")
                check(stat_size >= 13,
                      f"opening summary text is readable at 375px ({stat_size}px)")
                check(chrome.evaluate("""(() => {
                    const chart = document.getElementById('benchmark-chart');
                    return chart.scrollWidth <= chart.clientWidth + 1;
                })()"""), "benchmark chart has no horizontal clipping at 375px")
                check(chrome.evaluate("""(() => {
                    const box = document.getElementById('benchmark-chart').getBoundingClientRect();
                    return [...document.querySelectorAll('#benchmark-chart .run-dot circle')]
                      .every(dot => {
                        const r = dot.getBoundingClientRect();
                        return r.left >= box.left - 1 && r.right <= box.right + 1;
                      });
                })()"""), "all nine benchmark points fit inside the chart at 375px")
                check(min(chrome.evaluate("""[...document.querySelectorAll('#pr-strip .chip')]
                      .map(chip => chip.getBoundingClientRect().height)""")) >= 40,
                      "decision-strip chips are at least 40px at 375px")
                check(min(chrome.evaluate("""[...document.querySelectorAll('#selector-chips .chip')]
                      .map(chip => chip.getBoundingClientRect().height)""")) >= 40,
                      "selector chips are at least 40px at 375px")
                check(len(chrome.evaluate(
                    "getComputedStyle(document.querySelector('.selector-showcase')).gridTemplateColumns").split()) == 1,
                    "the selector showcase is one column at 375px")
                check(len(chrome.evaluate(
                    "getComputedStyle(document.querySelector('.figure-grid-4')).gridTemplateColumns").split()) == 1,
                    "the gate screenshot grid is one column at 375px")
            heights = chrome.evaluate("""[...document.querySelectorAll('button, a')]
                .filter(el => !el.classList.contains('evidence-link') && !el.classList.contains('author-link'))
                .map(el => el.getBoundingClientRect().height)
                .filter(h => h > 0)""")
            check(min(heights) >= 40, f"interactive targets are at least 40px at {width}px")
            path = os.path.join(EVIDENCE, f"viewport-{width}.png")
            chrome.screenshot(path, full_page=True)
            check(os.path.isfile(path) and os.path.getsize(path) > 1000,
                  f"viewport screenshot captured at {width}px")
            check(len(exceptions(chrome)) == 0, f"no exceptions at {width}px")

        # Chrome performance metrics on the mobile viewport.
        chrome.set_viewport(375, 812, 1, mobile=True)
        chrome.navigate(base, settle=1.5)
        wait_ready(chrome)
        nav = chrome.evaluate("""(() => {
            const n = performance.getEntriesByType('navigation')[0];
            return JSON.stringify({duration: Math.round(n.duration),
              domContentLoaded: Math.round(n.domContentLoadedEventEnd),
              load: Math.round(n.loadEventEnd),
              transferSize: n.transferSize, decodedBodySize: n.decodedBodySize}); })()""")
        paints = chrome.evaluate("JSON.stringify(performance.getEntriesByType('paint').map(p => ({name: p.name, start: Math.round(p.startTime)})))")
        metrics = {"navigation": json.loads(nav), "paint": json.loads(paints),
                   "viewport": "375x812", "method": "Chrome DevTools Protocol Performance entries",
                   "lighthouse": "separate Lighthouse reports are stored in this evidence folder"}
        with open(os.path.join(EVIDENCE, "performance.json"), "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, indent=2)
            fh.write("\n")
        check(metrics["navigation"]["duration"] > 0, "Chrome navigation metrics recorded")

        # GitHub Pages style subpath in an isolated copy and browser instance.
        subpath_temp = tempfile.mkdtemp(prefix="prk-site-subpath-")
        os.makedirs(os.path.join(subpath_temp, "project"))
        shutil.copytree(SITE, os.path.join(subpath_temp, "project", "site"))
        shutil.copytree(os.path.join(ROOT, "evidence"),
                        os.path.join(subpath_temp, "project", "evidence"))
        shutil.copytree(os.path.join(ROOT, "harness"),
                        os.path.join(subpath_temp, "project", "harness"))
        httpd3, port3 = serve(subpath_temp)
        subpath_chrome = Chrome(port=9254, width=1280, height=900, scale=1)
        try:
            subpath_chrome.navigate(f"http://127.0.0.1:{port3}/project/site/index.html", settle=1.5)
            wait_ready(subpath_chrome)
            check(subpath_chrome.evaluate("document.querySelectorAll('main section').length") == 8,
                  "all sections render from a GitHub Pages style subpath")
            check(subpath_chrome.evaluate("document.querySelectorAll('#pr-strip .chip').length") == 3,
                  "the decision strip works from a GitHub Pages style subpath")
            subpath_chrome.evaluate("document.querySelector('#selective details.extra').open = true")
            load_figures(subpath_chrome)
            subpath_images = subpath_chrome.evaluate("""JSON.stringify([...document.querySelectorAll('.figure img')]
                  .map(img => ({src: img.getAttribute('src'), complete: img.complete,
                                naturalWidth: img.naturalWidth})))""")
            check(subpath_chrome.evaluate("""[...document.querySelectorAll('.figure img')]
                  .every(img => img.complete && img.naturalWidth > 0)"""),
                  "screenshots load from a GitHub Pages style subpath " + subpath_images)
            subpath_links = json.loads(subpath_chrome.evaluate(
                "JSON.stringify([...document.querySelectorAll('#main a[href]')]"
                ".map(a => a.getAttribute('href')))"))
            subpath_repo = [href for href in subpath_links
                            if href.startswith(evidence_base)]
            subpath_paths = [href[len(evidence_base):] for href in subpath_repo]
            check(len(subpath_repo) >= 20,
                  "repository evidence links render from a project subpath")
            check(all(path in manifest_paths for path in subpath_paths),
                  "subpath evidence paths are in release/manifest.json")
            check(all(os.path.isfile(os.path.join(ROOT, path))
                      for path in subpath_paths),
                  "subpath evidence paths exist in the export")
            check(not any(href.startswith("../") for href in subpath_links),
                  "subpath rendering keeps the absolute evidence base")
            check(len(exceptions(subpath_chrome)) == 0,
                  "no exceptions from a GitHub Pages style subpath")
            path = os.path.join(EVIDENCE, "github-pages-subpath-1280.png")
            subpath_chrome.screenshot(path, full_page=True)
            check(os.path.isfile(path), "GitHub Pages subpath screenshot captured")
        finally:
            subpath_chrome.close()
            httpd3.shutdown()
            httpd3.server_close()

        # Assets-removed fallback in an isolated copy.
        temp = tempfile.mkdtemp(prefix="prk-site-no-assets-")
        for name in ("index.html", "styles.css", "app.js", "data.json"):
            shutil.copy2(os.path.join(SITE, name), os.path.join(temp, name))
        httpd2, port2 = serve(temp)
        try:
            chrome.set_viewport(1280, 900, 1)
            no_assets = f"http://127.0.0.1:{port2}/index.html"
            chrome.navigate(no_assets, settle=1.5)
            wait_ready(chrome)
            check(chrome.evaluate("document.querySelectorAll('main section').length") == 8,
                  "all sections render without the assets directory")
            check(chrome.evaluate("document.querySelectorAll('.run-dot').length") == 9,
                  "the chart works without the assets directory")
            check(chrome.evaluate("document.querySelectorAll('#pr-strip .chip').length") == 3
                  and chrome.evaluate("document.querySelectorAll('#pr-strip .strip-step').length") == 4,
                  "the decision strip works without the assets directory")
            # Force the lazy images to request their missing files so the error
            # fallback is exercised even when headless scrolling is throttled.
            chrome.evaluate("""[...document.querySelectorAll('.figure img')].forEach(img => {
                img.loading = 'eager';
                img.src = img.getAttribute('src');
            })""")
            chrome.evaluate("""(async () => {
                for (const fig of document.querySelectorAll('.figure')) {
                    const top = fig.getBoundingClientRect().top + window.scrollY - 200;
                    window.scrollTo({top: Math.max(0, top), behavior: 'instant'});
                    await new Promise(resolve => setTimeout(resolve, 350));
                }
                const deadline = performance.now() + 5000;
                while (performance.now() < deadline &&
                       ![...document.querySelectorAll('.figure')]
                         .every(fig => fig.classList.contains('asset-missing'))) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                window.scrollTo({top: 0, behavior: 'instant'});
            })()""", await_promise=True)
            check(chrome.evaluate("""[...document.querySelectorAll('.figure')]
                  .every(f => f.classList.contains('asset-missing'))"""),
                  "missing screenshots use the textual fallback "
                  + str(chrome.evaluate("""JSON.stringify({url: location.href,
                      figures: [...document.querySelectorAll('.figure')].map(f => ({
                        id: f.id, cls: f.className,
                        imgs: [...f.querySelectorAll('img')].map(img => ({
                          src: img.getAttribute('src'), complete: img.complete,
                          naturalWidth: img.naturalWidth}))}))})""")))
            check(chrome.evaluate("""[...document.querySelectorAll('.figure .fallback')]
                  .every(f => getComputedStyle(f).display !== 'none')"""),
                  "the fallback text is visible")
            check(len(exceptions(chrome)) == 0, "no exceptions with assets removed")
            path = os.path.join(EVIDENCE, "assets-removed-1280.png")
            chrome.screenshot(path, full_page=True)
            check(os.path.isfile(path), "assets-removed screenshot captured")
        finally:
            httpd2.shutdown()
            httpd2.server_close()

        # Keyboard activation follows native button behaviour.
        chrome.evaluate("document.querySelector('#pr-strip .chip[data-name=\"fixed\"]').focus()")
        for kind in ("keyDown", "char", "keyUp"):
            params = {"type": kind, "key": "Enter", "code": "Enter",
                      "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
            if kind == "char":
                params.update({"text": "\r", "unmodifiedText": "\r"})
            chrome.call("Input.dispatchKeyEvent", params)
        check(chrome.evaluate(
            "document.querySelector('#pr-strip .chip[data-name=\"fixed\"]').getAttribute('aria-pressed')") == "true",
            "the decision strip supports keyboard activation")
        check("Passed every check." in (chrome.evaluate(
            "document.querySelector('.strip-body').innerText") or ""),
            "keyboard activation renders the matching decision")

        # Reduced motion shows the same final information without waiting.
        # Use a fresh browser so the media preference is in place for the first
        # script execution, independent of the long normal-motion session.
        reduced_chrome = Chrome(port=9253, width=1280, height=900, scale=1)
        reduced_chrome.call("Emulation.setEmulatedMedia",
                            {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        reduced_chrome.navigate(base, settle=0.2)
        reduced_chrome.navigate(base, settle=0.6)
        wait_ready(reduced_chrome)
        check(reduced_chrome.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"),
              "reduced motion is active for the reduced-motion pass")
        reduced = json.loads(reduced_chrome.evaluate("""JSON.stringify((() => {
            const body = document.querySelector('.strip-body');
            const steps = [...body.querySelectorAll('.strip-step')];
            const reactor = document.querySelector('.reactor-panel');
            const gates = document.getElementById('gate-highlights');
            return {
              play: body.classList.contains('play'),
              op: steps.map(step => parseFloat(getComputedStyle(step).opacity)),
              delays: steps.map(step => getComputedStyle(step).transitionDelay),
              durations: steps.map(step => getComputedStyle(step).transitionDuration),
              text: body.innerText.replace(/\\n+/g, ' | '),
              caption: document.querySelector('#pr-strip figcaption').textContent,
              reactorPlay: reactor.classList.contains('play'),
              reactorOn: document.querySelectorAll('#reactor-illustration span.on').length,
              reactorDuration: getComputedStyle(document.querySelector('#reactor-illustration span.on')).transitionDuration,
              gatePlay: gates.classList.contains('play'),
              barWidths: [...gates.querySelectorAll('.gate-bar span')].map(span => span.style.width),
              barDuration: getComputedStyle(gates.querySelector('.gate-bar span')).transitionDuration,
              badgeOp: [...gates.querySelectorAll('.gate-state, .gate-verdict .status-badge')]
                .map(badge => parseFloat(getComputedStyle(badge).opacity))
            };
        })())"""))
        check(reduced["play"] and all(op > 0.99 for op in reduced["op"]),
              "reduced motion shows every decision step immediately")
        check(reduced["delays"] == ["0s", "0s", "0s", "0s"]
              and all(duration == "0s" for duration in reduced["durations"]),
              "reduced motion removes decision-strip delays and transitions")
        check("Blocked: the changed lines are not tested enough." in reduced["text"],
              "reduced motion keeps the recorded decision text")
        check(all(token in reduced["text"] for token in
                  ("92.33%", "0.00%", "BLOCK"))
              and "build #11" in reduced["caption"],
              "reduced motion keeps the recorded build and coverage values")
        check(reduced["reactorPlay"] and reduced["reactorOn"] == 3
              and reduced["reactorDuration"] == "0s",
              "reduced motion shows the selected reactor cells immediately")
        check(reduced["gatePlay"] and reduced["barWidths"] == ["92.33%", "0%", "94.08%", "100%"]
              and reduced["barDuration"] == "0s",
              "reduced motion shows the final coverage bars immediately")
        check(all(op > 0.99 for op in reduced["badgeOp"]),
              "reduced motion shows the final gate badges immediately")
        reduced_chrome.screenshot(os.path.join(EVIDENCE, "reduced-motion-1280.png"), full_page=True)
        check(os.path.isfile(os.path.join(EVIDENCE, "reduced-motion-1280.png")),
              "reduced-motion screenshot captured at 1280px")
        with open(os.path.join(EVIDENCE, "reduced-motion.json"), "w", encoding="utf-8") as fh:
            json.dump(reduced, fh, indent=2)
            fh.write("\n")
        reduced_chrome.set_viewport(375, 812, 1, mobile=True)
        reduced_chrome.navigate(base, settle=0.6)
        wait_ready(reduced_chrome)
        check(reduced_chrome.evaluate("document.querySelectorAll('#pr-strip .strip-step').length") == 4
              and reduced_chrome.evaluate(
                  "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"),
              "reduced motion keeps the decision strip complete at 375px without overflow")
        reduced_chrome.screenshot(os.path.join(EVIDENCE, "reduced-motion-375.png"), full_page=True)
        check(os.path.isfile(os.path.join(EVIDENCE, "reduced-motion-375.png")),
              "reduced-motion screenshot captured at 375px")
        reduced_chrome.close()
        reduced_chrome = None

        print(f"all site UI checks passed: {CHECKS}")
        return 0
    finally:
        if chrome:
            chrome.close()
        if reduced_chrome:
            reduced_chrome.close()
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
        if subpath_temp:
            shutil.rmtree(subpath_temp, ignore_errors=True)
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        sys.exit(1)
