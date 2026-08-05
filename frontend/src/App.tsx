import { Route, Routes } from "react-router-dom";
import { CreateDocumentPage } from "./pages/CreateDocumentPage";
import { ReviewResultPage } from "./pages/ReviewResultPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<CreateDocumentPage />} />
      <Route path="/reviews/:reviewId" element={<ReviewResultPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
