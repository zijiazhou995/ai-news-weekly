(() => {
  const items = [...document.querySelectorAll(".news-item")];
  if (!items.length) return;

  const pageKey = location.pathname.split("/").pop()?.replace(".html", "") || "current";
  const storeKey = `ai-news-feedback:${pageKey}`;
  const hash = (value) => {
    let output = 0;
    for (let index = 0; index < value.length; index += 1) {
      output = (output * 31 + value.charCodeAt(index)) >>> 0;
    }
    return output.toString(36);
  };
  const load = () => {
    try {
      return JSON.parse(localStorage.getItem(storeKey) || "{}");
    } catch (_) {
      return {};
    }
  };
  const save = (state) => localStorage.setItem(storeKey, JSON.stringify(state));
  const state = load();

  const toast = document.createElement("div");
  toast.className = "feedback-toast";
  document.body.appendChild(toast);
  const showToast = (text) => {
    toast.textContent = text;
    toast.classList.add("show");
    window.setTimeout(() => toast.classList.remove("show"), 1400);
  };

  const updateStats = () => {
    const fitCount = Object.values(state).filter((entry) => entry?.fit).length;
    const rewriteCount = Object.values(state).filter((entry) => entry?.rewrite?.trim()).length;
    document.querySelector("[data-fit-count]").textContent = fitCount;
    document.querySelector("[data-rewrite-count]").textContent = rewriteCount;
  };

  const exportFeedback = async () => {
    const records = Object.entries(state).map(([id, entry]) => ({ id, ...entry }));
    const payload = {
      week: pageKey,
      exportedAt: new Date().toISOString(),
      records,
    };
    const text = JSON.stringify(payload, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      showToast("反馈已复制");
    } catch (_) {
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${pageKey}-feedback.json`;
      link.click();
      URL.revokeObjectURL(url);
      showToast("反馈已导出");
    }
  };

  const panel = document.createElement("section");
  panel.className = "feedback-panel";
  panel.innerHTML = `
    <div class="feedback-stats">
      <span class="pill">已勾选 <strong data-fit-count>0</strong></span>
      <span class="pill">已润色 <strong data-rewrite-count>0</strong></span>
    </div>
    <div class="feedback-actions">
      <button class="button copy-feedback" type="button">导出反馈</button>
    </div>
  `;
  document.querySelector(".page-head")?.after(panel);
  panel.querySelector(".copy-feedback").addEventListener("click", exportFeedback);

  items.forEach((item, index) => {
    const brief = item.querySelector(".brief")?.textContent.trim() || "";
    const sourceLink = item.querySelector(".source a");
    const sourceTitle = sourceLink?.textContent.trim() || "";
    const sourceUrl = sourceLink?.href || "";
    const id = hash(`${brief}|${sourceUrl}|${index}`);
    const entry = state[id] || {
      fit: false,
      rewrite: "",
      original: brief,
      sourceTitle,
      sourceUrl,
    };
    state[id] = entry;

    const controls = document.createElement("div");
    controls.className = "news-feedback";
    controls.innerHTML = `
      <label class="fit-check">
        <input type="checkbox" ${entry.fit ? "checked" : ""}>
        <span>符合</span>
      </label>
      <div class="item-actions">
        <button class="edit-toggle" type="button" aria-expanded="false">修改</button>
      </div>
    `;

    const editArea = document.createElement("div");
    editArea.className = "edit-area";
    const textarea = document.createElement("textarea");
    textarea.className = "rewrite-input";
    textarea.placeholder = "输入你的润色版本";
    textarea.value = entry.rewrite || "";
    editArea.append(textarea);
    item.prepend(controls);
    item.append(editArea);

    const checkbox = controls.querySelector("input");
    const button = controls.querySelector(".edit-toggle");

    const syncVisual = () => item.classList.toggle("is-fit", Boolean(entry.fit));
    syncVisual();

    checkbox.addEventListener("change", () => {
      entry.fit = checkbox.checked;
      entry.original = brief;
      entry.sourceTitle = sourceTitle;
      entry.sourceUrl = sourceUrl;
      state[id] = entry;
      save(state);
      syncVisual();
      updateStats();
    });

    button.addEventListener("click", () => {
      const open = !item.classList.contains("is-editing");
      item.classList.toggle("is-editing", open);
      button.setAttribute("aria-expanded", String(open));
      if (open) textarea.focus();
    });

    textarea.addEventListener("input", () => {
      entry.rewrite = textarea.value;
      entry.original = brief;
      entry.sourceTitle = sourceTitle;
      entry.sourceUrl = sourceUrl;
      state[id] = entry;
      save(state);
      updateStats();
    });
  });

  save(state);
  updateStats();
})();
