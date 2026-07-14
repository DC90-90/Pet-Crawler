import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "@heroui/react";
import { useTranslation } from "react-i18next";
import "./i18n";
import "./styles/globals.css";
import "leaflet/dist/leaflet.css";
import { queryClient } from "./lib/queries";
import { router } from "./app/router";

/**
 * HeroUI's I18nProvider drives React-Aria locale + text direction; we feed it
 * the active i18next language so Arabic flips components to RTL correctly.
 */
function Root() {
  const { i18n } = useTranslation();
  return (
    <I18nProvider locale={i18n.language || "en"}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </I18nProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
