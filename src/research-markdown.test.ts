import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import {
  ResearchMarkdown,
  ResearchNoteSource,
  ResearchNotes,
} from "./components/ResearchMarkdown";
import { setLocale } from "./i18n";

const read = (text: string) =>
  renderToStaticMarkup(createElement(ResearchMarkdown, { text }));
const unescapeText = (text: string) =>
  text
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#x27;", "'")
    .replaceAll("&amp;", "&");

afterEach(() => setLocale("en"));

describe("research notes reading", () => {
  it("renders research structure including GFM tables, tasks, links and fenced code", () => {
    const html = read(`## Findings

The **grouped split** changes the *conclusion*.

1. Fix the input
2. Compare the held-out result

- [x] Retain predictions
- [ ] Obtain independent data

| Method | Accuracy |
| --- | ---: |
| RBF | 96.06% |

\`\`\`python
score = accuracy(y, prediction)
\`\`\`

[Original evidence](https://example.org/results)
`);
    expect(html).toContain("<h2>Findings</h2>");
    expect(html).toContain("<strong>grouped split</strong>");
    expect(html).toContain("<em>conclusion</em>");
    expect(html).toContain("<ol>");
    expect(html).toContain('type="checkbox"');
    expect(html).toContain("<table>");
    expect(html).toContain("<th>Method</th>");
    expect(html).toContain("96.06%");
    expect(html).toContain('<code class="language-python">');
    expect(html).toContain('href="https://example.org/results"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("keeps the exact stored source, including indentation, Unicode and trailing whitespace", () => {
    const original =
      '\n## 原始记录\n\n    x = "<raw> & unchanged"  \n\n- [ ] Check evidence\n\t# tab\n';
    const html = renderToStaticMarkup(
      createElement(ResearchNoteSource, { text: original }),
    );
    const contents = html.slice(
      html.indexOf(">") + 1,
      html.lastIndexOf("</pre>"),
    );
    // React emits an extra first newline for pre's HTML parsing rule.
    expect(unescapeText(contents).replace(/^\n\n/, "\n")).toBe(original);
  });

  it("does not execute raw HTML or expose javascript/data navigation", () => {
    const html = read(`<script>alert('bad')</script>

<img src="https://invalid.test/tracker.png" onerror="alert(1)">

[unsafe](javascript:alert%281%29)

[encoded](java&#x73;cript:alert%281%29)

![unsafe image](data:text/html;base64,PHNjcmlwdD4=)

<iframe src="https://invalid.test"></iframe>

Safe **finding**.`);
    expect(html).not.toMatch(
      /<script|<iframe|<img|onerror=|href="javascript:|href="data:/i,
    );
    expect(html).toContain("<strong>finding</strong>");
    expect(html).not.toContain("https://invalid.test");
  });

  it("shows image references as links without fetching their resources", () => {
    const html = read(
      "![Confusion matrix](https://example.org/matrix.png)\n\n![Local result](evidence/result.png)",
    );
    expect(html).not.toContain("<img");
    expect(html).not.toContain('rel="preload"');
    expect(html).toContain('href="https://example.org/matrix.png"');
    expect(html).toContain('href="evidence/result.png"');
    expect(html).toContain(">Confusion matrix</a>");
  });

  it("retains complete long code and wide tables within separate scrollable structures", () => {
    const longLine = "prediction_".repeat(300);
    const cells = Array.from({ length: 16 }, (_, i) => `Method ${i}`);
    const html = read(
      `\`\`\`text\n${longLine}\n\`\`\`\n\n| ${cells.join(" | ")} |\n| ${cells.map(() => "---").join(" | ")} |\n| ${cells.map(() => "96.06%").join(" | ")} |`,
    );
    expect(html).toContain(
      `<pre><code class="language-text">${longLine}\n</code></pre>`,
    );
    expect(html.match(/<th>/g)).toHaveLength(16);
    expect(html.match(/<td>/g)).toHaveLength(16);
    expect(html).toContain('class="research-markdown-table" tabindex="0"');
  });

  it("offers reading/source and expanded reading without changing research text in either language", () => {
    const text = "## 原始研究\n\nStill **verbatim**.";
    const render = () =>
      renderToStaticMarkup(
        createElement(ResearchNotes, { text, title: "Research" }),
      );
    setLocale("en");
    expect(render()).toContain("Reading</button>");
    expect(render()).toContain("Source</button>");
    expect(render()).toContain('aria-label="Expand notes"');
    expect(render()).toContain("<h2>原始研究</h2>");
    setLocale("zh-CN");
    expect(render()).toContain("阅读</button>");
    expect(render()).toContain("Markdown 原文</button>");
  });
});
