import { Route, Routes } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { CreateDocumentPage } from "./pages/CreateDocumentPage";
import { ReviewsDashboardPage } from "./pages/ReviewsDashboardPage";
import { ReviewResultRoute } from "./pages/ReviewResultPage";
import { AuditJournalPage } from "./pages/AuditJournalPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <>
      <NavBar />
      <Routes>
        <Route path="/" element={<CreateDocumentPage />} />
        <Route path="/reviews" element={<ReviewsDashboardPage />} />
        <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        <Route path="/audit" element={<AuditJournalPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}
