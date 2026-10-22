import { ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import React, { lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./style.css";

const FindingsPreview = import.meta.env.DEV
  ? lazy(() =>
      import("./preview/FindingsPreview").then(({ FindingsPreview }) => ({
        default: FindingsPreview,
      })),
    )
  : null;

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <ReactFlowProvider>
        {FindingsPreview &&
        new URLSearchParams(window.location.search).get("preview") ===
          "findings" ? (
          <Suspense fallback={null}>
            <FindingsPreview />
          </Suspense>
        ) : (
          <App />
        )}
      </ReactFlowProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
