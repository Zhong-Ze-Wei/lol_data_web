import { marked } from "marked";
import DOMPurify from "dompurify";

export function renderAnswer(answer) {
  return DOMPurify.sanitize(
    marked.parse(String(answer || ""), { gfm: true, breaks: true }),
    {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["img", "style", "form", "input", "button", "iframe"],
      FORBID_ATTR: ["style", "target"],
    },
  );
}
