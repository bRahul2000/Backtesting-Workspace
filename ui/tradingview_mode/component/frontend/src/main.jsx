import React from "react";
import { createRoot } from "react-dom/client";
import { withStreamlitConnection } from "streamlit-component-lib";
import App, { clientLog } from "./App.jsx";
import { sendEvent } from "./events.js";
import "./styles.css";

const reported = new Set();
function reportError(message) {
  const text = String(message || "Unknown frontend error").slice(0, 500);
  clientLog("error", text);
  if (reported.has(text)) return;
  reported.add(text);
  try { sendEvent("frontend_error", { message: text }); } catch { /* not connected yet */ }
}

window.addEventListener("error", (event) => reportError(event.message));
window.addEventListener("unhandledrejection", (event) => reportError(event.reason?.message || event.reason));

// A render failure must be visible, never a blank frame.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    reportError(`${error.message}${info?.componentStack ? ` @ ${info.componentStack.trim().split("\n")[0]}` : ""}`);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="fatal">
        <b>TradingView Mode failed to render.</b>
        <pre>{String(this.state.error.stack || this.state.error.message).slice(0, 1200)}</pre>
        <button type="button" className="btn primary" onClick={() => this.setState({ error: null })}>Retry</button>
      </div>
    );
  }
}

const Connected = withStreamlitConnection((props) => <ErrorBoundary><App {...props} /></ErrorBoundary>);
createRoot(document.getElementById("root")).render(<Connected />);
