import { Expand, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { t, useLocale } from "../i18n";
import "./research-markdown.css";

/** Research text stays untouched; formatting is only a reading view. */
export function ResearchMarkdown({ text }: { text: string }) {
  return (
    <div className="research-markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
          // Notes never load remote images implicitly. The reader may open one.
          img: ({ src, alt }) =>
            src ? (
              <a href={src} target="_blank" rel="noopener noreferrer">
                {alt || t("图片链接")}
              </a>
            ) : (
              <span>{alt || t("图片链接")}</span>
            ),
          table: ({ node: _node, ...props }) => (
            <div className="research-markdown-table" tabIndex={0}>
              <table {...props} />
            </div>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}

export function ResearchNoteSource({ text }: { text: string }) {
  return <pre className="research-note-source">{text}</pre>;
}

function ExpandedNotes({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useId();
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return createPortal(
    <dialog
      ref={dialog}
      className="research-notes-dialog"
      aria-labelledby={heading}
      onKeyDown={(event) => event.stopPropagation()}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          const bounds = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
          )
            onClose();
        }
      }}
    >
      <div className="research-notes-dialog-heading">
        <div>
          <span>{t("研究记录")}</span>
          <h2 id={heading}>{title}</h2>
        </div>
        <button
          className="icon-button"
          aria-label={t("关闭阅读窗口")}
          title={t("关闭阅读窗口")}
          onClick={onClose}
          autoFocus
        >
          <X size={18} />
        </button>
      </div>
      <div className="research-notes-dialog-content">{children}</div>
    </dialog>,
    document.body,
  );
}

export function ResearchNotes({
  text,
  title,
}: {
  text: string;
  title: string;
}) {
  useLocale();
  const [source, setSource] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const expandButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (!expanded && restoreFocus.current) {
      expandButton.current?.focus();
      restoreFocus.current = false;
    }
  }, [expanded]);
  const close = () => {
    restoreFocus.current = true;
    setExpanded(false);
  };
  const controls = (
    <div
      className="research-notes-modes"
      role="group"
      aria-label={t("记录显示方式")}
    >
      <button aria-pressed={!source} onClick={() => setSource(false)}>
        {t("阅读")}
      </button>
      <button aria-pressed={source} onClick={() => setSource(true)}>
        {t("Markdown 原文")}
      </button>
    </div>
  );
  const content = source ? (
    <ResearchNoteSource text={text} />
  ) : (
    <ResearchMarkdown text={text} />
  );
  return (
    <section className="research-notes" aria-label={t("研究记录")}>
      <div className="research-notes-toolbar">
        <span>{t("研究记录")}</span>
        <div>
          {controls}
          <button
            ref={expandButton}
            className="icon-button"
            aria-label={t("展开阅读")}
            title={t("展开阅读")}
            onClick={() => setExpanded(true)}
          >
            <Expand size={14} />
          </button>
        </div>
      </div>
      {content}
      {expanded && (
        <ExpandedNotes title={title} onClose={close}>
          {controls}
          {content}
        </ExpandedNotes>
      )}
    </section>
  );
}
