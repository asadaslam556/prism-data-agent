import { Fragment } from "react";

// The model writes markdown -- headings, bold, bullet lists -- and we were
// dumping it on the page as plain text, so answers showed literal "#" and
// "**" characters. This renders the subset the model actually uses.
//
// Deliberately not react-markdown: that's ~100KB for a handful of features,
// and this project has kept its frontend dependency-free on purpose. Output is
// built as React elements rather than raw HTML, so model text can never inject
// markup no matter what it writes.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|_[^_]+_)/g;

function renderInline(text, keyPrefix) {
  return text.split(INLINE).filter(Boolean).map((piece, index) => {
    const key = `${keyPrefix}-${index}`;
    if (piece.startsWith("**") && piece.endsWith("**")) {
      return <strong key={key}>{piece.slice(2, -2)}</strong>;
    }
    if (piece.startsWith("`") && piece.endsWith("`")) {
      return <code key={key} className="md-code">{piece.slice(1, -1)}</code>;
    }
    if (
      (piece.startsWith("*") && piece.endsWith("*")) ||
      (piece.startsWith("_") && piece.endsWith("_"))
    ) {
      return <em key={key}>{piece.slice(1, -1)}</em>;
    }
    return <Fragment key={key}>{piece}</Fragment>;
  });
}

/** Group consecutive list lines so they render as one <ul>/<ol>. */
function group(lines) {
  const blocks = [];
  let list = null;

  const closeList = () => {
    if (list) {
      blocks.push(list);
      list = null;
    }
  };

  for (const line of lines) {
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);

    if (bullet) {
      if (list?.type !== "ul") closeList(), (list = { type: "ul", items: [] });
      list.items.push(bullet[1]);
      continue;
    }
    if (numbered) {
      if (list?.type !== "ol") closeList(), (list = { type: "ol", items: [] });
      list.items.push(numbered[1]);
      continue;
    }
    closeList();
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
    } else if (line.trim() === "") {
      blocks.push({ type: "gap" });
    } else {
      const previous = blocks[blocks.length - 1];
      // keep wrapped lines in the same paragraph
      if (previous?.type === "p") previous.text += ` ${line.trim()}`;
      else blocks.push({ type: "p", text: line.trim() });
    }
  }
  closeList();
  return blocks;
}

export default function Markdown({ text, className = "" }) {
  if (!text) return null;
  const blocks = group(String(text).split("\n"));

  return (
    <div className={`md ${className}`.trim()}>
      {blocks.map((block, index) => {
        if (block.type === "gap") return null;
        if (block.type === "heading") {
          const Tag = `h${Math.min(block.level + 2, 6)}`; // h1 in an answer is too loud
          return (
            <Tag key={index} className="md-heading">
              {renderInline(block.text, index)}
            </Tag>
          );
        }
        if (block.type === "ul" || block.type === "ol") {
          const Tag = block.type;
          return (
            <Tag key={index} className="md-list">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item, `${index}-${itemIndex}`)}</li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={index} className="md-paragraph">
            {renderInline(block.text, index)}
          </p>
        );
      })}
    </div>
  );
}
