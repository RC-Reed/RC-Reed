import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Layout } from "./components/Layout";
import { getToken } from "./lib/api";
import Bills from "./pages/Bills";
import Connections from "./pages/Connections";
import Dashboard from "./pages/Dashboard";
import Debt from "./pages/Debt";
import Health from "./pages/Health";
import Investments from "./pages/Investments";
import Login from "./pages/Login";
import Money from "./pages/Money";
import Tasks from "./pages/Tasks";

function RequireAuth({ children }: { children: JSX.Element }) {
  const location = useLocation();
  if (!getToken()) return <Navigate to="/login" state={{ from: location }} replace />;
  return <Layout>{children}</Layout>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/money" element={<RequireAuth><Money /></RequireAuth>} />
      <Route path="/debt" element={<RequireAuth><Debt /></RequireAuth>} />
      <Route path="/investments" element={<RequireAuth><Investments /></RequireAuth>} />
      <Route path="/bills" element={<RequireAuth><Bills /></RequireAuth>} />
      <Route path="/tasks" element={<RequireAuth><Tasks /></RequireAuth>} />
      <Route path="/health" element={<RequireAuth><Health /></RequireAuth>} />
      <Route path="/connections" element={<RequireAuth><Connections /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
