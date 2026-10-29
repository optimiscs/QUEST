import { escapeHTML } from './format';
  function inlineMarkdown(text) {
    let html = escapeHTML(text);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return html;
  }

  function renderMarkdown(text) {
    const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
    let html = "";
    let paragraph = [];
    let listType = null;
    let listItems = [];
    const flushParagraph = () => {
      if (paragraph.length) {
        html += `<p>${paragraph.map(inlineMarkdown).join("<br>")}</p>`;
        paragraph = [];
      }
    };
    const flushList = () => {
      if (listType && listItems.length) {
        html += `<${listType}>${listItems.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</${listType}>`;
      }
      listType = null;
      listItems = [];
    };
    for (const line of lines) {
      if (/^\s*$/.test(line)) {
        flushParagraph();
        flushList();
        continue;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line.trim());
      if (heading) {
        flushParagraph();
        flushList();
        const level = Math.min(4, heading[1].length + 1);
        html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
        continue;
      }
      if (/^\s*(?:---+|\*\*\*+)\s*$/.test(line)) {
        flushParagraph();
        flushList();
        html += "<hr>";
        continue;
      }
      const unordered = /^\s*[-*+]\s+(.+)$/.exec(line);
      if (unordered) {
        flushParagraph();
        if (listType !== "ul") {
          flushList();
          listType = "ul";
        }
        listItems.push(unordered[1]);
        continue;
      }
      const ordered = /^\s*\d+\.\s+(.+)$/.exec(line);
      if (ordered) {
        flushParagraph();
        if (listType !== "ol") {
          flushList();
          listType = "ol";
        }
        listItems.push(ordered[1]);
        continue;
      }
      if (/^\s*>\s?/.test(line)) {
        flushParagraph();
        flushList();
        html += `<blockquote>${inlineMarkdown(line.replace(/^\s*>\s?/, ""))}</blockquote>`;
        continue;
      }
      flushList();
      paragraph.push(line);
    }
    flushParagraph();
    flushList();
    return html;
  }


export { renderMarkdown };
