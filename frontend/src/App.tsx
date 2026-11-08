import { useEffect, useState } from "react";
import DashboardPage from "./pages/Dashboard";
import ProventosPage from "./pages/Proventos";
import EvolucaoPage from "./pages/Evolucao";
import RebalancearPage from "./pages/Rebalancear";
import OportunidadesPage from "./pages/Oportunidades";
import ImportarPage from "./pages/Importar";

const PAGES = [
  { id: "carteira", label: "Carteira", el: <DashboardPage /> },
  { id: "oportunidades", label: "Oportunidades", el: <OportunidadesPage /> },
  { id: "rebalancear", label: "Simular aporte", el: <RebalancearPage /> },
  { id: "evolucao", label: "Evolução", el: <EvolucaoPage /> },
  { id: "proventos", label: "Proventos", el: <ProventosPage /> },
  { id: "importar", label: "Importar e ajustes", el: <ImportarPage /> },
] as const;

const current = () => {
  const h = window.location.hash.replace("#/", "").replace("#", "").split("?")[0];
  return PAGES.some((p) => p.id === h) ? h : "carteira";
};

export default function App() {
  const [page, setPage] = useState<string>(current);
  useEffect(() => {
    const on = () => setPage(current());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  return (
    <div className="min-h-screen">
      <header className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
          <span className="text-lg font-semibold">Wealth Balancer</span>
          <nav className="flex gap-1">
            {PAGES.map((p) => (
              <a
                key={p.id}
                href={`#/${p.id}`}
                className={`rounded-md px-3 py-1.5 text-sm ${page === p.id ? "font-semibold" : "text-2"}`}
                style={page === p.id ? { background: "var(--band)" } : undefined}
              >
                {p.label}
              </a>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">{PAGES.find((p) => p.id === page)!.el}</main>
    </div>
  );
}
