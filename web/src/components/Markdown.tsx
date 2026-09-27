// A small Markdown renderer that builds React elements (never HTML strings):
// headings, paragraphs, lists, tables, bold/italic, inline code and links.
// Model answers and methodology notes go through it; anything it doesn't
// recognise is plain text, so injected markup can't reach the DOM.
import { Fragment, type ReactNode } from "react";

const SAFE_URL = /^(https?:\/\/|\/)[^\s]*$/i;

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("[")) {
      const [, label, href] = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok) ?? [];
      if (label && href && SAFE_URL.test(href)) {
        const external = href.startsWith("http");
        out.push(
          <a
            key={key}
            href={href}
            className="text-accent underline decoration-1 underline-offset-2"
            {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
          >
            {label}
          </a>,
        );
      } else out.push(tok);
    } else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function isTableRow(line: string) {
  return /^\s*\|.*\|\s*$/.test(line);
}

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (!line.trim()) {
      i++;
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const level = Math.min(h[1]!.length + 1, 4);
      const Tag = `h${level}` as "h2" | "h3" | "h4";
      blocks.push(<Tag key={k++}>{inline(h[2]!, `h${k}`)}</Tag>);
      i++;
      continue;
    }
    if (isTableRow(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1]!)) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i]!)) rows.push(cells(lines[i++]!));
      blocks.push(
        <div key={k++} className="overflow-x-auto">
          <table>
            <thead>
              <tr>
                {head.map((c, j) => (
                  <th key={j} scope="col">
                    {inline(c, `th${k}${j}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="num">
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, j) => (
                    <td key={j}>{inline(c, `td${k}${ri}${j}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const bullet = /^\s*[-*]\s+/;
    const ordered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || ordered.test(line)) {
      const isOrdered = ordered.test(line);
      const re = isOrdered ? ordered : bullet;
      const items: string[] = [];
      while (i < lines.length && re.test(lines[i]!)) {
        let item = lines[i]!.replace(re, "");
        i++;
        // Continuation lines indented under the item.
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]!) && !re.test(lines[i]!)) {
          item += " " + lines[i]!.trim();
          i++;
        }
        items.push(item);
      }
      const List = isOrdered ? "ol" : "ul";
      blocks.push(
        <List key={k++}>
          {items.map((it, j) => (
            <li key={j}>{inline(it, `li${k}${j}`)}</li>
          ))}
        </List>,
      );
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i]!.trim() &&
      !/^(#{1,4})\s/.test(lines[i]!) &&
      !bullet.test(lines[i]!) &&
      !ordered.test(lines[i]!) &&
      !isTableRow(lines[i]!)
    ) {
      para.push(lines[i]!.trim());
      i++;
    }
    blocks.push(
      <p key={k++}>
        {para.map((p, j) => (
          <Fragment key={j}>
            {j > 0 && " "}
            {inline(p, `p${k}${j}`)}
          </Fragment>
        ))}
      </p>,
    );
  }
  return <div className={className}>{blocks}</div>;
}
