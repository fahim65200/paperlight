// Shared helpers for Paperlight tools
(function(){
const P = window.PL = {};
P.$ = s => document.querySelector(s);
P.fmt = b => b < 1024 ? b + " B" : b < 1048576 ? (b/1024).toFixed(1) + " KB" : (b/1048576).toFixed(2) + " MB";
P.baseName = n => n.replace(/\.[^.]+$/, "");
P.esc = s => String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
P.countWords = t => (String(t).match(/[\p{L}\p{N}][\p{L}\p{N}\p{M}'’.\-]*/gu) || []).length;

const downloadsP = (window.claude && typeof window.claude.use === "function")
  ? window.claude.use("downloads").catch(() => null) : Promise.resolve(null);
P.saveFile = async function(blob, filename){
  const d = await downloadsP;
  if (d){
    try { await d.save({ filename, data: blob }); return "saved"; }
    catch(e){
      if (e && e.code === "declined") return "declined";
      if (e && e.code === "rate_limited") return "busy";
      if (e && !["unavailable","not_granted","capability_disabled","capability_removed"].includes(e.code)) throw e;
    }
  }
  const url = URL.createObjectURL(blob), a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  return "saved";
};

// File picker + drag and drop. onFiles receives an array.
P.wireDrop = function(dropEl, inputEl, onFiles){
  inputEl.addEventListener("change", e => { const f = [...e.target.files]; inputEl.value = ""; if (f.length) onFiles(f); });
  ["dragenter","dragover"].forEach(ev => dropEl.addEventListener(ev, e => { e.preventDefault(); dropEl.classList.add("over"); }));
  ["dragleave","drop"].forEach(ev => dropEl.addEventListener(ev, e => { e.preventDefault(); dropEl.classList.remove("over"); }));
  dropEl.addEventListener("drop", e => { const f = [...e.dataTransfer.files]; if (f.length) onFiles(f); });
};

P.tabs = function(){
  const btns = document.querySelectorAll(".tabs button");
  btns.forEach(b => b.addEventListener("click", () => btns.forEach(x => {
    const on = x === b; x.setAttribute("aria-selected", String(on));
    document.getElementById(x.getAttribute("aria-controls")).hidden = !on;
  })));
};

// Read a .docx into ordered blocks: {kind:'h'|'p'|'li'|'cell', text, strong, level}
P.docxBlocks = async function(arrayBuffer){
  if (!window.mammoth) throw new Error("The Word reader didn't load. Check your connection and reload.");
  const { value } = await mammoth.convertToHtml({ arrayBuffer }, { ignoreEmptyParagraphs: true });
  const root = document.createElement("div"); root.innerHTML = value;
  const out = [];
  const walk = (el, inTable) => {
    for (const c of el.children){
      const tag = c.tagName.toLowerCase();
      if (tag === "table"){ c.querySelectorAll("td,th").forEach(td => { const t = td.textContent.trim(); if (t) out.push({ kind: "cell", text: t }); }); continue; }
      if (/^h[1-6]$/.test(tag)){ out.push({ kind: "h", level: +tag[1], text: c.textContent.trim() }); continue; }
      if (tag === "p"){
        const t = c.textContent.trim(); if (!t) continue;
        const strongText = [...c.querySelectorAll("strong")].map(s => s.textContent).join("").trim();
        out.push({ kind: "p", text: t, strong: strongText.length >= t.length * 0.9 });
        continue;
      }
      if (tag === "ul" || tag === "ol"){
        for (const li of c.querySelectorAll(":scope > li")){
          const clone = li.cloneNode(true); clone.querySelectorAll("ul,ol").forEach(n => n.remove());
          const isNote = /^(foot|end)note/.test(li.id || "");
          const t = clone.textContent.replace(/\u2191/g, "").trim(); if (t) out.push({ kind: isNote ? "note" : "li", text: t });
          li.querySelectorAll(":scope > ul, :scope > ol").forEach(sub => walk({ children: [sub] }));
        }
        continue;
      }
      walk(c, inTable);
    }
  };
  walk(root, false);
  return out;
};

// Plain text into blocks (for pasted text)
P.textBlocks = function(text){
  return text.split(/\r?\n/).map(s => s.trim()).filter(Boolean).map(t => ({ kind: "p", text: t, strong: false }));
};

// Is this block a heading? Returns the heading text or null.
P.isHeading = function(b){
  if (b.kind === "h") return b.text;
  if (b.kind !== "p") return null;
  const t = b.text;
  if (t.length > 90) return null;
  if (b.strong) return t;
  if (/^(\d+(\.\d+)*\.?|[IVX]+\.)\s+\p{Lu}/u.test(t) && t.split(/\s+/).length <= 10 && !/[.:;]$/.test(t)) return t;
  if (P.HEAD_RE.test(t.replace(/^(\d+(\.\d+)*\.?|[IVX]+\.)\s*/, ""))) return t;
  return null;
};
P.HEAD_RE = /^(abstract|summary|keywords?|key\s*words|references?|reference\s+list|bibliography|works\s+cited|literature\s+cited|acknowledg(e)?ments?|funding|conflicts?\s+of\s+interest|competing\s+interests?|declarations?(\s+of\s+(competing\s+)?interests?)?|data\s+availability(\s+statement)?|author\s+contributions?|credit\s+authorship.*|ethics(\s+statement)?|appendix.*|appendices|supplementary(\s+material)?s?)\s*:?$/i;
P.REF_HEAD_RE = /^(\d+(\.\d+)*\.?\s*)?(references?|reference\s+list|bibliography|works\s+cited|literature\s+cited)\s*:?$/i;
})();
