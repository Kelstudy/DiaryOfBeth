(function () {
  "use strict";

  var DATA_URL = "data/statsHistory.json";

  // ---------- formatting helpers ----------

  function formatCompactNumber(value) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    var abs = Math.abs(value);
    if (abs >= 1000000) return (value / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
    if (abs >= 1000) return (value / 1000).toFixed(1).replace(/\.0$/, "") + "K";
    return String(Math.round(value));
  }

  function formatFullNumber(value) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return Math.round(value).toLocaleString("en-US");
  }

  function formatPercent(value) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return value.toFixed(2) + "%";
  }

  function formatDateShort(date) {
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  function formatDateFull(date) {
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function truncateCaption(caption, maxLength) {
    if (!caption) return "(no caption)";
    var singleLine = caption.replace(/\n/g, " ").trim();
    if (singleLine.length <= maxLength) return singleLine;
    return singleLine.slice(0, maxLength - 1).trim() + "…";
  }

  // ---------- data normalization ----------

  // The stored schema evolved across sessions (last30Days -> recentWindow ->
  // pulledSetSummary). Read whichever is present so old history entries
  // still render instead of breaking the page.
  function getSummary(entry) {
    return entry.pulledSetSummary || entry.recentWindow || entry.last30Days || {};
  }

  function normalizeHistory(rawHistory) {
    return rawHistory
      .map(function (entry) {
        var summary = getSummary(entry);
        return {
          pulledAt: new Date(entry.pulledAt),
          profile: entry.profile || {},
          posts: entry.recentPosts || [],
          summary: summary,
        };
      })
      .filter(function (entry) { return !isNaN(entry.pulledAt.getTime()); })
      .sort(function (a, b) { return a.pulledAt - b.pulledAt; });
  }

  // ---------- KPI tiles ----------

  function renderDelta(container, current, previous, isUpGood, formatFn) {
    if (previous === null || previous === undefined || current === null || current === undefined) return;
    var diff = current - previous;
    var el = document.createElement("p");
    if (Math.abs(diff) < 1e-9) {
      el.className = "stat-delta flat";
      el.textContent = "No change since last pull";
    } else {
      var isUp = diff > 0;
      var good = isUp === isUpGood;
      el.className = "stat-delta " + (good ? "up" : "down");
      var arrow = isUp ? "▲" : "▼";
      el.textContent = arrow + " " + formatFn(Math.abs(diff)) + " since last pull";
    }
    container.appendChild(el);
  }

  function buildStatTile(label, valueText, deltaBuilder) {
    var tile = document.createElement("div");
    tile.className = "stat-tile";

    var labelEl = document.createElement("p");
    labelEl.className = "stat-label";
    labelEl.textContent = label;
    tile.appendChild(labelEl);

    var valueEl = document.createElement("p");
    valueEl.className = "stat-value";
    valueEl.textContent = valueText;
    tile.appendChild(valueEl);

    if (deltaBuilder) deltaBuilder(tile);

    return tile;
  }

  function renderKpiRow(history) {
    var container = document.getElementById("kpiRow");
    if (!history.length) return;

    var latest = history[history.length - 1];
    var previous = history.length > 1 ? history[history.length - 2] : null;

    var followers = latest.profile.followersCount;
    var engagementRate = latest.summary.averageEngagementRate;
    var totalInteractions = latest.summary.totalInteractions;
    var accountReach = latest.summary.accountReachSummed;

    container.appendChild(
      buildStatTile("Followers", formatFullNumber(followers), function (tile) {
        if (previous) renderDelta(tile, followers, previous.profile.followersCount, true, formatFullNumber);
      })
    );

    container.appendChild(
      buildStatTile("Engagement rate", formatPercent(engagementRate), function (tile) {
        if (previous) renderDelta(tile, engagementRate, previous.summary.averageEngagementRate, true, formatPercent);
      })
    );

    container.appendChild(
      buildStatTile("Total interactions", formatCompactNumber(totalInteractions), function (tile) {
        if (previous) renderDelta(tile, totalInteractions, previous.summary.totalInteractions, true, formatCompactNumber);
      })
    );

    container.appendChild(
      buildStatTile("Account reach", accountReach === null || accountReach === undefined ? "—" : formatCompactNumber(accountReach), function (tile) {
        if (previous && previous.summary.accountReachSummed != null) {
          renderDelta(tile, accountReach, previous.summary.accountReachSummed, true, formatCompactNumber);
        }
      })
    );
  }

  // ---------- masthead ----------

  function renderMasthead(history) {
    if (!history.length) {
      document.getElementById("accountMeta").textContent = "No data yet — check back after the first scheduled pull.";
      return;
    }
    var latest = history[history.length - 1];
    var profile = latest.profile;

    if (profile.username) {
      document.getElementById("username").textContent = "@" + profile.username;
      document.getElementById("profileLink").href = "https://instagram.com/" + profile.username;
    }

    var metaParts = [];
    if (profile.accountType) metaParts.push(profile.accountType);
    if (profile.followingCount != null) metaParts.push(formatFullNumber(profile.followingCount) + " following");
    if (profile.mediaCount != null) metaParts.push(formatFullNumber(profile.mediaCount) + " posts");
    document.getElementById("accountMeta").textContent = metaParts.join(" · ");

    document.getElementById("asOf").textContent = "Last pulled " + formatDateFull(latest.pulledAt);
  }

  // ---------- line chart (hand-rolled SVG, no dependencies) ----------

  var SVG_NS = "http://www.w3.org/2000/svg";

  function makeSvgEl(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    for (var key in attrs) el.setAttribute(key, attrs[key]);
    return el;
  }

  function renderLineChart(wrapId, emptyId, points, opts) {
    var wrap = document.getElementById(wrapId);
    var emptyMsg = document.getElementById(emptyId);

    if (points.length < 2) {
      wrap.hidden = true;
      emptyMsg.hidden = false;
      return;
    }
    wrap.hidden = false;
    emptyMsg.hidden = true;

    var width = 600, height = 220;
    var padL = 44, padR = 12, padT = 12, padB = 28;
    var plotW = width - padL - padR;
    var plotH = height - padT - padB;

    var xs = points.map(function (p) { return p.x.getTime(); });
    var ys = points.map(function (p) { return p.y; });
    var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
    var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
    if (yMin === yMax) { yMin -= 1; yMax += 1; }
    var yPad = (yMax - yMin) * 0.1;
    yMin -= yPad; yMax += yPad;
    if (xMin === xMax) xMax = xMin + 1;

    function xPos(t) { return padL + ((t - xMin) / (xMax - xMin)) * plotW; }
    function yPos(v) { return padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH; }

    var svg = makeSvgEl("svg", { viewBox: "0 0 " + width + " " + height, role: "img", "aria-label": opts.ariaLabel || "" });

    // gridlines (4 horizontal steps)
    var gridSteps = 4;
    for (var g = 0; g <= gridSteps; g++) {
      var gy = padT + (plotH / gridSteps) * g;
      svg.appendChild(makeSvgEl("line", {
        x1: padL, x2: width - padR, y1: gy, y2: gy,
        stroke: "var(--gridline)", "stroke-width": "1",
      }));
      var val = yMax - ((yMax - yMin) / gridSteps) * g;
      var tick = makeSvgEl("text", {
        x: padL - 8, y: gy + 4, "text-anchor": "end",
        fill: "var(--text-muted)", "font-size": "10",
      });
      tick.textContent = opts.yTickFormat(val);
      svg.appendChild(tick);
    }

    // baseline
    svg.appendChild(makeSvgEl("line", {
      x1: padL, x2: width - padR, y1: padT + plotH, y2: padT + plotH,
      stroke: "var(--baseline)", "stroke-width": "1",
    }));

    // x-axis labels: first and last only
    [points[0], points[points.length - 1]].forEach(function (p, i) {
      var text = makeSvgEl("text", {
        x: xPos(p.x.getTime()), y: height - 6,
        "text-anchor": i === 0 ? "start" : "end",
        fill: "var(--text-muted)", "font-size": "10",
      });
      text.textContent = formatDateShort(p.x);
      svg.appendChild(text);
    });

    // area wash
    var areaPath = "M " + xPos(xs[0]) + " " + yPos(ys[0]);
    for (var i = 1; i < points.length; i++) areaPath += " L " + xPos(xs[i]) + " " + yPos(ys[i]);
    areaPath += " L " + xPos(xs[xs.length - 1]) + " " + (padT + plotH) + " L " + xPos(xs[0]) + " " + (padT + plotH) + " Z";
    svg.appendChild(makeSvgEl("path", { d: areaPath, fill: "var(--series-1-wash)", stroke: "none" }));

    // line
    var linePath = "M " + xPos(xs[0]) + " " + yPos(ys[0]);
    for (var j = 1; j < points.length; j++) linePath += " L " + xPos(xs[j]) + " " + yPos(ys[j]);
    svg.appendChild(makeSvgEl("path", {
      d: linePath, fill: "none", stroke: "var(--series-1)",
      "stroke-width": "2", "stroke-linejoin": "round", "stroke-linecap": "round",
    }));

    // end marker
    var lastX = xPos(xs[xs.length - 1]), lastY = yPos(ys[ys.length - 1]);
    svg.appendChild(makeSvgEl("circle", {
      cx: lastX, cy: lastY, r: 5, fill: "var(--series-1)",
      stroke: "var(--surface-1)", "stroke-width": "2",
    }));

    // direct end-label - clamped so it can never render above the plot area
    var endLabelY = Math.max(lastY - 12, padT + 10);
    var endLabel = makeSvgEl("text", {
      x: lastX - 10, y: endLabelY, "text-anchor": "end",
      fill: "var(--text-primary)", "font-size": "12", "font-weight": "700",
    });
    endLabel.textContent = opts.tooltipFormat(ys[ys.length - 1]);
    svg.appendChild(endLabel);

    // crosshair (hidden until hover)
    var crosshair = makeSvgEl("line", {
      x1: 0, x2: 0, y1: padT, y2: padT + plotH,
      stroke: "var(--baseline)", "stroke-width": "1", opacity: "0",
    });
    svg.appendChild(crosshair);
    var hoverDot = makeSvgEl("circle", {
      r: 5, fill: "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": "2", opacity: "0",
    });
    svg.appendChild(hoverDot);

    // hit layer
    var hitRect = makeSvgEl("rect", {
      x: padL, y: padT, width: plotW, height: plotH, fill: "transparent",
    });
    svg.appendChild(hitRect);

    wrap.innerHTML = "";
    wrap.appendChild(svg);

    var tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    wrap.appendChild(tooltip);

    function findNearestIndex(mouseXFraction) {
      var targetT = xMin + mouseXFraction * (xMax - xMin);
      var nearestIndex = 0, nearestDist = Infinity;
      for (var k = 0; k < points.length; k++) {
        var dist = Math.abs(points[k].x.getTime() - targetT);
        if (dist < nearestDist) { nearestDist = dist; nearestIndex = k; }
      }
      return nearestIndex;
    }

    function showTooltip(index) {
      var p = points[index];
      var px = xPos(p.x.getTime()), py = yPos(p.y);
      crosshair.setAttribute("x1", px);
      crosshair.setAttribute("x2", px);
      crosshair.setAttribute("opacity", "1");
      hoverDot.setAttribute("cx", px);
      hoverDot.setAttribute("cy", py);
      hoverDot.setAttribute("opacity", "1");

      tooltip.innerHTML = "";
      var labelEl = document.createElement("div");
      labelEl.className = "tt-label";
      labelEl.textContent = formatDateFull(p.x);
      var valueEl = document.createElement("div");
      valueEl.className = "tt-value";
      valueEl.textContent = opts.tooltipFormat(p.y);
      tooltip.appendChild(labelEl);
      tooltip.appendChild(valueEl);

      var pxPercent = (px / width) * 100;
      // clamp so the tooltip (which renders above the point) never overflows
      // above the chart card - min 15% keeps it clear of the card header.
      var pyPercent = Math.max((py / height) * 100, 15);
      tooltip.style.left = pxPercent + "%";
      tooltip.style.top = pyPercent + "%";
      tooltip.classList.add("visible");
    }

    function hideTooltip() {
      crosshair.setAttribute("opacity", "0");
      hoverDot.setAttribute("opacity", "0");
      tooltip.classList.remove("visible");
    }

    hitRect.addEventListener("pointermove", function (evt) {
      var rect = svg.getBoundingClientRect();
      var xFraction = (evt.clientX - rect.left) / rect.width;
      var svgXFraction = (xFraction * width - padL) / plotW;
      svgXFraction = Math.max(0, Math.min(1, svgXFraction));
      showTooltip(findNearestIndex(svgXFraction));
    });
    hitRect.addEventListener("pointerleave", hideTooltip);

  }

  // ---------- posts grid ----------

  function renderPosts(history) {
    var grid = document.getElementById("postsGrid");
    if (!history.length) return;
    var latest = history[history.length - 1];
    var posts = latest.posts.slice().sort(function (a, b) {
      return (b.engagementRate || 0) - (a.engagementRate || 0);
    }).slice(0, 6);

    posts.forEach(function (post) {
      var card = document.createElement("a");
      card.className = "post-card";
      card.href = post.permalink || "#";
      card.target = "_blank";
      card.rel = "noopener";

      var typeEl = document.createElement("div");
      typeEl.className = "post-type";
      typeEl.textContent = post.mediaType || "POST";
      card.appendChild(typeEl);

      var captionEl = document.createElement("p");
      captionEl.className = "post-caption";
      captionEl.textContent = truncateCaption(post.caption, 90);
      card.appendChild(captionEl);

      var statsEl = document.createElement("div");
      statsEl.className = "post-stats";

      var likesEl = document.createElement("span");
      var likesStrong = document.createElement("strong");
      likesStrong.textContent = formatCompactNumber(post.likeCount);
      likesEl.appendChild(likesStrong);
      likesEl.appendChild(document.createTextNode(" likes"));

      var engEl = document.createElement("span");
      engEl.className = "post-engagement";
      engEl.textContent = formatPercent(post.engagementRate);

      statsEl.appendChild(likesEl);
      statsEl.appendChild(engEl);
      card.appendChild(statsEl);

      grid.appendChild(card);
    });

    document.getElementById("postsSub").textContent =
      "By engagement rate, from the pull on " + formatDateShort(latest.pulledAt);
  }

  // ---------- boot ----------

  fetch(DATA_URL)
    .then(function (res) {
      if (!res.ok) throw new Error("Failed to load " + DATA_URL);
      return res.json();
    })
    .then(function (rawHistory) {
      var history = normalizeHistory(rawHistory);
      renderMasthead(history);
      renderKpiRow(history);
      renderPosts(history);

      renderLineChart(
        "followerChart", "followerChartEmpty",
        history.map(function (e) { return { x: e.pulledAt, y: e.profile.followersCount }; }),
        {
          ariaLabel: "Follower growth over time",
          yTickFormat: formatCompactNumber,
          tooltipFormat: formatFullNumber,
        }
      );

      renderLineChart(
        "engagementChart", "engagementChartEmpty",
        history.map(function (e) { return { x: e.pulledAt, y: e.summary.averageEngagementRate }; })
          .filter(function (p) { return p.y !== null && p.y !== undefined; }),
        {
          ariaLabel: "Engagement rate over time",
          yTickFormat: formatPercent,
          tooltipFormat: formatPercent,
        }
      );
    })
    .catch(function (err) {
      document.getElementById("accountMeta").textContent = "Couldn't load stats data.";
      console.error(err);
    });
})();
