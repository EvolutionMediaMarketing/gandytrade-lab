import { Component, type ErrorInfo, type ReactNode } from "react";

/** If any part of the page crashes, show a short message and a reload button instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("GandyTrade page error:", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div style={{ padding: "3rem 1.5rem", maxWidth: 560, margin: "0 auto", color: "#e5edf5", fontFamily: "system-ui, sans-serif" }}>
        <h1 style={{ fontSize: "1.3rem" }}>Something went wrong on this page</h1>
        <p>Your data and paper trades are safe; this is only a display problem in the browser.</p>
        <p>Reload the page. If it happens again, try switching off the last indicator you added.</p>
        <button onClick={() => window.location.reload()} style={{ padding: "0.5rem 1rem", cursor: "pointer" }}>
          Reload
        </button>
      </div>
    );
  }
}
