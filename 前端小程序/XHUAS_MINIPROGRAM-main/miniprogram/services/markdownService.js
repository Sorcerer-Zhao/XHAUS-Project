function makeSpan(text, style) {
  return {
    text: String(text || ""),
    style: style || "normal",
  };
}

function renderInlineMarkdown(value) {
  const text = String(value || "");
  const spans = [];
  const codePattern = /`([^`\n]+?)`/g;
  let codeIndex = 0;
  let codeMatch = null;

  const pushStyled = (segment) => {
    if (!segment) {
      return;
    }
    let index = 0;
  const pattern = /(\*\*([\s\S]+?)\*\*)|(^|[^\*])\*([^*\n]+?)\*(?!\*)/g;
  let match = null;

    while ((match = pattern.exec(segment))) {
    if (match[1]) {
      if (match.index > index) {
          spans.push(makeSpan(segment.slice(index, match.index)));
      }
      spans.push(makeSpan(match[2], "strong"));
      index = match.index + match[1].length;
      continue;
    }

    const prefix = match[3] || "";
    const start = match.index + prefix.length;
    if (start > index) {
        spans.push(makeSpan(segment.slice(index, start)));
    }
    spans.push(makeSpan(match[4], "em"));
    index = start + match[4].length + 2;
  }

    if (index < segment.length) {
      spans.push(makeSpan(segment.slice(index)));
    }
  };

  while ((codeMatch = codePattern.exec(text))) {
    if (codeMatch.index > codeIndex) {
      pushStyled(text.slice(codeIndex, codeMatch.index));
    }
    spans.push(makeSpan(codeMatch[1], "code"));
    codeIndex = codeMatch.index + codeMatch[0].length;
  }

  if (codeIndex < text.length) {
    pushStyled(text.slice(codeIndex));
  }

  return spans.length ? spans : [makeSpan(text)];
}

function tableCells(line) {
  return String(line || "")
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableSeparator(line) {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function isTableStart(lines, index) {
  return (
    index + 1 < lines.length &&
    lines[index].includes("|") &&
    lines[index + 1].includes("|") &&
    isTableSeparator(lines[index + 1])
  );
}

function parseMarkdown(text) {
  const lines = String(text || "").split(/\r?\n/);
  const blocks = [];
  let index = 0;
  let listItems = [];

  const closeList = () => {
    if (listItems.length) {
      blocks.push({
        type: "list",
        items: listItems,
      });
      listItems = [];
    }
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      closeList();
      blocks.push({ type: "space" });
      index += 1;
      continue;
    }

    const codeFence = trimmed.match(/^```(\S*)\s*$/);
    if (codeFence) {
      closeList();
      const language = codeFence[1] || "";
      index += 1;
      const codeLines = [];
      while (index < lines.length && !/^```\s*$/.test(lines[index].trim())) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({
        type: "code",
        language,
        text: codeLines.join("\n"),
      });
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      closeList();
      blocks.push({ type: "hr" });
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      closeList();
      const headers = tableCells(lines[index]).map(renderInlineMarkdown);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const cells = tableCells(lines[index]);
        rows.push(headers.map((_, cellIndex) => renderInlineMarkdown(cells[cellIndex] || "")));
        index += 1;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        spans: renderInlineMarkdown(heading[2]),
      });
      index += 1;
      continue;
    }

    const listItem = trimmed.match(/^[-*]\s+(.+)$/);
    if (listItem) {
      listItems.push(renderInlineMarkdown(listItem[1]));
      index += 1;
      continue;
    }

    closeList();
    blocks.push({
      type: "paragraph",
      spans: renderInlineMarkdown(trimmed),
    });
    index += 1;
  }

  closeList();
  return blocks.length ? blocks : [{ type: "paragraph", spans: [makeSpan("")] }];
}

module.exports = {
  parseMarkdown,
  renderInlineMarkdown,
};
