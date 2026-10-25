import { t, useLocale } from "../i18n";
import { RefreshCw } from "lucide-react";
import { Component, type ReactNode } from "react";
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <CanvasFailure /> : this.props.children;
  }
}

function CanvasFailure() {
  useLocale();
  return (
    <main className="empty-state" style={{ height: "100dvh" }}>
      <h2>{t("画布未能加载")}</h2>
      <button className="button primary" onClick={() => location.reload()}>
        <RefreshCw size={14} />
        {t("重新打开")}
      </button>
    </main>
  );
}
