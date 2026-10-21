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
    return this.state.failed ? (
      <main className="empty-state" style={{ height: "100dvh" }}>
        <h2>画布未能加载</h2>
        <button className="button primary" onClick={() => location.reload()}>
          <RefreshCw size={14} />
          重新打开
        </button>
      </main>
    ) : (
      this.props.children
    );
  }
}
