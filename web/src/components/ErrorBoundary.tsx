import { Component, type ErrorInfo, type ReactNode } from "react";

/** Last-resort guard: a rendering error shows a recoverable message instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("SideDeck view error", error, info.componentStack); }
  componentDidUpdate(prev: { resetKey?: string }) { if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false }); }
  render() {
    if (!this.state.failed) return this.props.children;
    return <div role="alert" className="rounded-md border border-loss/40 bg-loss/5 p-4 text-sm">
      <p className="font-medium">This view could not be displayed.</p>
      <p className="mt-1 text-muted">The data did not have the shape this screen expects. Other workspaces still work; reload to try again.</p>
      <button type="button" onClick={() => window.location.reload()} className="mt-3 rounded border border-rule px-3 py-1.5 text-xs hover:bg-raised">Reload</button>
    </div>;
  }
}
