import React from "react";
import "./App.css";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import { AnalysisProvider } from "@/context/AnalysisContext";
import AppShell from "@/components/layout/AppShell";
import DashboardPage from "@/pages/DashboardPage";
import AnalyzePage from "@/pages/AnalyzePage";
import ReportPage from "@/pages/ReportPage";

function App() {
  return (
    <div className="App dark">
      <BrowserRouter>
        <AnalysisProvider>
          <AppShell>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/analyze" element={<AnalyzePage />} />
              <Route path="/report" element={<ReportPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AppShell>
          <Toaster position="top-right" richColors theme="dark" />
        </AnalysisProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
